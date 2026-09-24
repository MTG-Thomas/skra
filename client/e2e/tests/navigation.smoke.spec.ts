import { test, expect, navigateToOrg, TEST_ORG } from './test-utils';

/**
 * Smoke Test Suite: Navigation & Layout
 * 
 * Tests that the app renders correctly and navigation works.
 */
test.describe('Navigation and Layout', () => {
  
  test('should display organization selector', async ({ page }) => {
    await page.goto('/organizations');

    // Verify page elements (heading is 'Organizations', see
    // OrganizationsListPage; the critical suite pins the same).
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create Organization' })).toBeVisible();
  });

  test('should navigate to org dashboard', async ({ page }) => {
    // Navigate to a test org
    await navigateToOrg(page, TEST_ORG);

    // Should see the sidebar navigation (the page renders two <nav>
    // landmarks, so target the first).
    await expect(page.locator('nav').first()).toBeVisible();

    // Should see dashboard content
    await expect(page.getByText('Frequently Accessed')).toBeVisible();
  });
  
  test('should navigate between entity sections', async ({ page }) => {
    // Start at dashboard
    await page.goto(`/org/${TEST_ORG}`);
    
    // Click on Passwords in sidebar
    await page.getByRole('link', { name: 'Passwords' }).click();
    await expect(page).toHaveURL(/\/org\/[^/]+\/passwords/);
    await expect(page.getByRole('heading', { name: 'Passwords' })).toBeVisible();
    
    // Click on Configurations in sidebar
    await page.getByRole('link', { name: 'Configurations' }).click();
    await expect(page).toHaveURL(/\/org\/[^/]+\/configurations/);
    // Pages render more than one matching heading (page header plus
    // section titles); the first is the page header.
    await expect(page.getByRole('heading', { name: 'Configurations' }).first()).toBeVisible();

    // Click on Locations in sidebar
    await page.getByRole('link', { name: 'Locations' }).click();
    await expect(page).toHaveURL(/\/org\/[^/]+\/locations/);
    await expect(page.getByRole('heading', { name: 'Locations' }).first()).toBeVisible();

    // Click on Documents in sidebar
    await page.getByRole('link', { name: 'Documents' }).click();
    await expect(page).toHaveURL(/\/org\/[^/]+\/documents/);
  });
  
  test('should display command palette', async ({ page }) => {
    await page.goto(`/org/${TEST_ORG}`);

    // Open command palette with keyboard shortcut (Ctrl+K works on all
    // platforms; the placeholder is scope-dependent, so match loosely).
    await page.keyboard.press('Control+k');

    // Should see command palette dialog
    await expect(page.getByPlaceholder(/Search/)).toBeVisible();

    // Close with escape
    await page.keyboard.press('Escape');

    // Command palette should be hidden
    await expect(page.getByPlaceholder(/Search/)).not.toBeVisible();
  });
  
});
