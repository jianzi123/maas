import { api } from "./client";
// The endpoint is installed only by the explicitly enabled local Vite bridge.
export async function enterLocalControl() {
  const response = await api.response("/__maas/local-session", {
    method: "POST",
    body: "{}",
  });
  const value: unknown = await response.json();
  if (
    !value ||
    typeof value !== "object" ||
    !("csrf_token" in value) ||
    typeof value.csrf_token !== "string" ||
    value.csrf_token.length < 43 ||
    !("expires_at" in value) ||
    typeof value.expires_at !== "string" ||
    !Number.isFinite(Date.parse(value.expires_at)) ||
    Date.parse(value.expires_at) <= Date.now()
  )
    throw Error("本地临时会话不可用。");
  api.csrf = value.csrf_token;
}
export async function leaveLocalControl() {
  await api.response("/__maas/local-session", { method: "DELETE" });
  api.csrf = "";
}
