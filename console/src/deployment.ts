import { checked } from "./chat/ar1-contracts";
import type { HTTPChatConfig } from "./chat/http";
export type Deployment = {
  schema_version: "maas.console/1";
  playground?: { enabled: boolean };
  chat: { enabled: false } | ({ enabled: true } & HTTPChatConfig);
};
let installed: Deployment | undefined;
const failure = () =>
  Error("控制台部署配置不可用，请检查同源 /console-config.json。");
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw failure();
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: string[]) {
  if (
    Object.keys(value).length !== expected.length ||
    expected.some((key) => !Object.hasOwn(value, key))
  )
    throw failure();
}
export function parseDeployment(value: unknown): Deployment {
  const root = object(value);
  keys(
    root,
    Object.hasOwn(root, "playground")
      ? ["schema_version", "chat", "playground"]
      : ["schema_version", "chat"],
  );
  if (Object.hasOwn(root, "playground")) {
    const feature = object(root.playground);
    keys(feature, ["enabled"]);
    if (typeof feature.enabled !== "boolean") throw failure();
  }
  if (root.schema_version !== "maas.console/1") throw failure();
  const chat = object(root.chat);
  if (chat.enabled === false) keys(chat, ["enabled"]);
  else if (chat.enabled === true) {
    keys(chat, ["enabled", "limits", "tools"]);
    checked("RunLimits", chat.limits);
    if (!Array.isArray(chat.tools) || chat.tools.length > 16) throw failure();
    const names = new Set<string>();
    for (const item of chat.tools) {
      const tool = object(item);
      keys(tool, ["name", "revision"]);
      if (
        typeof tool.name !== "string" ||
        !tool.name.trim() ||
        tool.name.length > 128 ||
        typeof tool.revision !== "string" ||
        !tool.revision.trim() ||
        tool.revision.length > 128 ||
        names.has(tool.name)
      )
        throw failure();
      names.add(tool.name);
    }
  } else throw failure();
  return structuredClone(value) as Deployment;
}
// Only public installation limits. API paths, credentials and persistence stay in Go.
export async function loadDeployment(
  fetcher: typeof fetch = fetch,
): Promise<Deployment> {
  installed = undefined;
  try {
    const response = await fetcher("/console-config.json", {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
    if (
      !response.ok ||
      !response.headers.get("Content-Type")?.includes("application/json")
    )
      throw failure();
    installed = parseDeployment(await response.json());
    return structuredClone(installed);
  } catch {
    throw failure();
  }
}
export function deployedChatConfig(): HTTPChatConfig {
  if (!installed?.chat.enabled) throw Error("当前安装尚未启用 Chat 服务。");
  const { limits, tools } = installed.chat;
  return structuredClone({ limits, tools });
}
