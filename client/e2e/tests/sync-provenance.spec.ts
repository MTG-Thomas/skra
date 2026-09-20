import type { Page } from '@playwright/test';
import { test, expect } from './test-utils';

/**
 * Sync Provenance UI (issue #35).
 *
 * Proves the read-only Sync Provenance card renders source, external ID,
 * and freshness on entity detail views, and degrades gracefully when the
 * entity was never synced.
 *
 * NOTE: requires a running stack with seeded data (VM101 lease). The API
 * seeding below uses the logged-in browser context, so no separate token
 * is needed.
 */

const SYNC_METADATA = {
  source_system: 'itglue',
  source_tenant_id: 'tenant-123',
  external_id: `e2e-provenance-${Date.now()}`,
  last_synced_at: new Date().toISOString(),
  sync_status: 'synced',
  sync_hash: 'sha256:e2e',
};

async function firstOrgId(page: Page): Promise<string> {
  const response = await page.request.get('/api/organizations');
  expect(response.ok()).toBeTruthy();
  const orgs = await response.json();
  expect(orgs.length).toBeGreaterThan(0);
  return orgs[0].id;
}

test.describe('Sync Provenance', () => {
  test('password detail shows provenance card when synced', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const create = await page.request.post(`/api/organizations/${orgId}/passwords`, {
      data: {
        name: `Provenance PW ${Date.now()}`,
        password: 'Secret123!',
        sync_metadata: SYNC_METADATA,
      },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/passwords/${id}`);
    await expect(page.getByText('Sync Provenance')).toBeVisible();
    await expect(page.getByText('Itglue')).toBeVisible();
    await expect(page.getByText(SYNC_METADATA.external_id)).toBeVisible();
  });

  test('unsafe source_url scheme never renders a link', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const create = await page.request.post(`/api/organizations/${orgId}/passwords`, {
      data: {
        name: `Unsafe URL PW ${Date.now()}`,
        password: 'Secret123!',
        sync_metadata: { ...SYNC_METADATA, source_url: 'javascript:alert(1)' },
      },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/passwords/${id}`);
    // Card still renders (source/external ID are plain text), but no anchor
    // may point at the unsafe scheme.
    await expect(page.getByText('Sync Provenance')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Open source record' })).toHaveCount(0);
    const hrefs = await page.locator('a[href^="javascript:"]').count();
    expect(hrefs).toBe(0);
  });

  test('password detail hides card gracefully without provenance', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const create = await page.request.post(`/api/organizations/${orgId}/passwords`, {
      data: { name: `Plain PW ${Date.now()}`, password: 'Secret123!' },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/passwords/${id}`);
    await expect(page.getByText('Sync Provenance')).toHaveCount(0);
  });

  test('location detail shows provenance card when synced', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const create = await page.request.post(`/api/organizations/${orgId}/locations`, {
      data: { name: `Provenance Loc ${Date.now()}`, sync_metadata: SYNC_METADATA },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/locations/${id}`);
    await expect(page.getByText('Sync Provenance')).toBeVisible();
    await expect(page.getByText(SYNC_METADATA.external_id)).toBeVisible();
  });
});
