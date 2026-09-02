import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: process.env.NOEMOSYNE_WEB_URL ?? "http://localhost:3001",
    trace: "retain-on-failure",
  },
});
