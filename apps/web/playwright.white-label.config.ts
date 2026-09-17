import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Disposable database/storage and separate ports/build output: never reset the
// user's development database or replace their current login/session.
const temporary = mkdtempSync(path.join(tmpdir(), "setu-white-label-qa-"));
const common = {
  APP_ENV: "development",
  APP_ORIGIN: "http://localhost:3001",
  BRAND_PROXY_KEY: "setu-development-proxy",
  PLATFORM_ADMIN_EMAILS: "white-label-qa@example.test",
};
const python =
  process.env.API_PYTHON ||
  (process.platform === "win32"
    ? ".venv\\Scripts\\python.exe"
    : ".venv/bin/python");
export default defineConfig({
  testDir: "./tests/white-label",
  workers: 1,
  timeout: 180_000,
  use: {
    baseURL: "http://localhost:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      name: "Isolated API",
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 8001`,
      cwd: path.resolve("../api"),
      url: "http://127.0.0.1:8001/health",
      reuseExistingServer: false,
      env: {
        ...common,
        DATABASE_URL: `sqlite:///${path.join(temporary, "qa.db").replaceAll("\\", "/")}`,
        BRAND_ASSET_DIR: path.join(temporary, "assets"),
      },
    },
    {
      name: "Isolated website",
      command: "npm run dev -- --port 3001",
      url: "http://localhost:3001/login",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        ...common,
        API_INTERNAL_URL: "http://127.0.0.1:8001",
        NEXT_BUILD_DIR: ".next-white-label-qa",
      },
    },
  ],
});
