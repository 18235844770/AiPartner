import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";

import { PythonServiceManager } from "./services/python-service";

const pythonService = new PythonServiceManager(8000);
let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#f4f0e8",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  const devServerUrl = process.env.VITE_DEV_SERVER_URL ?? "http://127.0.0.1:5173";
  if (app.isPackaged) {
    void mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
    return;
  }
  void mainWindow.loadURL(devServerUrl);
}

app.whenReady().then(() => {
  ipcMain.handle("get-service-status", () => pythonService.status());
  pythonService.start();
  createWindow();
});

app.on("before-quit", () => {
  pythonService.stop();
});

app.on("window-all-closed", () => {
  pythonService.stop();
  if (process.platform !== "darwin") {
    app.quit();
  }
});
