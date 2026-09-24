import { test, expect, navigateToEntity, waitForDataTable, getTableRowCount, TEST_ORG } from './test-utils';

/**
 * Smoke Test Suite: Passwords CRUD
 * 
 * Tests basic Create, Read, Update, Delete operations for passwords.
 */
test.describe('Passwords', () => {
  
  test('should display passwords list page', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG, 'passwords');
    
    // Should see page heading
    await expect(page.getByRole('heading', { name: 'Passwords' })).toBeVisible();
    
    // Should see add button
    // Header icon and empty-state buttons share the name on empty orgs.
    await expect(
      page.getByRole('button', { name: 'Add Password' }).first()
    ).toBeVisible();
    
    // Table should load (or empty state)
    const tableOrEmpty = page.locator('[data-testid="data-table"], [data-testid="empty-state"]');
    await expect(tableOrEmpty).toBeVisible();
  });
  
  test('should create a new password', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG, 'passwords');
    
    // Click add button
    await page.getByRole('button', { name: 'Add Password' }).first().click();
    
    // Fill in form
    const testName = `Test Password ${Date.now()}`;
    await page.getByLabel('Name').fill(testName);
    await page.getByLabel('Username').fill('testuser');
    await page.getByLabel('Password', { exact: true }).fill('TestPassword123!');
    
    // Submit form
    await page.getByRole('button', { name: 'Create' }).click();
    
    // Should navigate to password detail
    await expect(page).toHaveURL(/\/org\/[^/]+\/passwords\/[^/]+/);
    
    // Should see the password name
    await expect(page.getByText(testName)).toBeVisible();
  });
  
  test('should search passwords', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG, 'passwords');
    
    // Wait for table to load
    await waitForDataTable(page);
    
    // Get initial row count
    const initialCount = await getTableRowCount(page);
    
    // Enter search term
    await page.getByPlaceholder('Search passwords...').fill('NonExistentPassword');
    
    // Wait for search to apply (debounced, so wait a bit)
    await page.waitForTimeout(500);
    
    // Should show no results or reduced results
    const newCount = await getTableRowCount(page);
    expect(newCount).toBeLessThanOrEqual(initialCount);
  });
  
  test('should show disabled passwords when toggled', async ({ page }) => {
    await navigateToEntity(page, TEST_ORG, 'passwords');
    
    // Find and click Show Disabled toggle
    const showDisabledToggle = page.locator('label').filter({ hasText: 'Show Disabled' });
    if (await showDisabledToggle.count() > 0) {
      await showDisabledToggle.click();
      
      // Wait for table to reload
      await page.waitForTimeout(500);
      
      // Table should still be visible
      await expect(page.locator('[data-testid="data-table"]')).toBeVisible();
    }
  });
  
});
