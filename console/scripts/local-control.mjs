// Development-only bridge to the existing loopback Go management API.
export function localControlFromEnv(env = process.env) {
  if (!env.MAAS_LOCAL_API) return undefined;
  const target = new URL(env.MAAS_LOCAL_API);
  if (
    target.protocol !== "http:" ||
    !["127.0.0.1", "[::1]"].includes(target.hostname) ||
    target.username ||
    target.password ||
    target.pathname !== "/"
  )
    throw Error("The controlled API must be an explicit loopback HTTP origin.");
  const session = env.MAAS_LOCAL_SESSION,
    csrf = env.MAAS_LOCAL_CSRF;
  const expires = Date.parse(env.MAAS_LOCAL_EXPIRES || "");
  if (
    !session ||
    !csrf ||
    !/^[A-Za-z0-9-]{43,256}$/.test(session) ||
    !/^[A-Za-z0-9-]{43,256}$/.test(csrf) ||
    !Number.isFinite(expires) ||
    expires <= Date.now() ||
    expires > Date.now() + 30 * 60000
  )
    throw Error(
      "Explicit short-lived bootstrap session, CSRF and expiry are required.",
    );
  return {
    name: "maas-local-control",
    apply: "serve",
    config() {
      return {
        define: {
          "import.meta.env.VITE_LOCAL_CONTROL": JSON.stringify("true"),
          "import.meta.env.VITE_CONSOLE_FIXTURES": JSON.stringify("false"),
        },
        server: {
          host: "127.0.0.1",
          port: Number(env.MAAS_LOCAL_PORT || 4179),
          strictPort: true,
          proxy: {
            "/api": { target: target.origin, changeOrigin: false },
            "/v1": { target: target.origin, changeOrigin: false },
          },
        },
      };
    },
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url !== "/__maas/local-session") return next();
        const address = server.httpServer?.address();
        const origin =
          address && typeof address === "object"
            ? "http://127.0.0.1:" + address.port
            : "";
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Content-Type", "application/json");
        if (
          req.headers.host !== origin.slice(7) ||
          req.headers.origin !== origin ||
          !["POST", "DELETE"].includes(req.method)
        ) {
          res.statusCode = 403;
          res.end(JSON.stringify({ message: "Local origin required" }));
          return;
        }
        if (req.method === "DELETE") {
          res.setHeader(
            "Set-Cookie",
            "maas_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
          );
          res.statusCode = 204;
          res.end();
          return;
        }
        if (Date.now() >= expires) {
          res.statusCode = 401;
          res.end(JSON.stringify({ message: "Local session expired" }));
          return;
        }
        try {
          const reply = await fetch(new URL("/api/admin/v1/keys", target), {
            headers: { Cookie: "maas_session=" + session },
            signal: AbortSignal.timeout(5000),
            redirect: "error",
          });
          if (!reply.ok) {
            res.statusCode = 503;
            res.end(
              JSON.stringify({ message: "Go management session unavailable" }),
            );
            return;
          }
          await reply.body?.cancel();
          res.setHeader(
            "Set-Cookie",
            "maas_session=" +
              session +
              "; HttpOnly; SameSite=Strict; Path=/; Max-Age=" +
              Math.floor((expires - Date.now()) / 1000),
          );
          res.end(
            JSON.stringify({
              csrf_token: csrf,
              expires_at: new Date(expires).toISOString(),
            }),
          );
        } catch {
          res.statusCode = 503;
          res.end(JSON.stringify({ message: "Go management API unavailable" }));
        }
      });
    },
  };
}
