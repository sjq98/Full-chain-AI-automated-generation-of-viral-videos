"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const DESKTOP_DIR = path.resolve(__dirname, "..");
const PROJECT_ROOT = path.resolve(DESKTOP_DIR, "..");
const BACKEND_DIR = path.join(DESKTOP_DIR, "resources", "backend");
const MANIFEST_PATH = path.join(BACKEND_DIR, "backend-manifest.json");

function normalizedArch(value) {
  const arch = String(value || "").toLowerCase();
  if (["x64", "x86_64", "amd64"].includes(arch)) return "x64";
  if (["arm64", "aarch64"].includes(arch)) return "arm64";
  return arch;
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: DESKTOP_DIR, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}

function findPython() {
  const candidates = [process.env.PYTHON, process.env.PYTHON3, "python3"].filter(Boolean);
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (!probe.error && probe.status === 0) return candidate;
  }
  throw new Error("No usable Python 3 was found. Install Python 3 or set the PYTHON environment variable.");
}

function verifyBackend() {
  if (!fs.existsSync(MANIFEST_PATH)) {
    throw new Error("Backend manifest was not created. The macOS package cannot use a stale backend.");
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));
  const expectedArch = normalizedArch(process.arch);
  if (manifest.platform !== "darwin" || normalizedArch(manifest.machine) !== expectedArch) {
    throw new Error(
      `Backend was built for ${manifest.platform || "unknown"}/${manifest.machine || "unknown"}, ` +
      `but this package requires darwin/${expectedArch}. Rebuild it on the target Mac architecture.`
    );
  }
  if (manifest.backend !== "app" || !fs.existsSync(path.join(BACKEND_DIR, "app"))) {
    throw new Error("The native macOS backend executable is missing.");
  }
  if (manifest.sources?.["app.py"] !== sha256File(path.join(PROJECT_ROOT, "app.py"))) {
    throw new Error("Backend does not match the current app.py. Rebuild before creating the macOS package.");
  }
  if (manifest.capabilities?.volcengine_tos_sdk?.available !== true) {
    throw new Error("The backend was built without the Volcengine TOS SDK.");
  }
}

function main() {
  if (process.platform !== "darwin") {
    throw new Error("The macOS app must be packaged on macOS so the backend matches the target platform.");
  }
  const python = findPython();
  run(python, [path.join(PROJECT_ROOT, "build_release.py")]);
  verifyBackend();
  const electronBuilder = path.join(
    DESKTOP_DIR,
    "node_modules",
    ".bin",
    process.platform === "win32" ? "electron-builder.cmd" : "electron-builder"
  );
  if (!fs.existsSync(electronBuilder)) {
    throw new Error("electron-builder is not installed. Run npm install in the desktop directory first.");
  }
  run(electronBuilder, ["--mac", "dmg", "zip", "--publish", "never", `--${normalizedArch(process.arch)}`]);
}

main();
