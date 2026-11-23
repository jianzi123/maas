import { afterEach, it, expect, vi } from "vitest";
import {
  parseDeployment,
  loadDeployment,
  deployedChatConfig,
} from "./deployment";
import example from "../examples/console-config.controlled.json";
afterEach(() => vi.restoreAllMocks());
it("loads only same-origin public limits and isolates later mutation", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify(example), {
        headers: { "Content-Type": "application/json" },
      }),
  );
  const config = await loadDeployment(fetcher as typeof fetch);
  expect(fetcher).toHaveBeenCalledWith("/console-config.json", {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  expect(deployedChatConfig().tools).toHaveLength(2);
  if (config.chat.enabled) config.chat.limits.max_steps = 99;
  expect(deployedChatConfig().limits.max_steps).toBe(4);
});
for (const field of [
  "api_url",
  "csrf_token",
  "platform_key",
  "database_path",
]) {
  it(
    "rejects deployment field " +
      field +
      " rather than selecting another service or credentials",
    () => {
      expect(() =>
        parseDeployment({ ...example, [field]: "invalid" }),
      ).toThrow();
    },
  );
}
it("requires explicit limits, unique tool names and the original strict RunLimits", () => {
  for (const chat of [
    { enabled: true, tools: [] },
    { ...example.chat, limits: { ...example.chat.limits, max_tokens: "-1" } },
    { ...example.chat, limits: { ...example.chat.limits, extra: true } },
    { ...example.chat, tools: [example.chat.tools[0], example.chat.tools[0]] },
    {
      ...example.chat,
      tools: [{ name: "x", revision: "1", secret: "invalid" }],
    },
  ])
    expect(() =>
      parseDeployment({ schema_version: "maas.console/1", chat }),
    ).toThrow();
});
it("disabled config leaves management usable and never falls back to a development Chat store", async () => {
  await loadDeployment(
    async () =>
      new Response(
        JSON.stringify({
          schema_version: "maas.console/1",
          chat: { enabled: false },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
  );
  expect(() => deployedChatConfig()).toThrow("尚未启用");
});
for (const response of [
  () =>
    new Response("<html>fallback</html>", {
      headers: { "Content-Type": "text/html" },
    }),
  () => new Response("missing", { status: 404 }),
  () =>
    new Response("invalid", {
      headers: { "Content-Type": "application/json" },
    }),
]) {
  it("failed reload discards prior installed config instead of keeping stale authorization settings", async () => {
    await loadDeployment(
      async () =>
        new Response(JSON.stringify(example), {
          headers: { "Content-Type": "application/json" },
        }),
    );
    await expect(loadDeployment(async () => response())).rejects.toThrow(
      "部署配置不可用",
    );
    expect(() => deployedChatConfig()).toThrow("尚未启用");
  });
}
