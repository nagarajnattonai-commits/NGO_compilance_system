// HTTP integration checks through Next's same-origin API rewrite.
// Uses an isolated temporary SQLite database, never the user's project database.
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import net from "node:net";

const webRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const apiRoot = resolve(webRoot, "../api");
const origin = "http://127.0.0.1:3100";
const processes = [];
const directory = await mkdtemp(join(tmpdir(), "setu-auth-smoke-"));
const database = join(directory, "auth-test.db").replaceAll("\\", "/");
const logs = [];

async function ensureFree(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", () => reject(new Error(`Port ${port} is in use; no existing server will be stopped.`)));
    server.listen(port, "127.0.0.1", () => server.close(resolve));
  });
}
function launch(command, args, cwd, env) {
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  processes.push(child);
  child.stdout.on("data", chunk => logs.push(chunk.toString()));
  child.stderr.on("data", chunk => logs.push(chunk.toString()));
  child.on("error", error => logs.push(error.message));
  return child;
}
async function ready(url) {
  for (let attempt = 0; attempt < 80; attempt++) {
    try { if ((await fetch(url)).ok) return; } catch { /* startup in progress */ }
    if (processes.some(child => child.exitCode !== null)) throw new Error("Test server stopped before becoming ready");
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Test server startup timed out");
}
let cookie = "";
async function request(path, body, method = body ? "POST" : "GET") {
  const response = await fetch(origin + path, { method, redirect: "manual",
    headers: { "Content-Type": "application/json", "X-Setu-Request": "1", Origin: origin, ...(cookie ? { Cookie: cookie } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const setCookie = response.headers.get("set-cookie");
  if (setCookie) cookie = setCookie.split(";")[0];
  return response;
}

try {
  await ensureFree(8000); await ensureFree(3100);
  const python = process.platform === "win32" ? join(apiRoot, ".venv/Scripts/python.exe") : join(apiRoot, ".venv/bin/python");
  launch(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], apiRoot,
    { DATABASE_URL: `sqlite:///${database}`, APP_ORIGIN: origin, APP_ENV: "development" });
  await ready("http://127.0.0.1:8000/health");
  launch(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "3100"], webRoot,
    { API_INTERNAL_URL: "http://127.0.0.1:8000", NODE_ENV: "production" });
  await ready(origin + "/login");
  for (const [route, title] of [["/login", "Welcome back"], ["/signup", "Create your account"], ["/admin/login", "Platform Administration"],
    ["/forgot-password", "Forgot your password?"], ["/reset-password", "Set a new password"], ["/accept-invitation", "Join your workspace"]]) {
    const page = await request(route);
    assert.equal(page.status, 200); assert.ok((await page.text()).includes(title), route);
  }
  const marketing = await request("/");
  assert.equal(marketing.status, 200);
  const marketingHtml = await marketing.text();
  assert.ok(marketingHtml.includes("Every obligation."));
  assert.ok(marketingHtml.includes("D&amp;D MANAGEMENT"));
  for (const route of ["/dashboard", "/admin", "/account"]) {
    const page = await request(route);
    assert.equal(page.status, 307); assert.equal(page.headers.get("location"), route === "/admin" ? "/admin/login" : "/login");
  }
  assert.equal((await request("/api/v1/organizations")).status, 401);
  const signedUp = await request("/api/v1/auth/signup", {
    name: "Smoke Test Owner", workspace_name: "Isolated Smoke Workspace", email: "smoke@example.test", password: "Isolated-smoke-passphrase-2026",
  });
  assert.equal(signedUp.status, 201);
  assert.ok(signedUp.headers.get("set-cookie").includes("HttpOnly"));
  const owner = await signedUp.json();
  assert.equal(owner.role, "ADMIN");
  assert.equal((await request("/api/v1/auth/me")).status, 200);
  assert.equal((await request("/api/v1/admin/users")).status, 200);
  for (const route of ["/", "/dashboard", "/account"]) assert.equal((await request(route)).status, 200, route);
  assert.equal((await request("/admin")).headers.get("location"), "/access-denied?admin=1");
  const account = await (await request("/account")).text();
  assert.ok(account.includes("Smoke Test Owner"));
  const admin = await (await request("/admin")).text();
  assert.ok(!admin.includes("Ananya Desai"), "Protected HTML must not contain the old demo identity");
  const result = await request("/api/v1/auth/logout", {});
  assert.equal(result.status, 204);
  assert.equal((await request("/api/v1/auth/me")).status, 401);
  assert.equal((await request("/admin")).status, 307);
  const login = await request("/api/v1/auth/login", { email: "smoke@example.test", password: "Isolated-smoke-passphrase-2026", remember: true });
  assert.equal(login.status, 200);
  assert.equal((await request("/api/v1/auth/me")).status, 200);
  console.log("PASS: public marketing and auth pages, protected route redirects, signup, cookie forwarding, dashboard/admin access, account rendering, logout and sign-in through Next.");
} catch (error) {
  console.error(error.message);
  // Logs contain only requests without body/cookie dumps; tokens use URL fragments.
  console.error(logs.slice(-10).join(""));
  process.exitCode = 1;
} finally {
  for (const child of processes.reverse()) {
    if (child.exitCode !== null || !child.pid) continue;
    try {
      if (process.platform === "win32") execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "pipe" });
      else child.kill("SIGTERM");
    } catch { console.error(`Could not stop test process ${child.pid}; please stop it manually.`); process.exitCode = 1; }
  }
  // Only the freshly created, known temporary test directory is removed.
  if (resolve(directory).startsWith(resolve(tmpdir()) + (process.platform === "win32" ? "\\" : "/")) && directory.includes("setu-auth-smoke-")) {
    await rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }).catch(() => console.error("Temporary test database is still in use; retained for cleanup."));
  }
}
