export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type ErrorBody = {
  code: string;
  message: string;
};

function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return typeof record.code === "string" && typeof record.message === "string";
}

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body === undefined ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError("无法连接本地服务", 0, "network_error");
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    if (isErrorBody(body)) {
      throw new ApiError(body.message, response.status, body.code);
    }
    throw new ApiError(`请求失败：${response.status}`, response.status, "http_error");
  }

  return (await response.json()) as T;
}

export function errorText(caught: unknown): string {
  if (caught instanceof ApiError) {
    return caught.message;
  }
  if (caught instanceof Error && caught.message) {
    return caught.message;
  }
  return "请求失败";
}
