const { app, BrowserWindow, dialog } = require("electron");
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

// ===================== 生命周期 =====================

app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (err) {
    dialog.showErrorBox("启动失败", `无法启动工具台后端服务：\n${err.message}`);
    app.quit();
    return;
  }
  createWindow();

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
