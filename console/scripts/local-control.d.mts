import type { Plugin } from "vite";
export function localControlFromEnv(
  env?: Record<string, string | undefined>,
): Plugin | undefined;
