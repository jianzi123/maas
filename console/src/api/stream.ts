import { Api, ApiError } from "./client";
import { validate, type S } from "./contracts";
import { uuid } from "./recovery";
export type StreamHooks = {
  id: (id: string) => void;
  chunk: (text: string) => void;
  usage: (usage: S["Usage"]) => void;
};
export async function streamChat(
  client: Api,
  key: string,
  input: S["ChatRequest"],
  signal: AbortSignal,
  hooks: StreamHooks,
) {
  validate("ChatRequest", input);
  // Consumption key and cookie session are separate. Never send admin CSRF or cookies to inference.
  const consumer = new Api((url, init) =>
    client.fetcher(url, { ...init, credentials: "omit" }),
  );
  let res: Response;
  try {
    res = await consumer.response("/v1/chat/completions", {
      method: "POST",
      signal,
      headers: { Authorization: `Bearer ${key}` },
      body: JSON.stringify({ ...input, stream: true }),
    });
  } catch (e) {
    if (e instanceof ApiError && e.requestId) hooks.id(e.requestId);
    throw e;
  }
  const id = res.headers.get("X-Request-ID");
  if (!id || !uuid.test(id)) throw new ApiError("protocol_error", 200);
  hooks.id(id);
  if (
    !res.headers
      .get("Content-Type")
      ?.toLowerCase()
      .startsWith("text/event-stream") ||
    !res.body
  )
    throw new ApiError("protocol_error", 200);
  const reader = res.body.getReader(),
    decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "",
    event = "",
    data: string[] = [],
    done = false,
    finished = false;
  let created: number | undefined;
  function dispatch() {
    if (!data.length) {
      event = "";
      return;
    }
    if (done) throw new ApiError("protocol_error", 200);
    const payload = data.join("\n");
    data = [];
    if (event === "error") {
      event = "";
      const e = validate<S["Error"]>("Error", JSON.parse(payload));
      if (e.error.request_id !== id) throw new ApiError("protocol_error", 200);
      throw new ApiError(e.error.code, 200);
    }
    event = "";
    if (payload === "[DONE]") {
      if (!finished) throw new ApiError("protocol_error", 200);
      done = true;
      return;
    }
    const chunk = validate<S["ChatChunk"]>("ChatChunk", JSON.parse(payload));
    if (chunk.id !== "chatcmpl-" + id || chunk.model !== input.model)
      throw new ApiError("protocol_error", 200);
    if (created !== undefined && chunk.created !== created)
      throw new ApiError("protocol_error", 200);
    created = chunk.created;
    for (const choice of chunk.choices) {
      if (choice.delta.content) hooks.chunk(choice.delta.content);
      if (choice.finish_reason) finished = true;
    }
    if (chunk.usage) hooks.usage(chunk.usage);
  }
  function drain(final = false) {
    // Line parsing preserves CRLF split across network chunks and UTF-8 splits.
    while (true) {
      const index = buffer.search(/[\r\n]/);
      if (index < 0) break;
      if (buffer[index] === "\r" && index === buffer.length - 1 && !final)
        break;
      const line = buffer.slice(0, index);
      const n = buffer[index] === "\r" && buffer[index + 1] === "\n" ? 2 : 1;
      buffer = buffer.slice(index + n);
      if (!line) dispatch();
      else if (line.startsWith("data:"))
        data.push(line.slice(5).replace(/^ /, ""));
      else if (line.startsWith("event:")) event = line.slice(6).trim();
    }
    if (buffer.length > 262144 || data.join("").length > 262144)
      throw new ApiError("protocol_error", 200);
  }
  try {
    while (!done) {
      const part = await reader.read();
      if (part.done) {
        buffer += decoder.decode();
        drain(true);
        break;
      }
      buffer += decoder.decode(part.value, { stream: true });
      drain();
    }
    if (!done) throw new Error("响应流已中断，终态和用量待回查。");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
