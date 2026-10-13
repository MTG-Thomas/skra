import { defineConfig, devices } from '@playwright/test';

const e2ePort = process.env.E2E_PORT || '5173';
if (!/^\d{1,5}$/.test(e2ePort) || Number(e2ePort) < 1 || Number(e2ePort) > 65535) {
  throw new Error('E2E_PORT must be a decimal TCP port between 1 and 65535');
}
const e2eBaseURL = process.env.E2E_BASE_URL || `http://localhost:${e2ePort}`;

/**
 * Playwright E2E Test Configuration
 * 
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './e2e/tests',
  
  /* Run tests in files in parallel */
  fullyParallel: true,
  
  /* Fail the build on CI if you accidentally left test.only in the source code */
  forbidOnly: !!process.env.CI,
  
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  
  /* Opt out of parallel tests on CI */
  workers: process.env.CI ? 1 : undefined,
  
  /* Reporter to use */
  reporter: [
    ['html', { open: 'never' }],
    ['list']
  ],
  
  /* Shared settings for all the projects below */
  use: {
    /* Base URL to use in actions like `await page.goto('/')` */
    baseURL: e2eBaseURL,
    
    /* Collect trace when retrying the failed test */
    trace: 'on-first-retry',
    
    /* Screenshot on failure */
    screenshot: 'only-on-failure',
    
    /* Video on failure */
    video: 'on-first-retry',
  },

  /* Configure projects for major browsers */
  projects: [
    // Chromium (desktop)
    {
      name: 'chromium',
      use: { 
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 720 }
      },
    },
    
    // Firefox (desktop)
    {
      name: 'firefox',
      use: { 
        ...devices['Desktop Firefox'],
        viewport: { width: 1280, height: 720 }
      },
    },
    
    // WebKit (Safari - desktop)
    {
      name: 'webkit',
      use: { 
        ...devices['Desktop Safari'],
        viewport: { width: 1280, height: 720 }
      },
    },
    
    /* Mobile viewports */
    {
      name: 'Mobile Chrome',
      use: { 
        ...devices['Pixel 5'],
      },
    },
    {
      name: 'Mobile Safari',
      use: { 
        ...devices['iPhone 12'],
      },
    },
    
    /* Tablet viewports */
    {
      name: 'Tablet Chrome',
      use: { 
        ...devices['Galaxy Tab S4'],
      },
    },
    {
      name: 'Tablet Safari',
      use: { 
        ...devices['iPad Mini'],
      },
    },
  ],

  /* Run local dev server before starting the tests */
  webServer: process.env.E2E_SKIP_WEBSERVER ? undefined : {
    command: `npm run dev -- --port ${e2ePort}`,
    url: e2eBaseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
});
