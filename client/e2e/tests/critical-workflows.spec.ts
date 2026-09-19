import { test as pwTest } from '@playwright/test';
import {
  test,
  expect,
  TEST_USER,
  TEST_ORG_ID,
  performLogin,
  navigateToEntity,
} from './test-utils';

/**
 * Critical Technician Workflows (issue #32).
 *
 * Small, deterministic end-to-end coverage for the paths that block
 * technician work: login, organization navigation, one credential
 * create/reveal cycle, and one document create/read cycle.
 *
 * Data isolation: created entities use timestamped names, so parallel
 * runs never collide and no cleanup step is required.
 *
 * Seed prerequisites (E2E environment):
 * - A user matching E2E_TEST_EMAIL / E2E_TEST_PASSWORD exists.
 * - That user can access the org in E2E_TEST_ORG_ID.
 * See client/e2e/README.md for the local/CI run path.
 */
pwTest.describe('Critical technician workflows', () => {
  pwTest('technician can log in', async ({ page }) => {
    await performLogin(page, TEST_USER.email, TEST_USER.password);

    // Login lands on the org dashboard or the organizations list.
    await expect(page).toHaveURL(/\/(org\/[^/]+|organizations)/);
  });
});

test.describe('Critical technician workflows (authenticated)', () => {
  test('technician can navigate to an organization', async ({ page }) => {
    await page.goto('/organizations');
    await expect(
      page.getByRole('heading', { name: 'Organizations' })
    ).toBeVisible();

    // Org cards carry stable test ids (see OrganizationsListPage).
    await page.locator('[data-testid^="org-card-"]').first().click();
    await expect(page).toHaveURL(/\/org\/[^/]+/);
  });

  test('technician can create and reveal a credential', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG_ID, 'passwords');

    const name = `Critical E2E Credential ${Date.now()}`;
    const secret = `E2e-Secret-${Date.now()}!`;

    await page.getByRole('button', { name: 'Add Password' }).click();
    await page.getByLabel('Name').fill(name);
    await page.getByLabel('Username').fill('e2e-technician');
    await page.getByLabel('Password', { exact: true }).fill(secret);
    await page.getByRole('button', { name: 'Create' }).click();

    // Lands on the password detail page showing the new credential.
    await expect(page).toHaveURL(/\/org\/[^/]+\/passwords\/[^/]+/);
    await expect(page.getByText(name)).toBeVisible();

    // Secret is masked until explicitly revealed.
    await expect(page.getByText('************', { exact: true })).toBeVisible();
    await expect(page.getByText(secret, { exact: true })).toBeHidden();

    // Reveal shows the plaintext; hiding masks it again.
    await page.getByRole('button', { name: 'Reveal password' }).click();
    await expect(page.getByText(secret, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Hide password' }).click();
    await expect(page.getByText('************', { exact: true })).toBeVisible();
  });

  test('technician can create and read a document', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG_ID, 'documents');

    await page.getByRole('button', { name: 'New Document' }).click();
    await expect(page).toHaveURL(/\/org\/[^/]+\/documents\/new/);

    const title = `Critical E2E Document ${Date.now()}`;
    await page.getByPlaceholder('Document name').fill(title);
    await page.getByRole('button', { name: 'Save' }).click();

    // Save navigates to the new document detail page (read path).
    await expect(page).toHaveURL(/\/org\/[^/]+\/documents\/[^/]+/);
    await expect(
      page.getByRole('heading', { name: title, exact: true })
    ).toBeVisible();
  });
});
