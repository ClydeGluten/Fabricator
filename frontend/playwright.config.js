import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: '../.artifacts/browser',
  use: {
    baseURL: 'http://127.0.0.1:5057',
    viewport: { width: 1440, height: 1080 },
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {},
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `${process.env.FABRICATOR_TEST_PYTHON || '../.venv/bin/python'} ../tests/browser_fixture.py`,
    url: 'http://127.0.0.1:5057',
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
    stderr: 'ignore',
  },
})
