import { test as base, expect, Page } from '@playwright/test';

/**
 * Test user credentials for E2E tests.
 * In a real CI environment, these would come from environment variables
 * or be created dynamically via API calls.
 */
export const TEST_USER = {
  email: process.env.E2E_TEST_EMAIL || 'test@example.com',
  password: process.env.E2E_TEST_PASSWORD || 'TestPassword123!',
};

/**
 * Test organization ID for tests that need it.
 * Should be an org that the test user has access to.
 */
export const TEST_ORG_ID = process.env.E2E_TEST_ORG_ID || 'test-org-uuid';

/**
 * Org route segment for specs that navigate to `/org/<id>`.
 * CI seeds a fresh org per run and exports its UUID via E2E_TEST_ORG_ID;
 * local runs keep the legacy 'test-org' slug.
 */
export const TEST_ORG = process.env.E2E_TEST_ORG_ID || 'test-org';

/**
 * Extended test fixture with helper methods.
 */
export const test = base.extend<{
  loginPage: Page;
  orgPage: Page;
}>({
  // Auto-login fixture - logs in before each test
  page: async ({ page }, use) => {
    await performLogin(page, TEST_USER.email, TEST_USER.password);
    await use(page);
  },
});

export { expect } from '@playwright/test';

/**
 * Perform login via the UI.
 * 
 * @param page - Playwright page object
 * @param email - User email
 * @param password - User password
 */
export async function performLogin(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login');
  
  // Fill in login form
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  
  // Submit form
  await page.getByRole('button', { name: 'Sign in' }).click();
  
  // Wait for navigation to complete (dashboard root, org page, or org list).
  // LoginPage navigates to "/" on success, so the bare root must match.
  // NOTE: Playwright matches against the full URL (including origin), so
  // the pattern must not anchor at string start.
  await page.waitForURL(/\/(org\/[^/]+|organizations)?([?#]|$)/, {
    timeout: 10000,
  });
}

/**
 * Navigate to a specific organization.
 * 
 * @param page - Playwright page object
 * @param orgId - Organization ID
 */
export async function navigateToOrg(page: Page, orgId: string): Promise<void> {
  await page.goto(`/org/${orgId}`);
  await page.waitForLoadState('networkidle');
}

/**
 * Navigate to a specific entity list page within an org.
 * 
 * @param page - Playwright page object
 * @param orgId - Organization ID
 * @param entity - Entity type (passwords, configurations, locations, documents)
 */
export async function navigateToEntity(
  page: Page, 
  orgId: string, 
  entity: 'passwords' | 'configurations' | 'locations' | 'documents'
): Promise<void> {
  await page.goto(`/org/${orgId}/${entity}`);
  await page.waitForLoadState('networkidle');
}

/**
 * Wait for the DataTable to be fully loaded.
 * 
 * @param page - Playwright page object
 */
export async function waitForDataTable(page: Page): Promise<void> {
  // Wait for the table to be visible
  await page.waitForSelector('[data-testid="data-table"]', { timeout: 10000 });
  
  // Wait for loading to complete (no loading spinner)
  const loadingSpinner = page.locator('[data-testid="table-loading"]');
  await loadingSpinner.waitFor({ state: 'hidden', timeout: 10000 });
}

/**
 * Get the number of rows in the DataTable.
 * 
 * @param page - Playwright page object
 * @returns Number of visible rows
 */
export async function getTableRowCount(page: Page): Promise<number> {
  const rows = page.locator('[data-testid="data-table"] tbody tr');
  return await rows.count();
}

/**
 * Create a test password via API.
 * Useful for setting up test data.
 * 
 * @param apiContext - API request context
 * @param orgId - Organization ID
 * @param name - Password name
 * @param password - Password value
 */
export async function createTestPassword(
  apiContext: { post: (url: string, options: { data: object }) => Promise<{ ok: () => boolean; json: () => Promise<any> }> },
  orgId: string,
  name: string,
  password: string
): Promise<string> {
  const response = await apiContext.post(`/api/organizations/${orgId}/passwords`, {
    data: {
      name,
      username: 'testuser',
      password,
      is_enabled: true,
    },
  });
  
  if (!response.ok()) {
    throw new Error('Failed to create test password');
  }
  
  const data = await response.json();
  return data.id;
}
