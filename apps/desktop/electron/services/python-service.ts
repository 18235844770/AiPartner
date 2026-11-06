import { ChildProcess, spawn } from "child_process";
import fs from "fs";
import path from "path";

export type PythonServiceStatus = {
  state: "starting" | "running" | "failed";
  detail: string;
  apiBaseUrl: string;
};

export class PythonServiceManager {
  private child: ChildProcess | null = null;
  private state: PythonServiceStatus["state"] = "starting";
  private detail = "正在启动 Python 服务";

  constructor(private readonly port: number) {}

  status(): PythonServiceStatus {
    return {
      state: this.state,
      detail: this.detail,
      apiBaseUrl: `http://127.0.0.1:${this.port}`,
    };
  }

  start(): void {
    const serverRoot = path.resolve(__dirname, "../../../server");
    if (!fs.existsSync(path.join(serverRoot, "pyproject.toml"))) {
      this.state = "failed";
      this.detail = `找不到 Python 服务目录 ${serverRoot}`;
      return;
    }
    this.child = spawn(
      resolveUv(),
      ["run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(this.port)],
      {
        cwd: serverRoot,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        windowsHide: true,
      },
    );
    this.child.stdout?.on("data", (chunk: Buffer) => {
      console.log(chunk.toString());
    });
    this.child.stderr?.on("data", (chunk: Buffer) => {
      console.error(chunk.toString());
    });
    this.child.on("error", (error) => {
      this.state = "failed";
      this.detail = error.message;
    });
    this.child.on("exit", (code) => {
      if (this.state === "running") {
        this.state = "failed";
        this.detail = `Python 服务已退出，代码 ${code ?? "unknown"}`;
      }
    });
    void this.waitUntilHealthy();
  }

  async waitUntilHealthy(): Promise<void> {
    const url = `${this.status().apiBaseUrl}/health`;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try {
        const response = await fetch(url);
        if (response.ok) {
          this.state = "running";
          this.detail = "Python 服务已就绪";
          return;
        }
        this.detail = `健康检查返回 ${response.status}`;
      } catch (error) {
        this.detail = error instanceof Error ? error.message : "等待 Python 服务";
      }
      await delay(500);
    }
    this.state = "failed";
    this.detail = "Python 服务在超时时间内没有就绪";
  }

  stop(): void {
    const pid = this.child?.pid;
    if (!pid) {
      return;
    }
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(pid), "/t", "/f"], { windowsHide: true });
      return;
    }
    this.child?.kill();
  }
}

function resolveUv(): string {
  if (process.env.COMPANION_UV_BIN) {
    return process.env.COMPANION_UV_BIN;
  }
  const localUv = path.join(process.env.USERPROFILE ?? "", ".local", "bin", "uv.exe");
  if (fs.existsSync(localUv)) {
    return localUv;
  }
  return "uv";
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
