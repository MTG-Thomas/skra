import type { Page } from '@playwright/test';
import { test, expect } from './test-utils';

/**
 * Expiration Tracking UI (issue #40).
 *
 * Proves the entity badge renders on a custom asset whose flagged date
 * field is near expiration, and the org home page shows the upcoming
 * expirations widget linking to that asset.
 *
 * NOTE: requires a running stack with seeded data (VM101 lease). The API
 * seeding below uses the logged-in browser context, so no separate token
 * is needed. Browser proof is deferred until the #117 VM lease is free.
 */

const STAMP = Date.now();
const EXPIRING_DATE = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000)
  .toISOString()
  .slice(0, 10);

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

async function seedExpiringAsset(page: Page, orgId: string) {
  const headers = await csrfHeaders(page);

  const typeCreate = await page.request.post('/api/custom-asset-types', {
    headers,
    data: {
      name: `E2E SSL Certs ${STAMP}`,
      display_field_key: 'hostname',
      fields: [
        { key: 'hostname', name: 'Hostname', type: 'text', required: true, show_in_list: true },
        {
          key: 'expires_on',
          name: 'Expires On',
          type: 'date',
          required: true,
          show_in_list: true,
          expiration_alert: true,
        },
      ],
    },
  });
  expect(typeCreate.ok()).toBeTruthy();
  const assetType = await typeCreate.json();

  const assetCreate = await page.request.post(
    `/api/organizations/${orgId}/custom-asset-types/${assetType.id}/assets`,
    {
      headers,
      data: {
        values: { hostname: `cert-${STAMP}.example.com`, expires_on: EXPIRING_DATE },
      },
    }
  );
  expect(assetCreate.ok()).toBeTruthy();
  const asset = await assetCreate.json();

  return { typeId: assetType.id as string, assetId: asset.id as string };
}

test.describe('Expiration Tracking', () => {
  test('asset detail shows expiration badge for flagged date field', async ({
    page,
  }) => {
    const orgId = await firstOrgId(page);
    const { typeId, assetId } = await seedExpiringAsset(page, orgId);

    await page.goto(`/org/${orgId}/assets/${typeId}/${assetId}`);
    const badge = page.getByTestId('expiration-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('Expires in 5d');
  });

  test('org home shows upcoming expirations widget', async ({ page }) => {
    const orgId = await firstOrgId(page);
    await seedExpiringAsset(page, orgId);

    await page.goto(`/org/${orgId}`);
    const widget = page.getByTestId('upcoming-expirations-widget');
    await expect(widget).toBeVisible();
    await expect(widget.getByText('Upcoming Expirations')).toBeVisible();
    await expect(widget.getByText(`cert-${STAMP}.example.com`)).toBeVisible();
  });
});
