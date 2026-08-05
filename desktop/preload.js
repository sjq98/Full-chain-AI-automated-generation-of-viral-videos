const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("appBridge", {
  // 基本信息
  getVersion: () => ipcRenderer.invoke("app:version"),
  getPlatform: () => ipcRenderer.invoke("app:platform"),

  // 自动更新
  checkForUpdates: (manual = true) => ipcRenderer.invoke("app:update-check", manual),
  downloadUpdate: () => ipcRenderer.invoke("app:update-download"),
  installUpdate: () => ipcRenderer.invoke("app:update-install"),
  getUpdateState: () => ipcRenderer.invoke("app:update-state"),
  onUpdateStatus: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("update-status", listener);
    return () => ipcRenderer.removeListener("update-status", listener);
  },
});
