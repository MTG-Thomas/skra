import { test, expect } from './test-utils';

/**
 * Cookie-session auth behavior (issue #90).
 *
 * Asserts the migration contract: after login no Bearer [REDACTED] remain in
 * readable browser storage (session lives in HttpOnly cookies), the session
 * survives reload, and logout ends it. Refresh rotation is exercised
 * implicitly by the authenticated fixture on every spec.
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

  test('logout ends the session', async ({ page }) => {
    await page.getByTestId('user-menu-trigger').click();
    await page.getByRole('menuitem', { name: 'Log out' }).click();

    await expect(page).toHaveURL(/\/login/);

    // Protected routes bounce back to login once cookies are cleared.
    await page.goto('/organizations');
    await expect(page).toHaveURL(/\/login/);
  });
});
