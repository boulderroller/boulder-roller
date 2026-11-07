import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testMatch: 'portal-v2-routes.spec.ts',
  grep: /ClimbView Phase C capture/,
  projects: [{ name: 'webkit-climb', use: { ...devices['Desktop Safari'] } }],
});
