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

/** CSRF header for raw API writes (cookie sessions enforce it). */
async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name.toLowerCase().includes('csrf'));
  expect(csrf?.value).toBeTruthy();
  return { 'X-CSRF-Token': csrf!.value };
}

test.describe('Sync Provenance', () => {
  test('password detail shows provenance card when synced', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const headers = await csrfHeaders(page);
    const create = await page.request.post(`/api/organizations/${orgId}/passwords`, {
      headers,
      data: {
        name: `Provenance PW ${Date.now()}`,
        password: 'Secret123!',
        sync_metadata: SYNC_METADATA,
      },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/passwords/${id}`);
    const card = page.getByTestId('sync-provenance-card');
    await expect(card).toBeVisible();
    await expect(card.getByText('Itglue')).toBeVisible();
    await expect(card.getByText(SYNC_METADATA.external_id)).toBeVisible();
    // Read-only: no buttons, inputs, or textareas inside the card.
    await expect(card.getByRole('button')).toHaveCount(0);
    await expect(card.locator('input, textarea, select')).toHaveCount(0);
  });

  test('unsafe source_url scheme never renders a link', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const headers = await csrfHeaders(page);
    const create = await page.request.post(`/api/organizations/${orgId}/passwords`, {
      headers,
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
    const card = page.getByTestId('sync-provenance-card');
    await expect(card).toBeVisible();
    await expect(card.getByRole('link', { name: 'Open source record' })).toHaveCount(0);
    const hrefs = await page.locator('a[href^="javascript:"]').count();
    expect(hrefs).toBe(0);
  });

  test('password detail hides card gracefully without provenance', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const headers = await csrfHeaders(page);
    const create = await page.request.post(`/api/organizations/${orgId}/passwords`, {
      headers,
      data: { name: `Plain PW ${Date.now()}`, password: 'Secret123!' },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/passwords/${id}`);
    await expect(page.getByTestId('sync-provenance-card')).toHaveCount(0);
  });

  test('location detail shows provenance card when synced', async ({ page }) => {
    const orgId = await firstOrgId(page);

    const headers = await csrfHeaders(page);
    const create = await page.request.post(`/api/organizations/${orgId}/locations`, {
      headers,
      data: { name: `Provenance Loc ${Date.now()}`, sync_metadata: SYNC_METADATA },
    });
    expect(create.ok()).toBeTruthy();
    const { id } = await create.json();

    await page.goto(`/org/${orgId}/locations/${id}`);
    const card = page.getByTestId('sync-provenance-card');
    await expect(card).toBeVisible();
    await expect(card.getByText(SYNC_METADATA.external_id)).toBeVisible();
    await expect(card.getByRole('button')).toHaveCount(0);
  });
});
