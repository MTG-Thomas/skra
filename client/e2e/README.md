# E2E Testing with Playwright

This directory contains End-to-End (E2E) tests using [Playwright](https://playwright.dev/).

## Quick Start

```bash
# Install dependencies (includes Playwright)
npm install

# Install Playwright browsers
npx playwright install

# Run all tests
npm run test:e2e

# Run tests in UI mode (interactive debugging)
npm run test:e2e:ui

# Run tests in headed mode (see browser)
npm run test:e2e:headed

# Run specific test file
npm run test:e2e -- auth.smoke.spec.ts

# Run tests on specific browser
npm run test:e2e -- --project=chromium

# Debug mode
npm run test:e2e:debug
```

## Test Configuration

### Environment Variables

Create a `.env` file in the `client/` directory:

```bash
# Base URL for tests (default: http://localhost:8080)
E2E_BASE_URL=http://localhost:8080

# Test user credentials
E2E_TEST_EMAIL=test@example.com
E2E_TEST_PASSWORD=TestPassword123!

# Test organization ID
E2E_TEST_ORG_ID=test-org-uuid

# Skip auto-starting dev server (useful for CI)
E2E_SKIP_WEBSERVER=true
```

### Browsers

Playwright is configured to test across multiple browsers:

- **Desktop:** Chromium, Firefox, WebKit (Safari)
- **Mobile:** Chrome (Pixel 5), Safari (iPhone 12)
- **Tablet:** Chrome (Galaxy Tab S4), Safari (iPad Mini)

See `playwright.config.ts` for viewport configurations.

## Test Structure

```
e2e/
├── tests/
│   ├── test-utils.ts           # Shared utilities & fixtures
│   ├── auth.smoke.spec.ts      # Authentication tests
│   ├── navigation.smoke.spec.ts # Navigation & layout tests
│   ├── passwords.smoke.spec.ts  # Password CRUD tests
│   └── responsive.spec.ts      # Mobile/tablet viewport tests
```

## Writing Tests

### Basic Test Structure

```typescript
import { test, expect, navigateToEntity } from './test-utils';

test('should do something', async ({ page }) => {
  // Navigate to a page
  await navigateToEntity(page, 'org-id', 'passwords');
  
  // Perform actions
  await page.getByRole('button', { name: 'Add Password' }).click();
  
  // Make assertions
  await expect(page.getByRole('heading', { name: 'Create Password' })).toBeVisible();
});
```

### Available Utilities

From `test-utils.ts`:

- `test` - Extended test with auto-login fixture
- `expect` - Playwright assertions
- `performLogin(page, email, password)` - Login via UI
- `navigateToOrg(page, orgId)` - Navigate to organization
- `navigateToEntity(page, orgId, entity)` - Navigate to entity list
- `waitForDataTable(page)` - Wait for table to load
- `getTableRowCount(page)` - Get number of table rows

### Best Practices

1. **Use data-testid attributes** for selecting elements:
   ```tsx
   <div data-testid="data-table">...</div>
   ```
   ```typescript
   await page.getByTestId('data-table');
   ```

2. **Use role-based selectors** when possible:
   ```typescript
   await page.getByRole('button', { name: 'Sign in' });
   await page.getByRole('heading', { name: 'Passwords' });
   ```

3. **Wait for network idle** after navigation:
   ```typescript
   await page.waitForLoadState('networkidle');
   ```

4. **Use the auto-login fixture** for tests that need authentication:
   ```typescript
   import { test } from './test-utils';
   
   test('my test', async ({ page }) => {
     // Already logged in!
   });
   ```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: E2E Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 20
          
      - name: Install dependencies
        run: npm ci
        
      - name: Install Playwright browsers
        run: npx playwright install --with-deps
        
      - name: Start services
        run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
        
      - name: Run E2E tests
        run: npm run test:e2e
        env:
          E2E_BASE_URL: http://localhost:8080
          E2E_TEST_EMAIL: test@example.com
          E2E_TEST_PASSWORD: testpassword
          E2E_SKIP_WEBSERVER: true
          
      - name: Upload test results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 30
```

## Troubleshooting

### Tests failing locally

1. **Ensure dev server is running:**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
   ```

2. **Check base URL:**
   ```bash
   curl http://localhost:8080
   ```

3. **Update test credentials** in `.env` to match your local user

4. **Regenerate types** if API changed:
   ```bash
   npm run generate:types
   ```

### Debugging tests

1. **UI Mode** (recommended):
   ```bash
   npm run test:e2e:ui
   ```

2. **Debug mode:**
   ```bash
   npm run test:e2e:debug
   ```

3. **View trace:**
   ```bash
   npx playwright show-trace test-results/trace.zip
   ```

### Common issues

- **Tests timeout:** Increase timeout in `playwright.config.ts`
- **Element not found:** Check if element has correct role/label
- **Flaky tests:** Add retries or use `test.fixme()` for unstable tests

## Resources

- [Playwright Documentation](https://playwright.dev/docs/intro)
- [Best Practices](https://playwright.dev/docs/best-practices)
- [Selectors](https://playwright.dev/docs/locators)
- [Assertions](https://playwright.dev/docs/test-assertions)

## Critical workflows suite (issue #32)

`e2e/tests/critical-workflows.spec.ts` covers the technician paths that
block rollout: login, organization navigation, one credential
create/reveal cycle, and one document create/read cycle. Created entities
use timestamp + random suffixes, so parallel runs (all Playwright
projects) never collide.

Seed prerequisites: the E2E environment must provide a user matching
`E2E_TEST_EMAIL` / `E2E_TEST_PASSWORD` with access to `E2E_TEST_ORG_ID`
(see `client/.env.e2e.example`). No VM is needed for authoring; full
stack validation runs on VM 101 once released, or in CI.

Data lifecycle: no per-test cleanup by design. The suite assumes a
dedicated E2E backend whose database is reset between runs (`./test.sh`
tears test volumes down with `down -v`). On long-lived environments such
as VM 101, either re-seed/reset the database between runs or purge
`Critical E2E*` records afterwards — do not point the suite at a
production or shared-dev database.

```bash
# Local: frontend dev server + API must be up, env vars exported
cd client
npx playwright install --with-deps chromium
npx playwright test critical-workflows.spec.ts --project=chromium

# CI: same spec runs wherever e2e/tests runs; the e2e-tests job pattern is
# npm run test:e2e -- <spec-file> --project=chromium (main pushes only,
# non-blocking while fixtures stabilize — see .github/workflows/ci.yml)
```
