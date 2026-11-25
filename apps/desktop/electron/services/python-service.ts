import { ChildProcess, spawn } from "child_process";
import fs from "fs";
import path from "path";

export type PythonServiceStatus = {
  state: "starting" | "running" | "failed";
  detail: string;
  apiBaseUrl: string;
};

export class PythonServiceManager {
  private api: ChildProcess | null = null;
  private worker: ChildProcess | null = null;
  private stopping = false;
  private state: PythonServiceStatus["state"] = "starting";
  private detail = "正在启动 Python 服务";
  private workerDetail = "";
  private serverRoot = "";

  constructor(private readonly port: number) {}

  status(): PythonServiceStatus {
    const detail = this.workerDetail ? `${this.detail}；${this.workerDetail}` : this.detail;
    return {
      state: this.state,
      detail,
      apiBaseUrl: `http://127.0.0.1:${this.port}`,
    };
  }

  start(): void {
    this.stopping = false;
    this.serverRoot = path.resolve(__dirname, "../../../server");
    if (!fs.existsSync(path.join(this.serverRoot, "pyproject.toml"))) {
      this.state = "failed";
      this.detail = `找不到 Python 服务目录 ${this.serverRoot}`;
      return;
    }
    this.api = this.spawnProcess(
      ["run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(this.port)],
      {
        onError: (error) => {
          this.state = "failed";
          this.detail = error.message;
        },
        onExit: (code) => {
          if (this.stopping || this.state !== "running") {
            return;
          }
          this.state = "failed";
          this.detail = `Python 服务已退出，代码 ${code ?? "unknown"}`;
        },
      },
    );
    this.startWorker();
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
    this.stopping = true;
    this.kill(this.worker);
    this.kill(this.api);
    this.worker = null;
    this.api = null;
  }

  private startWorker(): void {
    if (this.stopping || !this.serverRoot) {
      return;
    }
    this.workerDetail = "正在启动主动联系调度";
    this.worker = this.spawnProcess(["run", "arq", "app.modules.infrastructure.worker.WorkerSettings"], {
      onError: (error) => {
        this.workerDetail = error.message;
      },
      onExit: (code) => {
        this.worker = null;
        if (this.stopping) {
          return;
        }
        this.workerDetail = `主动联系调度已退出（${code ?? "unknown"}），稍后重试`;
        setTimeout(() => this.startWorker(), 5000);
      },
    });
    this.workerDetail = "主动联系调度已启动";
  }

  private spawnProcess(
    args: string[],
    hooks: { onError: (error: Error) => void; onExit: (code: number | null) => void },
  ): ChildProcess {
    const child = spawn(resolveUv(), args, {
      cwd: this.serverRoot,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      windowsHide: true,
    });
    child.stdout?.on("data", (chunk: Buffer) => {
      console.log(chunk.toString());
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      console.error(chunk.toString());
    });
    child.on("error", hooks.onError);
    child.on("exit", hooks.onExit);
    return child;
  }

  private kill(child: ChildProcess | null): void {
    const pid = child?.pid;
    if (!pid) {
      return;
    }
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(pid), "/t", "/f"], { windowsHide: true });
      return;
    }
    child.kill();
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
