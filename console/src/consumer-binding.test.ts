import { describe, it, expect, vi } from "vitest";
import { Api } from "./api/client";
import { streamChat } from "./api/stream";
import { fixtureError, rid, lookupSample } from "./fixtures";
const other = "00000000-0000-4000-8000-000000000022";
const input = {
  model: "model-a",
  messages: [{ role: "user" as const, content: "test" }],
  stream: true,
};
function event(
  created: number,
  content: string,
  finish = false,
  usage = false,
) {
  return (
    "data: " +
    JSON.stringify({
      id: "chatcmpl-" + rid,
      object: "chat.completion.chunk",
      created,
      model: "model-a",
      choices: usage
        ? []
        : [
            {
              index: 0,
              delta: { content },
              finish_reason: finish ? "stop" : null,
            },
          ],
      ...(usage ? { usage: lookupSample.data[0]!.usage } : {}),
    }) +
    "\r\n\r\n"
  );
}
const hooks = () => ({ id: vi.fn(), chunk: vi.fn(), usage: vi.fn() });
function response(body: string) {
  const bytes = new TextEncoder().encode(body);
  let i = 0;
  return new Response(
    new ReadableStream({
      pull(c) {
        if (i === bytes.length) c.close();
        else c.enqueue(bytes.slice(i, ++i));
      },
    }),
    { headers: { "Content-Type": "text/event-stream", "X-Request-ID": rid } },
  );
}
describe("stream created binding", () => {
  it.each([0, 1, 1790000000])(
    "accepts fixed created=%i across split content, finish and usage events",
    async (created) => {
      const h = hooks();
      await streamChat(
        new Api(async () =>
          response(
            event(created, "首片") +
              event(created, "尾片", true) +
              event(created, "", false, true) +
              "data: [DONE]\n\n",
          ),
        ),
        "fixture",
        input,
        new AbortController().signal,
        h,
      );
      expect(h.chunk.mock.calls).toEqual([["首片"], ["尾片"]]);
      expect(h.usage).toHaveBeenCalledTimes(1);
    },
  );
  it.each(["content", "finish", "usage"])(
    "rejects changed created in %s before publishing that event",
    async (kind) => {
      const h = hooks();
      const f = vi.fn<typeof fetch>(async () =>
        response(
          event(0, "first") +
            event(1, "wrong", kind === "finish", kind === "usage") +
            "data: [DONE]\n\n",
        ),
      );
      await expect(
        streamChat(
          new Api(f),
          "fixture",
          input,
          new AbortController().signal,
          h,
        ),
      ).rejects.toMatchObject({ code: "protocol_error" });
      expect(h.chunk.mock.calls).toEqual([["first"]]);
      expect(h.usage).not.toHaveBeenCalled();
      expect(f).toHaveBeenCalledTimes(1);
    },
  );
  it("new generation may have a different created timestamp", async () => {
    const client = new Api(
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          response(event(1, "A", true) + "data: [DONE]\n\n"),
        )
        .mockResolvedValueOnce(
          response(event(2, "B", true) + "data: [DONE]\n\n"),
        ),
    );
    await streamChat(
      client,
      "fixture",
      input,
      new AbortController().signal,
      hooks(),
    );
    await streamChat(
      client,
      "fixture",
      input,
      new AbortController().signal,
      hooks(),
    );
  });
});
describe("HTTP error association", () => {
  it("matching IDs preserve normalized budget rejection and original request", async () => {
    const body = await fixtureError("token_budget_exceeded", 429).json();
    body.error.reset_at = "2026-11-14T00:00:00Z";
    body.error.retry_after_seconds = 7;
    await expect(
      new Api(async () =>
        Response.json(body, { status: 429, headers: { "X-Request-ID": rid } }),
      ).response("/v1/chat/completions", { method: "POST" }),
    ).rejects.toMatchObject({
      code: "token_budget_exceeded",
      requestId: rid,
      resetAt: body.error.reset_at,
      retryAfter: 7,
    });
  });
  it.each([429, 503])(
    "mismatched error ID on HTTP %i cannot supply business hints",
    async (status) => {
      const body = await fixtureError("token_budget_exceeded", status).json();
      body.error.request_id = other;
      body.error.reset_at = "2026-11-14T00:00:00Z";
      body.error.retry_after_seconds = 7;
      const h = hooks(),
        f = vi.fn<typeof fetch>(async () =>
          Response.json(body, { status, headers: { "X-Request-ID": rid } }),
        );
      await expect(
        streamChat(
          new Api(f),
          "fixture",
          input,
          new AbortController().signal,
          h,
        ),
      ).rejects.toMatchObject({
        code: "protocol_error",
        requestId: rid,
        resetAt: null,
        retryAfter: null,
        uncertain: status >= 500,
      });
      expect(h.id).toHaveBeenCalledWith(rid);
      expect(h.chunk).not.toHaveBeenCalled();
      expect(f).toHaveBeenCalledTimes(1);
    },
  );
  it.each([null, "invalid"])(
    "no trusted header %s means no recoverable original ID",
    async (header) => {
      const body = await fixtureError("money_budget_exceeded", 429).json();
      const h = hooks();
      await expect(
        streamChat(
          new Api(async () =>
            Response.json(body, {
              status: 429,
              headers: header ? { "X-Request-ID": header } : {},
            }),
          ),
          "fixture",
          input,
          new AbortController().signal,
          h,
        ),
      ).rejects.toMatchObject({ code: "protocol_error", requestId: null });
      expect(h.id).not.toHaveBeenCalled();
    },
  );
  it("invalid JSON error does not expose raw content or infer rejection", async () => {
    const f = vi.fn<typeof fetch>(
      async () =>
        new Response("PRIVATE_UPSTREAM_BODY", {
          status: 503,
          headers: { "X-Request-ID": rid },
        }),
    );
    await expect(
      new Api(f).response("/v1/chat/completions", { method: "POST" }),
    ).rejects.toMatchObject({
      code: "protocol_error",
      requestId: rid,
      uncertain: true,
    });
    expect(f).toHaveBeenCalledTimes(1);
  });
});
