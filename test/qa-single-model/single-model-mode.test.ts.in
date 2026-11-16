import { it, expect } from "vitest";
import { localControlFromEnv } from "../scripts/local-control.mjs";
const base = {
  MAAS_LOCAL_API: "http://127.0.0.1:18082",
  MAAS_LOCAL_SESSION: "s".repeat(64),
  MAAS_LOCAL_CSRF: "c".repeat(64),
  MAAS_LOCAL_EXPIRES: new Date(Date.now() + 60000).toISOString(),
};
for (const enabled of [undefined, "0", "1"])
  it("local inference opt-in " + enabled, () => {
    const plugin = localControlFromEnv({
      ...base,
      ...(enabled ? { MAAS_LOCAL_INFERENCE_ENABLED: enabled } : {}),
    }) as any;
    const config = plugin.config();
    expect(config.define["import.meta.env.VITE_LOCAL_INFERENCE_ENABLED"]).toBe(
      JSON.stringify(enabled === "1" ? "true" : "false"),
    );
    expect(config.server.proxy["/v1"].target).toBe(base.MAAS_LOCAL_API);
  });
it("invalid local inference flag is rejected", () => {
  expect(() =>
    localControlFromEnv({ ...base, MAAS_LOCAL_INFERENCE_ENABLED: "true" }),
  ).toThrow();
});
