import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.BR_PLAYWRIGHT_BASE_URL ?? 'http://localhost:4173';
const useExternalServer = process.env.BR_PLAYWRIGHT_EXTERNAL_SERVER === 'true';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  webServer: useExternalServer ? undefined : {
    command: 'VITE_PRIVY_APP_ID=playwright-test VITE_PRIVY_E2E_MOCK=true npm run dev -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
