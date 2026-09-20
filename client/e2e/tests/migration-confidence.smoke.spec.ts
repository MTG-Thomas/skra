import { expect, test, type Page, type Route } from "@playwright/test";

const TEST_ORG = {
  id: "org-midtown",
  name: "Midtown Technology Group",
  slug: "midtown-technology-group",
  is_enabled: true,
  created_at: "2026-04-24T12:00:00Z",
  updated_at: "2026-04-24T12:00:00Z",
};

const TEST_DOCUMENT = {
  id: "doc-migration-runbook",
  organization_id: TEST_ORG.id,
  name: "Migration Runbook",
  path: "/Operations",
  content: "<h1>Cutover Checklist</h1><p>Verify DNS, redirects, and support contacts.</p>",
  is_enabled: true,
  created_at: "2026-04-24T12:00:00Z",
  updated_at: "2026-04-24T12:30:00Z",
  updated_by_user_id: "user-technician",
  updated_by_user_name: "Taylor Technician",
  metadata: {},
};

const TEST_PASSWORD = {
  id: "password-quick-create",
  organization_id: TEST_ORG.id,
  name: "VPN Credential",
  username: "svc-vpn",
  url: null,
  notes: null,
  has_totp: false,
  is_enabled: true,
  created_at: "2026-04-24T12:00:00Z",
  updated_at: "2026-04-24T12:30:00Z",
  updated_by_user_id: "user-technician",
  updated_by_user_name: "Taylor Technician",
  metadata: {},
};

const SMOKE_TOKEN = `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.${Buffer.from(
  JSON.stringify({ exp: 4102444800, sub: "user-technician" })
).toString("base64url")}.`;

async function installAuthenticatedSession(page: Page) {
  await page.addInitScript(
    ({ org, token }) => {
      window.localStorage.setItem("access_token", token);
      window.localStorage.setItem("refresh_token", token);
      window.localStorage.setItem(
        "skra-auth",
        JSON.stringify({
          state: {
            user: {
              id: "user-technician",
              email: "tech@example.com",
              name: "Taylor Technician",
              role: "administrator",
              is_active: true,
              created_at: "2026-04-24T12:00:00Z",
              updated_at: "2026-04-24T12:00:00Z",
            },
            accessToken: token,
            refreshToken: token,
            isAuthenticated: true,
            needsSetup: false,
          },
          version: 0,
        })
      );
      window.localStorage.setItem(
        "skra-organization",
        JSON.stringify({
          state: {
            currentOrg: org,
          },
          version: 0,
        })
      );
    },
    { org: TEST_ORG, token: SMOKE_TOKEN }
  );
}

