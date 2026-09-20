import { test, expect, TEST_ORG_ID } from './test-utils';
import type { Page } from '@playwright/test';

/**
 * Interactive checklist/SOP custom asset fields (issue #37).
 *
 * Covers: ordered steps with progress, checking a step (server-stamped),
 * persistence across reload, reset, and completion % in list views.
 *
 * Seed prerequisites: an E2E user (owner, for global type management) with
 * access to E2E_TEST_ORG_ID — same as the critical suite.
 */

async function apiFetch(page: Page, method: string, path: string, body?: unknown) {
  // Same-origin fetch inherits the session cookies; attach the readable
  // CSRF cookie value for cookie-authenticated mutations.
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.cookie
        .split('; ')
        .find((c) => c.startsWith('csrf_token='))
        ?.split('=')[1];
      const res = await fetch(path, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`${method} ${path}: ${res.status}`);
      return (await res.json()) as { id: string };
    },
    { method, path, body }
  );
}

test.describe('Checklist custom asset field', () => {
  test('toggle persists, progress and list % update, reset clears', async ({ page }) => {
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    // Setup via API: checklist type + empty asset.
    const typeRes = await apiFetch(page, 'POST', '/api/custom-asset-types', {
      name: `SOP E2E ${suffix}`,
      fields: [
        {
          key: 'steps',
          name: 'Procedure',
          type: 'checklist',
          show_in_list: true,
          checklist_items: [
            { id: 's1', label: 'First step' },
            { id: 's2', label: 'Second step', required: true },
          ],
        },
      ],
    });
    const assetRes = await apiFetch(
      page,
      'POST',
      `/api/organizations/${TEST_ORG_ID}/custom-asset-types/${typeRes.id}/assets`,
      { values: {} }
    );

    // Detail page: ordered steps, 0% progress.
    await page.goto(`/org/${TEST_ORG_ID}/assets/${typeRes.id}/${assetRes.id}`);
    await expect(page.getByText('First step')).toBeVisible();
    await expect(page.getByText('Second step')).toBeVisible();
    await expect(page.getByText('0% (0/2)')).toBeVisible();

    // Check the first step: progress updates, stamp shown.
    await page.getByRole('checkbox', { name: 'First step' }).click();
    await expect(page.getByText('50% (1/2)')).toBeVisible();

    // Persistence across reload (server-owned state).
    await page.reload();
    await expect(page.getByText('50% (1/2)')).toBeVisible();

    // List view shows completion %.
    await page.goto(`/org/${TEST_ORG_ID}/assets/${typeRes.id}`);
    await expect(page.getByText('50% (1/2)').first()).toBeVisible();

    // Reset clears all steps.
    await page.goto(`/org/${TEST_ORG_ID}/assets/${typeRes.id}/${assetRes.id}`);
    await page.getByRole('button', { name: 'Reset checklist' }).click();
    await expect(page.getByText('0% (0/2)')).toBeVisible();
  });
});
