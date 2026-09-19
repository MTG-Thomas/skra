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
 *
 * Data lifecycle: created records are namespaced per run (timestamp +
 * random suffix) and treated as disposable. The suite assumes a dedicated
 * E2E backend whose database is reset between runs (`./test.sh` runs
 * `down -v`); on long-lived environments, purge `Critical E2E` records
 * or re-seed instead of relying on per-test cleanup.
 */
function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
pwTest.describe('Critical technician workflows', () => {
  pwTest('technician can log in', async ({ page }) => {
    await performLogin(page, TEST_USER.email, TEST_USER.password);

    // Login lands on the dashboard root, an org page, or the org list.
    await expect(page).toHaveURL(/\/(org\/[^/]+|organizations)?([?#]|$)/);
  });
});

test.describe('Critical technician workflows (authenticated)', () => {
  test('technician can navigate to an organization', async ({ page }) => {
    await page.goto('/organizations');
    await expect(
      page.getByRole('heading', { name: 'Organizations' })
    ).toBeVisible();

    // Target the seeded org exactly (see OrganizationsListPage test ids).
    await page.getByTestId(`org-card-${TEST_ORG_ID}`).click();
    await expect(page).toHaveURL(`/org/${TEST_ORG_ID}`);
  });

  test('technician can create and reveal a credential', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG_ID, 'passwords');

    const tag = uniqueSuffix();
    const name = `Critical E2E Credential ${tag}`;
    const secret = `E2e-Secret-${tag}!`;

    // Header icon and empty-state buttons share the name; exactly one is
    // actionable per list state, with the header first in DOM order.
    await page.getByRole('button', { name: 'Add Password' }).first().click();
    // NOTE: labels carry " *" markers ('Name *', 'Password *') and 'Name'
    // substring-matches 'Username', so target the stable input names instead.
    const dialog = page.getByRole('dialog');
    await dialog.locator('input[name="name"]').fill(name);
    await dialog.locator('input[name="username"]').fill('e2e-technician');
    await dialog.locator('input[name="password"]').fill(secret);
    await page.getByRole('button', { name: 'Create' }).click();

    // Lands on the password detail page showing the new credential.
    // NOTE: the name also appears in a sidebar span, so assert the heading.
    await expect(page).toHaveURL(/\/org\/[^/]+\/passwords\/[^/]+/);
    await expect(
      page.getByRole('heading', { name, exact: true })
    ).toBeVisible();

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

    const title = `Critical E2E Document ${uniqueSuffix()}`;
    await page.getByPlaceholder('Document name').fill(title);
    await page.getByRole('button', { name: 'Save' }).click();

    // Save navigates to the new document detail page (read path).
    // The (?!new) guard keeps this from matching the /new editor itself.
    await expect(page).toHaveURL(/\/org\/[^/]+\/documents\/(?!new\b)[^/]+/);
    await expect(
      page.getByRole('heading', { name: title, exact: true })
    ).toBeVisible();
  });
});
