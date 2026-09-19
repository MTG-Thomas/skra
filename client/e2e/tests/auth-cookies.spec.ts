import { test, expect } from './test-utils';

/**
 * Cookie-session auth behavior (issue #90).
 *
 * Asserts the migration contract: after login no Bearer [REDACTED] remain in
 * readable browser storage (session lives in HttpOnly cookies), the session
 * survives reload, access-cookie expiry triggers a CSRF-guarded refresh
 * rotation, and logout ends it.
 *
 * Same seed prerequisites as the critical suite (see README).
 */
test.describe('Cookie session auth', () => {
  test('login persists no readable tokens', async ({ page }) => {
    // The auth fixture already logged in via the UI.
    const stored = await page.evaluate(() => ({
      accessToken: localStorage.getItem('access_token'),
      refreshToken: localStorage.getItem('refresh_token'),
      persisted: localStorage.getItem('bifrost-docs-auth'),
    }));

    expect(stored.accessToken).toBeNull();
    expect(stored.refreshToken).toBeNull();

    // The zustand persist entry may exist for profile state, but must not
    // carry tokens.
    if (stored.persisted) {
      const state = JSON.parse(stored.persisted).state ?? {};
      expect(state).not.toHaveProperty('accessToken');
      expect(state).not.toHaveProperty('refreshToken');
    }
  });

  test('session survives reload', async ({ page }) => {
    await page.reload();
    // Still inside the app, not bounced to login.
    await expect(page).not.toHaveURL(/\/login/);
  });

  test('expired access cookie triggers CSRF-guarded refresh', async ({
    page,
    context,
  }) => {
    // Simulate access-token expiry by dropping only that cookie. Refresh
    // and CSRF cookies stay, mirroring a live session past access TTL.
    await context.clearCookies({ name: 'access_token' });

    // The first 401 triggers the credentialed refresh rotation.
    const [refreshRequest] = await Promise.all([
      page.waitForRequest(
        (req) =>
          req.url().includes('/auth/refresh') && req.method() === 'POST'
      ),
      page.reload(),
    ]);

    // The rotation carries the double-submit CSRF header. Without it the
    // API answers 403 (see server enforcement) and the client logs out,
    // so reaching the app below proves the header was sent and accepted.
    expect(refreshRequest.headers()['x-csrf-token']).toBeTruthy();

    // Rotation succeeded: still inside the app, tokens never readable.
    await expect(page).not.toHaveURL(/\/login/);
    const stored = await page.evaluate(() => ({
      accessToken: localStorage.getItem('access_token'),
      refreshToken: localStorage.getItem('refresh_token'),
    }));
    expect(stored.accessToken).toBeNull();
    expect(stored.refreshToken).toBeNull();
  });

  test('OAuth callback rejects unverifiable state', async ({ page }) => {
    // Provider matches the initiated flow but no oauth_state is stored
    // (fresh context): the callback must fail closed at the state gate
    // instead of exchanging the code without CSRF verification.
    await page.goto('/login');
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_provider', 'github');
    });
    await page.goto('/auth/callback/github?code=fake-code&state=no-stored-state');

    // NOTE: the CardTitle renders a generic, not a heading role.
    await expect(page.getByText('Authentication Failed')).toBeVisible();
    await expect(
      page.getByText('State mismatch - possible CSRF attack')
    ).toBeVisible();
  });

  test('OAuth callback rejects provider mismatch', async ({ page }) => {
    // Stored state matches, but the path provider differs from the one
    // that initiated the flow: the callback must fail closed instead of
    // routing the code to the attacker's provider exchange.
    await page.goto('/login');
    await page.evaluate(() => {
      sessionStorage.setItem('oauth_state', 'stored-state');
      sessionStorage.setItem('oauth_provider', 'github');
    });
    await page.goto('/auth/callback/gitlab?code=fake-code&state=stored-state');

    await expect(page.getByText('Authentication Failed')).toBeVisible();
    await expect(
      page.getByText('Provider mismatch - possible CSRF attack')
    ).toBeVisible();
  });

  test('logout ends the session', async ({ page }) => {
    await page.getByTestId('user-menu-trigger').click();
    await page.getByRole('menuitem', { name: 'Log out' }).click();

    await expect(page).toHaveURL(/\/login/);

    // Protected routes bounce back to login once cookies are cleared.
    await page.goto('/organizations');
    await expect(page).toHaveURL(/\/login/);
  });
});
