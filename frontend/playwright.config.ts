import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests',
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173', launchOptions: process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : {} },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
})
