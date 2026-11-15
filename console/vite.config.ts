import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { localControlFromEnv } from "./scripts/local-control.mjs";
export default defineConfig(({ command }) => {
  const local = command === "serve" ? localControlFromEnv() : undefined;
  return {
    plugins: [vue(), ...(local ? [local] : [])],
    test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
  };
});
