const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { autoUpdater } = require("electron-updater");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const fs = require("fs");
const net = require("net");

// ===================== 后端进程管理 =====================

let backendProc = null;
let backendPort = 0;
let isQuitting = false;

function isPackaged() {
  return app.isPackaged;
}

function findFreePort(startPort, attempts = 50) {
  return new Promise((resolve, reject) => {
    let port = startPort;
    const tryNext = () => {
      if (attempts-- <= 0) return reject(new Error("找不到可用端口"));
      const server = net.createServer();
      server.once("error", () => {
        port += 1;
        tryNext();
      });
      server.once("listening", () => {
        server.close(() => resolve(port));
      });
      server.listen(port, "127.0.0.1");
    };
    tryNext();
  });
}

function backendCommand() {
  if (isPackaged()) {
    const backendName = process.platform === "win32" ? "app.exe" : "app";
    const exe = path.join(process.resourcesPath, "backend", backendName);
    if (process.platform !== "win32") {
      try {
        fs.chmodSync(exe, 0o755);
      } catch (_) {
        /* best effort */
      }
    }
    return { cmd: exe, args: [] };
  }
  const projectRoot = path.resolve(__dirname, "..");
  return { cmd: "python", args: [path.join(projectRoot, "app.py")] };
}

function waitForBackend(port, timeoutMs = 60000) {
  const url = `http://127.0.0.1:${port}/`;
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const ping = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode) return resolve(port);
      });
      req.on("error", () => {
        if (Date.now() > deadline) return reject(new Error("后端启动超时"));
        setTimeout(ping, 500);
      });
      req.setTimeout(3000, () => req.destroy());
    };
    ping();
  });
}

async function startBackend() {
  backendPort = await findFreePort(8767);
  const { cmd, args } = backendCommand();
  const env = { ...process.env, HOST: "127.0.0.1", PORT: String(backendPort) };
  backendProc = spawn(cmd, args, {
    env,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  backendProc.stdout.on("data", (d) => console.log("[backend]", String(d).trim()));
  backendProc.stderr.on("data", (d) => console.error("[backend-err]", String(d).trim()));
  backendProc.on("exit", (code) => {
    console.log(`[backend] exited with code ${code}`);
    if (!isQuitting && code !== 0 && mainWindow && !mainWindow.isDestroyed()) {
      dialog.showErrorBox(
        "后端服务异常退出",
        `工具台后端进程已退出（代码 ${code}）。请重新打开软件。`
      );
    }
  });
  await waitForBackend(backendPort);
  return backendPort;
}

function stopBackend() {
  isQuitting = true;
  if (backendProc && !backendProc.killed) {
    try {
      backendProc.kill();
    } catch (_) {
      /* ignore */
    }
    backendProc = null;
  }
}

// ===================== 窗口 =====================

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    title: "MP4金句片段工作台",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.loadURL(`http://127.0.0.1:${backendPort}/`);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  // 让窗口标题跟随页面
  mainWindow.webContents.on("page-title-updated", (e, title) => {
    e.preventDefault();
    mainWindow.setTitle(title || "MP4金句片段工作台");
  });
}

// ===================== 自动更新 =====================

let updateState = {
  checking: false,
  available: null, // { version, releaseDate, releaseNotes }
  downloading: false,
  progress: 0, // 0-100
  downloaded: false,
  error: null,
};

function sendUpdateStatus() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("update-status", { ...updateState });
  }
}

function setupAutoUpdater() {
  autoUpdater.autoDownload = false; // 由前端发起下载
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on("checking-for-update", () => {
    updateState.checking = true;
    updateState.error = null;
    sendUpdateStatus();
  });
  autoUpdater.on("update-available", (info) => {
    updateState.checking = false;
    updateState.available = {
      version: info.version,
      releaseDate: info.releaseDate,
      releaseNotes: info.releaseNotes ? String(info.releaseNotes).slice(0, 2000) : "",
    };
    sendUpdateStatus();
  });
  autoUpdater.on("update-not-available", () => {
    updateState.checking = false;
    sendUpdateStatus();
  });
  autoUpdater.on("download-progress", (progress) => {
    updateState.downloading = true;
    updateState.progress = Math.round(progress.percent || 0);
    updateState.bytesPerSecond = progress.bytesPerSecond;
    updateState.transferred = progress.transferred;
    updateState.total = progress.total;
    sendUpdateStatus();
  });
  autoUpdater.on("update-downloaded", () => {
    updateState.downloading = false;
    updateState.downloaded = true;
    updateState.progress = 100;
    sendUpdateStatus();
  });
  autoUpdater.on("error", (err) => {
    updateState.checking = false;
    updateState.downloading = false;
    updateState.error = String(err && err.message ? err.message : err);
    sendUpdateStatus();
  });
}

function checkForUpdates(manual = true) {
  if (updateState.checking) return Promise.resolve({ ...updateState });
  try {
    if (manual) {
      updateState.error = null;
    }
    autoUpdater.checkForUpdates();
  } catch (err) {
    updateState.error = String(err && err.message ? err.message : err);
    sendUpdateStatus();
  }
  return Promise.resolve({ ...updateState });
}

async function downloadUpdate() {
  try {
    await autoUpdater.downloadUpdate();
  } catch (err) {
    updateState.error = String(err && err.message ? err.message : err);
    sendUpdateStatus();
  }
}

async function installUpdate() {
  try {
    autoUpdater.quitAndInstall(false, true);
  } catch (err) {
    updateState.error = String(err && err.message ? err.message : err);
    sendUpdateStatus();
  }
}

// ===================== IPC =====================

ipcMain.handle("app:version", () => app.getVersion());
ipcMain.handle("app:platform", () => process.platform);
ipcMain.handle("app:update-check", (_e, manual = true) => checkForUpdates(manual));
ipcMain.handle("app:update-download", () => downloadUpdate());
ipcMain.handle("app:update-install", () => installUpdate());
ipcMain.handle("app:update-state", () => ({ ...updateState }));

// ===================== 生命周期 =====================

app.whenReady().then(async () => {
  setupAutoUpdater();
  try {
    await startBackend();
  } catch (err) {
    dialog.showErrorBox("启动失败", `无法启动工具台后端服务：\n${err.message}`);
    app.quit();
    return;
  }
  createWindow();

  // 打开软件后延迟数秒自动检查更新（生产环境才检查）
  if (isPackaged()) {
    setTimeout(() => {
      try {
        autoUpdater.checkForUpdates();
      } catch (_) {
        /* ignore */
      }
    }, 8000);
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  stopBackend();
  app.quit();
});

app.on("before-quit", () => {
  stopBackend();
});
