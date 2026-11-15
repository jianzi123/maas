import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { Api, api, ADMIN } from "./api/client";
import { streamChat } from "./api/stream";
import { validate, type S } from "./api/contracts";
import Playground from "./pages/Playground.vue";
import Releases from "./pages/Releases.vue";
import {
  fixtureFetch,
  lookupSample,
  now,
  releaseSample,
  resetFixtures,
  rid,
} from "./fixtures";

// Review-only regressions. Synthetic HTTP responses; no vendor/Go/cluster calls.
const secondId = "00000000-0000-4000-8000-000000000091";
const opAId = "00000000-0000-4000-8000-000000000080";
const opBId = "00000000-0000-4000-8000-000000000081";
const mounted: ReturnType<typeof mount>[] = [];
const originalFetcher = api.fetcher;
afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount();
  api.fetcher = originalFetcher;
  vi.restoreAllMocks();
  resetFixtures();
});
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function sse(headerId: string, chunkId = headerId, usage?: unknown) {
  const chunk = {
    id: "chatcmpl-" + chunkId,
    object: "chat.completion.chunk",
    created: 1,
    model: "model-a",
    choices: [
      {
        index: 0,
        delta: { content: "review response" },
        finish_reason: "stop",
      },
    ],
    ...(usage ? { usage } : {}),
  };
  return new Response(
    "data: " + JSON.stringify(chunk) + "\n\ndata: [DONE]\n\n",
    {
      headers: {
        "Content-Type": "text/event-stream",
        "X-Request-ID": headerId,
      },
    },
  );
}
function op(
  id: string,
  action: S["ReleaseOperation"]["action"] = "Pause",
): S["ReleaseOperation"] {
  return {
    id,
    action,
    state: "Accepted",
    namespace: releaseSample.metadata.namespace,
    name: releaseSample.metadata.name,
    cr_uid: releaseSample.metadata.uid!,
    requested_generation: releaseSample.metadata.generation!,
    publication_id: null,
    created_at: now,
    updated_at: now,
    reason: null,
    message: "synthetic review operation",
  };
}
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;

describe("independent backend review: expected safety properties", () => {
  it("R1: late recovery for request A cannot populate request B evidence", async () => {
    const oldLookup = deferred<Response>();
    let posts = 0;
    api.fetcher = vi.fn(async (path, init) => {
      if (String(path) === "/v1/chat/completions")
        return ++posts === 1 ? fixtureFetch(path, init) : sse(secondId);
      if (String(path).includes("request_id=" + rid)) return oldLookup.promise;
      if (String(path).includes("request_id=" + secondId)) {
        const page = structuredClone(lookupSample);
        page.lookup.request_id = secondId;
        page.data.forEach((row) => {
          row.request_id = secondId;
          row.status = "succeeded";
        });
        return Response.json(page);
      }
      return fixtureFetch(path, init);
    });
    const w = mount(Playground);
    mounted.push(w);
    await flushPromises();
    await w.find("select").setValue("model-a");
    await w.find('input[type="password"]').setValue("synthetic-review-key");
    await w.find("textarea").setValue("test");
    await w.find("form").trigger("submit");
    await flushPromises();
    await button(w, "停止传输").trigger("click");
    await flushPromises();
    expect(button(w, "发送请求").attributes("disabled")).toBeUndefined();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(posts).toBe(2);
    expect(w.text()).toContain(secondId);
    oldLookup.resolve(Response.json(lookupSample));
    await flushPromises();
    expect(w.text()).not.toContain("请求终态：cancelled");
    expect((w.vm as any).$.setupState.lookup.lookup.request_id).toBe(secondId);
  });

  it("R2: late operation A lookup cannot overwrite newly accepted operation B", async () => {
    const pending = deferred<Response>();
    let puts = 0;
    api.fetcher = vi.fn(async (path, init) => {
      if (String(path).includes("/release-operations/")) return pending.promise;
      if (init?.method === "PUT") {
        puts++;
        const resource = structuredClone(releaseSample);
        resource.spec.lifecycle.desiredState =
          puts === 1 ? "Paused" : "Published";
        resource.metadata.generation = 2 + puts;
        resource.metadata.resourceVersion = String(420 + puts);
        return Response.json(
          {
            operation: {
              ...op(
                puts === 1 ? opAId : opBId,
                puts === 1 ? "Pause" : "Resume",
              ),
              requested_generation: 2 + puts,
            },
            resource,
          },
          { status: 202 },
        );
      }
      return fixtureFetch(path, init);
    });
    const w = mount(Releases);
    mounted.push(w);
    await flushPromises();
    await w.find(".release-card").trigger("click");
    await flushPromises();
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    await button(w, "恢复发布").trigger("click");
    await flushPromises();
    expect(w.text()).toContain(opBId);
    pending.resolve(
      Response.json({
        ...op(opAId),
        requested_generation: 3,
        state: "Succeeded",
      }),
    );
    await flushPromises();
    expect(w.text()).toContain(opBId);
  });

  it("R3: a valid ACK for another CR must be uncertain and must not replace selected CR", async () => {
    const resource = structuredClone(releaseSample);
    resource.metadata.name = "other-release";
    resource.metadata.uid = secondId;
    resource.spec.modelAlias = "other-model";
    const operation = { ...op(opBId), name: "other-release", cr_uid: secondId };
    const accepted = { operation, resource };
    validate("ReleaseAccepted", accepted);
    api.fetcher = async (path, init) =>
      init?.method === "PUT"
        ? Response.json(accepted, { status: 202 })
        : fixtureFetch(path, init);
    const w = mount(Releases);
    mounted.push(w);
    await flushPromises();
    await w.find(".release-card").trigger("click");
    await flushPromises();
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    expect(w.text()).toContain("写入结果未知");
  });

  it("I2: clarified public response contract rejects a chunk from another request", async () => {
    await expect(
      streamChat(
        new Api(async () => sse(rid, secondId)),
        "synthetic-review-key",
        {
          model: "model-a",
          messages: [{ role: "user", content: "test" }],
          stream: true,
        },
        new AbortController().signal,
        { id: vi.fn(), chunk: vi.fn(), usage: vi.fn() },
      ),
    ).rejects.toMatchObject({ code: "protocol_error" });
  });

  it("I1: raw provider usage requires Go normalization before public consumption", async () => {
    // Direct provider prompt_tokens/completion_tokens are not the public Usage contract.
    const upstreamUsage = {
      prompt_tokens: 12,
      completion_tokens: 7,
      total_tokens: 19,
    };
    await expect(
      streamChat(
        new Api(async () => sse(rid, rid, upstreamUsage)),
        "synthetic-review-key",
        {
          model: "model-a",
          messages: [{ role: "user", content: "test" }],
          stream: true,
        },
        new AbortController().signal,
        { id: vi.fn(), chunk: vi.fn(), usage: vi.fn() },
      ),
    ).rejects.toThrow("ChatChunk");
  });
});
