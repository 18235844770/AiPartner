import { ApiError, errorFromResponse } from "./http";

export interface Credentials {
  username: string;
  password: string;
}

export interface AccountProfile {
  id: string;
  username: string;
  display_name: string;
  timezone: string;
  created_at: string;
}

export interface ManagedCompanion {
  id: string;
  name: string;
  description: string | null;
  initialization_status: "pending" | "ready" | "failed";
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") headers.set("X-Companion-Request", "1");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  try {
    return await fetch(`/api${path}`, { ...init, headers, cache: "no-store", credentials: "same-origin" });
  } catch (caught) {
    if (init.signal?.aborted) throw caught;
    throw new ApiError("无法连接账号服务，请稍后重试", 0, "network_error");
  }
}

async function checked(response: Response): Promise<Response> {
  if (!response.ok) throw await errorFromResponse(response);
  return response;
}

export async function authAction(path: string, signal: AbortSignal, body?: object): Promise<void> {
  await checked(await request(`/auth/${path}`, {
    method: "POST", signal, body: body ? JSON.stringify(body) : undefined,
  }));
}

let renewal: Promise<AccountProfile> | undefined;

export function restoreAccount(signal: AbortSignal): Promise<AccountProfile> {
  if (renewal) return renewal;
  const restore = async (): Promise<AccountProfile> => {
    let response = await request("/user/me", { signal });
    if (response.status === 401) {
      await authAction("refresh", signal);
      response = await request("/user/me", { signal });
    }
    return (await checked(response)).json();
  };
  const task = navigator.locks
    ? navigator.locks.request("companion-session-restore", { signal }, restore).then((profile) => profile)
    : restore();
  renewal = task;
  const clear = () => { if (renewal === task) renewal = undefined; };
  task.then(clear, clear);
  return task;
}

let session: { userId: string; signal: AbortSignal; expire: () => void } | undefined;

export function bindAccount(userId: string, signal: AbortSignal, expire: () => void): void {
  session = { userId, signal, expire };
}

export async function accountFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const bound = session;
  if (!bound || bound.signal.aborted) throw new ApiError("请先登录", 401, "unauthorized");
  const headers = new Headers(init.headers);
  headers.set("X-Companion-Account", bound.userId);
  const signal = init.signal ? AbortSignal.any([init.signal, bound.signal]) : bound.signal;
  const call = () => request(path, { ...init, headers, signal });
  let response = await call();
  if (response.status === 401) {
    const failure = await errorFromResponse(response.clone());
    if (failure.code === "credentials_rejected") throw failure;
    try {
      const current = await restoreAccount(bound.signal);
      if (current.id !== bound.userId) throw new ApiError("当前账号已切换", 401, "account_changed");
      response = await call();
      if (response.status === 401) throw await errorFromResponse(response);
    } catch (caught) {
      if (!bound.signal.aborted && caught instanceof ApiError && caught.status === 401 && caught.code !== "credentials_rejected") {
        bound.expire();
      }
      throw caught;
    }
  }
  return checked(response);
}

export async function accountJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await accountFetch(path, init);
  return response.json() as Promise<T>;
}