async function installSmokeApi(page: Page) {
  await page.route("**/auth/setup/status", (route) =>
    route.fulfill({ json: { needs_setup: false } })
  );
  await page.route("**/auth/refresh", (route) =>
    fulfillJson(route, {
      access_token: SMOKE_TOKEN,
      refresh_token: SMOKE_TOKEN,
    })
  );

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (pathname === "/api/organizations") {
      return fulfillJson(route, [TEST_ORG]);
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}`) {
      return fulfillJson(route, TEST_ORG);
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/sidebar`) {
      return fulfillJson(route, {
        passwords_count: 2,
        locations_count: 1,
        documents_count: 1,
        configurations_count: 1,
        configuration_types: [],
        custom_asset_types: [],
      });
    }

    if (pathname === "/api/me/recent") {
      return fulfillJson(route, []);
    }

    if (pathname === "/api/me/favorites") {
      return fulfillJson(route, {
        items: [],
        total: 0,
      });
    }

    if (pathname === "/api/me/favorites/check") {
      return fulfillJson(route, {
        is_favorite: false,
      });
    }

    if (pathname === "/api/configuration-types") {
      return fulfillJson(route, []);
    }

    if (pathname === "/api/configuration-statuses") {
      return fulfillJson(route, []);
    }

    if (
      pathname === `/api/organizations/${TEST_ORG.id}/passwords` &&
      request.method() === "POST"
    ) {
      const payload = request.postDataJSON();
      return fulfillJson(route, {
        ...TEST_PASSWORD,
        name: payload.name,
        username: payload.username ?? null,
        url: payload.url ?? null,
        notes: payload.notes ?? null,
      });
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/passwords/${TEST_PASSWORD.id}`) {
      return fulfillJson(route, TEST_PASSWORD);
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/attachments`) {
      return fulfillJson(route, {
        items: [],
        total: 0,
      });
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/relationships/resolved`) {
      return fulfillJson(route, {
        relationships: [],
      });
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/documents`) {
      return fulfillJson(route, {
        items: [TEST_DOCUMENT],
        total: 1,
        limit: 1000,
        offset: 0,
      });
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/documents/folders`) {
      return fulfillJson(route, {
        folders: [{ path: "/Operations", count: 1 }],
      });
    }

    if (pathname === `/api/organizations/${TEST_ORG.id}/documents/${TEST_DOCUMENT.id}`) {
      return fulfillJson(route, TEST_DOCUMENT);
    }

    if (pathname === "/api/search") {
      return fulfillJson(route, {
        query: url.searchParams.get("q") ?? "",
        total: 1,
        results: [
          {
            entity_id: TEST_DOCUMENT.id,
            entity_type: "document",
            organization_id: TEST_ORG.id,
            organization_name: TEST_ORG.name,
            name: TEST_DOCUMENT.name,
            snippet: "Cutover Checklist",
            updated_at: TEST_DOCUMENT.updated_at,
            is_enabled: true,
          },
        ],
      });
    }

    return route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({
        error: "Unhandled smoke API route",
        method: request.method(),
        pathname,
      }),
    });
  });
}

async function fulfillJson(route: Route, json: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(json),
  });
}

test.describe("Smoke: Midtown migration confidence", () => {
  test.beforeEach(async ({ page }) => {
    await installAuthenticatedSession(page);
    await installSmokeApi(page);
  });

  test("smoke: authenticated session renders the technician navigation shell", async ({ page }) => {
    await page.goto(`/org/${TEST_ORG.id}`, { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: TEST_ORG.name })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("button", { name: /Search/i })).toBeVisible();
    await expect(page.getByRole("link", { name: "Passwords" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Documents" })).toBeVisible();
  });

  test("smoke: quick create opens from nav, creates a password, and offers next action", async ({ page }) => {
    await page.goto(`/org/${TEST_ORG.id}`, { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: "Quick create" }).click();
    const menu = page.getByRole("menu");
    await expect(menu.getByRole("menuitem", { name: "Organization" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Password" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Configuration" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Document" })).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Location" })).toBeVisible();

    await menu.getByRole("menuitem", { name: "Password" }).click();

    const createDialog = page.getByRole("dialog", { name: "Create Password" });
    await expect(createDialog).toBeVisible();
    await createDialog.getByLabel("Name *").fill(TEST_PASSWORD.name);
    await createDialog.getByLabel("Password *").fill("correct horse battery staple");
    await createDialog.getByRole("button", { name: "Create" }).click();

    const successDialog = page.getByRole("dialog", { name: "Password created" });
    await expect(successDialog).toBeVisible();
    await expect(successDialog.getByText(`Created in ${TEST_ORG.name}.`)).toBeVisible();
    await expect(successDialog.getByRole("button", { name: "Stay here" })).toBeVisible();
    await successDialog.getByRole("button", { name: "Open password" }).click();

    await expect(page).toHaveURL(`/org/${TEST_ORG.id}/passwords/${TEST_PASSWORD.id}`);
  });

  test("smoke: global search opens, returns document results, and closes cleanly", async ({ page }) => {
    await page.goto(`/org/${TEST_ORG.id}`, { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: /Search/i }).click();
    const searchInput = page.getByPlaceholder(`Search in ${TEST_ORG.name}...`);
    await expect(searchInput).toBeVisible();
    await expect(page.getByText("Type at least 2 characters to search")).toBeVisible();

    await searchInput.fill("mi");
    await expect(page.getByRole("option", { name: /Migration Runbook/ })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(searchInput).not.toBeVisible();

    await page.getByRole("button", { name: /Search/i }).click();
    await expect(page.getByPlaceholder(`Search in ${TEST_ORG.name}...`)).toBeVisible();
  });

  test("smoke: document detail remains reachable on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/org/${TEST_ORG.id}/documents/${TEST_DOCUMENT.id}`, {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: "Cutover Checklist" })).toBeVisible();
  });
});
