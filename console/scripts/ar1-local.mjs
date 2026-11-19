// Explicit loopback development bridge. The cookie/CSRF belong to this Go service.
export function ar1LocalFromEnv(env = process.env) {
  if (!env.MAAS_LOCAL_AGENT_API) return undefined;
  if (env.MAAS_LOCAL_API)
    throw Error(
      "Choose one Go application session; two independent local cookie services cannot be combined.",
    );
  const target = new URL(env.MAAS_LOCAL_AGENT_API);
  if (
    target.protocol !== "http:" ||
    target.hostname !== "127.0.0.1" ||
    target.username ||
    target.password ||
    target.pathname !== "/" ||
    target.search ||
    target.hash
  )
    throw Error(
      "MAAS_LOCAL_AGENT_API requires an explicit loopback HTTP origin.",
    );
  // Test values for the fixed agentcontrolled entry, never production defaults.
  const config = {
    limits: {
      max_steps: 4,
      max_model_calls: 4,
      max_tool_calls: 8,
      max_duration_ms: 10000,
      tool_timeout_ms: 1000,
      max_tool_output_bytes: 8192,
      max_context_tokens: 32768,
      no_progress_limit: 3,
      max_tokens: "100",
      max_money_atomic: "100",
      currency: "TST",
    },
    tools: [
      { name: "bounded_arithmetic", revision: "1" },
      { name: "list_visible_models", revision: "1" },
    ],
  };
  const proxy = {
    target: target.origin,
    changeOrigin: true,
    configure(instance) {
      instance.on("proxyReq", (out, req) => {
        if (req.headers.origin) out.setHeader("Origin", target.origin);
      });
    },
  };
  return {
    name: "maas-ar1-local",
    apply: "serve",
    config() {
      return {
        define: {
          "import.meta.env.VITE_CHAT_AR1_ENABLED": JSON.stringify("true"),
          "import.meta.env.VITE_CHAT_AR1_CONTROLLED": JSON.stringify("true"),
          "import.meta.env.VITE_CHAT_AR1_CONFIG": JSON.stringify(
            JSON.stringify(config),
          ),
          "import.meta.env.VITE_CONSOLE_FIXTURES": JSON.stringify("false"),
        },
        server: {
          host: "127.0.0.1",
          proxy: { "/api/agent/v1": proxy, "/__maas/local-session": proxy },
        },
      };
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (
          !req.url?.startsWith("/api/agent/v1") &&
          !req.url?.startsWith("/__maas/local-session")
        )
          return next();
        const address = server.httpServer?.address();
        const origin =
          address && typeof address === "object"
            ? "http://127.0.0.1:" + address.port
            : "";
        const write = !["GET", "HEAD"].includes(req.method);
        if (
          req.headers.host !== origin.slice(7) ||
          (req.headers.origin && req.headers.origin !== origin) ||
          (write && req.headers.origin !== origin) ||
          req.headers["sec-fetch-site"] === "cross-site"
        ) {
          res.statusCode = 403;
          res.end("Local same-origin session required");
          return;
        }
        next();
      });
    },
  };
}
