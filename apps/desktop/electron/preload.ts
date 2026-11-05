import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("companion", {
  getServiceStatus: (): Promise<{
    state: "starting" | "running" | "failed";
    detail: string;
    apiBaseUrl: string;
  }> => ipcRenderer.invoke("get-service-status"),
});
