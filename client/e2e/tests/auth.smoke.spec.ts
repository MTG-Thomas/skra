import { test, expect, performLogin, TEST_USER } from './test-utils';

/**
 * Smoke Test Suite: Authentication
 *
 * Basic login/logout behavior across browsers. Selectors track the current
 * auth UI (see LoginPage/RegisterPage); seed prerequisites match the
 * critical suite (E2E_TEST_EMAIL / E2E_TEST_PASSWORD user exists).
 */
test.describe('Authentication', () => {
  test('should display login page', async ({ page }) => {
    await page.goto('/login');

    // Current UI renders a "Welcome back" card title with a submit button.
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
  });

  test('should login with valid credentials', async ({ page }) => {
    // Use the shared seeded test user (or E2E_TEST_EMAIL override).
    await performLogin(page, TEST_USER.email, TEST_USER.password);

    // After login, should be inside the app (dashboard root, org page,
    // or org list) — never bounced back to login.
    await expect(page).not.toHaveURL(/\/login/);
  });

  test('should show error with invalid credentials', async ({ page }) => {
    await page.goto('/login');

    // Fill in wrong credentials
    await page.getByLabel('Email').fill('wrong@example.com');
    await page.getByLabel('Password').fill('wrongpassword');

    // Submit form
    await page.getByRole('button', { name: 'Sign in' }).click();

    // Login failure surfaces as a toast error.
    await expect(page.getByText('Invalid email or password')).toBeVisible();

    // Should still be on login page
    expect(page.url()).toContain('/login');
  });

  test('should navigate to register page', async ({ page }) => {
    await page.goto('/login');

    // Current UI links "Sign up" to the register page.
    await page.getByRole('link', { name: 'Sign up' }).click();

    // Should be on register page
    await expect(page).toHaveURL('/register');
    await expect(page.getByRole('heading', { name: 'Create an account' })).toBeVisible();
  });
});
