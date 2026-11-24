import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { localControlFromEnv } from "./scripts/local-control.mjs";
import { ar1LocalFromEnv } from "./scripts/ar1-local.mjs";
export default defineConfig(({ command }) => {
  const local = command === "serve" ? localControlFromEnv() : undefined;
  const ar1 = command === "serve" ? ar1LocalFromEnv() : undefined;
  return {
    plugins: [vue(), ...(local ? [local] : []), ...(ar1 ? [ar1] : [])],
    test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
  };
});
