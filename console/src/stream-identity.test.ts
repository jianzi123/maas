import { it, expect, vi } from "vitest";
import { Api } from "./api/client";
import { streamChat } from "./api/stream";
import { fixtureError, rid } from "./fixtures";
const request = {
  model: "model-a",
  messages: [{ role: "user" as const, content: "test" }],
  stream: true,
};
const hooks = () => ({ id: vi.fn(), chunk: vi.fn(), usage: vi.fn() });
it("rejects a valid chunk belonging to another original request before showing text", async () => {
  const body =
    "data: " +
    JSON.stringify({
      id: "chatcmpl-00000000-0000-4000-8000-000000000022",
      object: "chat.completion.chunk",
      created: 1,
      model: "model-a",
      choices: [
        {
          index: 0,
          delta: { content: "wrong request" },
          finish_reason: "stop",
        },
      ],
    }) +
    "\n\ndata: [DONE]\n\n";
  const h = hooks();
  await expect(
    streamChat(
      new Api(
        async () =>
          new Response(body, {
            headers: {
              "Content-Type": "text/event-stream",
              "X-Request-ID": rid,
            },
          }),
      ),
      "fixture",
      request,
      new AbortController().signal,
      h,
    ),
  ).rejects.toMatchObject({ code: "protocol_error" });
  expect(h.chunk).not.toHaveBeenCalled();
});
it("rejects an error envelope for another original request", async () => {
  const e = await fixtureError("accounting_unavailable").json();
  e.error.request_id = "00000000-0000-4000-8000-000000000022";
  await expect(
    streamChat(
      new Api(
        async () =>
          new Response("event: error\ndata: " + JSON.stringify(e) + "\n\n", {
            headers: {
              "Content-Type": "text/event-stream",
              "X-Request-ID": rid,
            },
          }),
      ),
      "fixture",
      request,
      new AbortController().signal,
      hooks(),
    ),
  ).rejects.toMatchObject({ code: "protocol_error" });
});
it("does not invent an original request when the trusted header is absent", async () => {
  const h = hooks();
  await expect(
    streamChat(
      new Api(
        async () =>
          new Response("data: [DONE]\n\n", {
            headers: { "Content-Type": "text/event-stream" },
          }),
      ),
      "fixture",
      request,
      new AbortController().signal,
      h,
    ),
  ).rejects.toMatchObject({ code: "protocol_error" });
  expect(h.id).not.toHaveBeenCalled();
});
