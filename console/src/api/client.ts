import { validate, type S } from "./contracts";
export const ADMIN = "/api/admin/v1";
export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
    public uncertain = false,
    public resetAt: string | null = null,
    public retryAfter: number | null = null,
    public requestId: string | null = null,
  ) {
    super(errorText(code));
  }
}
const messages: Record<string, string> = {
  unauthenticated: "管理会话已过期，请重新登录。",
  invalid_api_key: "消费 Key 无效。",
  key_revoked: "消费 Key 已撤销。",
  csrf_failed: "会话校验失败，请重新登录。",
  request_budget_exceeded: "请求次数预算不足。",
  token_budget_exceeded: "Token 预算不足。",
  money_budget_exceeded: "金额预算不足。",
  rate_limited: "请求过于频繁，请稍后手动重试。",
  concurrency_exceeded: "并发容量不足。",
  policy_changed: "预算策略已变化，请刷新后核对。",
  resource_version_conflict: "配置已被修改，请刷新并核对后重新提交。",
  release_not_callable: "当前发布尚不可调用。",
  budget_bound_unavailable: "模型尚缺可信 Token 上界。",
  pricing_unavailable: "价格依据不可用。",
  unknown_write: "写入结果未知，请核对原操作；不要直接重复提交。",
  dependency_unavailable: "服务依赖暂不可用。",
  protocol_error: "服务响应不符合当前契约。",
};
export function errorText(code: string) {
  return messages[code] ?? `请求未完成（${code}）。`;
}
export class Api {
  csrf = "";
  constructor(public fetcher: typeof fetch = (...args) => fetch(...args)) {}
  async response(path: string, init: RequestInit = {}) {
    if (!path.startsWith("/") || path.startsWith("//"))
      throw new Error("仅允许同源接口");
    const method = init.method ?? "GET";
    const write = !["GET", "HEAD"].includes(method);
    const headers = new Headers(init.headers);
    if (init.body) headers.set("Content-Type", "application/json");
    if (write && this.csrf) headers.set("X-CSRF-Token", this.csrf);
    let response: Response;
    try {
      response = await this.fetcher(path, {
        ...init,
        headers,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
    } catch (e) {
      if (init.signal?.aborted) throw e;
      throw new ApiError(
        write ? "unknown_write" : "dependency_unavailable",
        0,
        write,
      );
    }
    if (!response.ok) {
      let body: S["Error"] | undefined;
      try {
        body = validate<S["Error"]>("Error", await response.json());
      } catch {
        /* Never echo untrusted response bodies. */
      }
      if (
        path.startsWith(ADMIN) &&
        response.status === 401 &&
        typeof window !== "undefined"
      )
        window.dispatchEvent(new Event("maas-session-expired"));
      throw new ApiError(
        body?.error.code ?? "dependency_unavailable",
        response.status,
        write && response.status >= 500,
        body?.error.reset_at,
        body?.error.retry_after_seconds,
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          response.headers.get("X-Request-ID") ?? "",
        )
          ? response.headers.get("X-Request-ID")
          : null,
      );
    }
    return response;
  }
  async json<T>(
    path: string,
    schema: string,
    init: RequestInit = {},
    version: "stable" | "draft" = "stable",
  ): Promise<T> {
    const res = await this.response(path, init);
    try {
      return validate<T>(schema, await res.json(), version);
    } catch {
      throw new ApiError(
        "protocol_error",
        res.status,
        !!init.method && !["GET", "HEAD"].includes(init.method),
      );
    }
  }
  async login(input: S["Login"]) {
    const s = await this.json<S["Session"]>(`${ADMIN}/session`, "Session", {
      method: "POST",
      body: JSON.stringify(input),
    });
    this.csrf = s.csrf_token;
    return s;
  }
  async session() {
    const s = await this.json<S["Session"]>(`${ADMIN}/session`, "Session");
    this.csrf = s.csrf_token;
    return s;
  }
  async logout() {
    await this.response(`${ADMIN}/session`, { method: "DELETE" });
    this.csrf = "";
  }
}
export const api = new Api();
