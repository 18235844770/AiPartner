import { app, BrowserWindow, ipcMain, Menu, nativeImage, session, Tray } from "electron";
import path from "path";

import { PythonServiceManager } from "./services/python-service";

const pythonService = new PythonServiceManager(8000);
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let quitting = false;

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showMainWindow();
  });
  app.whenReady().then(() => {
    allowMediaPermissions();
    ipcMain.handle("get-service-status", () => pythonService.status());
    pythonService.start();
    createTray();
    createWindow();
  });
}

function allowMediaPermissions(): void {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission === "media");
  });
  session.defaultSession.setPermissionCheckHandler((_webContents, permission) => {
    return permission === "media" || permission === "mediaKeySystem";
  });
}

function showMainWindow(): void {
  if (!app.isReady()) {
    return;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

function createTray(): void {
  tray = new Tray(trayImage());
  tray.setToolTip("关掉窗口后仍会主动说话");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "打开", click: () => showMainWindow() },
      {
        label: "退出",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("double-click", () => {
    showMainWindow();
  });
}

function trayImage(): Electron.NativeImage {
  const size = 16;
  const buffer = Buffer.alloc(size * size * 4);
  const radius = 5;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const dx = x - 7.5;
      const dy = y - 7.5;
      if (dx * dx + dy * dy > radius * radius) {
        continue;
      }
      const offset = (y * size + x) * 4;
      buffer[offset] = 92;
      buffer[offset + 1] = 140;
      buffer[offset + 2] = 196;
      buffer[offset + 3] = 255;
    }
  }
  return nativeImage.createFromBitmap(buffer, { width: size, height: size });
}

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
  mainWindow.on("close", (event) => {
    if (quitting) {
      return;
    }
    event.preventDefault();
    mainWindow?.hide();
  });
  const devServerUrl = process.env.VITE_DEV_SERVER_URL ?? "http://127.0.0.1:5173";
  if (app.isPackaged) {
    void mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
    return;
  }
  void mainWindow.loadURL(devServerUrl);
}

app.on("activate", () => {
  showMainWindow();
});

app.on("before-quit", () => {
  quitting = true;
  pythonService.stop();
  tray?.destroy();
  tray = null;
});

app.on("window-all-closed", () => {
  // 窗口关掉之后接口和主动联系调度继续跑，不跟用户是否留在界面上绑定。
});
