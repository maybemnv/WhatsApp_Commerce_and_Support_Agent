import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const reportDirectory = process.env.PLAYWRIGHT_OUTPUT_DIR ?? "test-results";

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  workers: 1,
  fullyParallel: false,
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(reportDirectory, "results.json") }],
    ["junit", { outputFile: path.join(reportDirectory, "results.xml") }],
  ],
  use: {
    baseURL: "http://127.0.0.1:8105",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8105",
    cwd: "..",
    env: { ...process.env, APP_ENV: "local-fixture" },
    url: "http://127.0.0.1:8105/ready",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
