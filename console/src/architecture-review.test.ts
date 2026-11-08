import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { api } from "./api/client";
import { validate } from "./api/contracts";
import Playground from "./pages/Playground.vue";
import Releases from "./pages/Releases.vue";
import { fixtureFetch, lookupSample, rid, resetFixtures } from "./fixtures";

afterEach(() => {
  vi.restoreAllMocks();
  resetFixtures();
});
const secondId = "00000000-0000-4000-8000-000000000005";
function button(w: any, name: string) {
  return w.findAll("button").find((b: any) => b.text() === name)!;
}
const state = (w: any) => w.vm.$.setupState;
async function openRelease() {
  const w = mount(Releases);
  await flushPromises();
  await w.find(".release-card").trigger("click");
  await flushPromises();
  return w;
}
function endResponse(id: string) {
  return new Response(
    "data: " +
      JSON.stringify({
        id: "chatcmpl-" + id,
        object: "chat.completion.chunk",
        created: 1,
        model: "model-a",
        choices: [
          { index: 0, delta: { content: "ok" }, finish_reason: "stop" },
        ],
      }) +
      "\n\ndata: [DONE]\n\n",
    {
      headers: { "Content-Type": "text/event-stream", "X-Request-ID": id },
    },
  );
}
it("R1: late lookup A must not become current request B evidence", async () => {
  let releaseOld!: (r: Response) => void;
  let posts = 0;
  api.fetcher = async (p, init) => {
    const url = String(p);
    if (url === "/v1/chat/completions")
      return endResponse(++posts === 1 ? rid : secondId);
    if (url.includes("request_id=" + rid))
      return new Promise((r) => {
        releaseOld = r;
      });
    return fixtureFetch(p, init);
  };
  const w = mount(Playground);
  try {
    await flushPromises();
    await w.find("select").setValue("model-a");
    await w.find("input[type=password]").setValue("synthetic-review-key");
    await w.find("textarea").setValue("synthetic prompt");
    await w.find("form").trigger("submit");
    await flushPromises();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(posts).toBe(2);
    expect(state(w).id).toBe(secondId);
    releaseOld(Response.json(lookupSample));
    await flushPromises();
    expect(state(w).lookup.lookup.request_id).toBe(secondId);
  } finally {
    w.unmount();
  }
});
it("R2: editing after acknowledged pause must use acknowledged paused spec", async () => {
  const submitted: any[] = [];
  api.fetcher = async (p, init) => {
    const response = await fixtureFetch(p, init);
    if (init?.method === "PUT") {
      submitted.push({
        body: JSON.parse(String(init.body)),
        version: new Headers(init.headers).get("If-Match"),
      });
      const accepted = await response.json();
      accepted.resource.spec.lifecycle.desiredState = "Paused";
      accepted.resource.metadata.resourceVersion = "421";
      validate("ReleaseAccepted", accepted);
      return Response.json(accepted, { status: 202 });
    }
    return response;
  };
  const w = await openRelease();
  try {
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    expect(button(w, "恢复发布").exists()).toBe(true);
    await button(w, "编辑配置").trigger("click");
    const input = JSON.parse(
      (w.find("textarea").element as HTMLTextAreaElement).value,
    );
    const staleEditorState = input.spec.lifecycle.desiredState;
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(submitted).toHaveLength(2);
    expect(submitted[1].version).toBe('"421"');
    console.info(
      "R2 observed",
      JSON.stringify({
        staleEditorState,
        sentState: submitted[1].body.spec.lifecycle.desiredState,
        ifMatch: submitted[1].version,
      }),
    );
    expect(submitted[1].body.spec.lifecycle.desiredState).toBe("Paused");
  } finally {
    w.unmount();
  }
});
it("R3: old operation lookup must not replace a new write operation", async () => {
  let releaseOld!: (r: Response) => void;
  let oldOp: any;
  let writes = 0;
  const newId = "00000000-0000-4000-8000-000000000081";
  api.fetcher = async (p, init) => {
    if (String(p).includes("/release-operations/"))
      return new Promise((r) => {
        releaseOld = r;
      });
    const response = await fixtureFetch(p, init);
    if (init?.method === "PUT") {
      const accepted = await response.json();
      if (++writes === 1) oldOp = structuredClone(accepted.operation);
      else accepted.operation.id = newId;
      return Response.json(accepted, { status: 202 });
    }
    return response;
  };
  const w = await openRelease();
  try {
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    await button(w, "恢复发布").trigger("click");
    await flushPromises();
    expect(state(w).operation.id).toBe(newId);
    releaseOld(Response.json(oldOp));
    await flushPromises();
    expect(state(w).operation.id).toBe(newId);
  } finally {
    w.unmount();
  }
});
it("R4: unrelated schema-valid release ACK must remain uncertain", async () => {
  api.fetcher = async (p, init) => {
    const response = await fixtureFetch(p, init);
    if (init?.method === "PUT") {
      const accepted = await response.json();
      accepted.operation.name = "unrelated-cr";
      accepted.operation.cr_uid = secondId;
      accepted.resource.metadata.name = "unrelated-cr";
      accepted.resource.metadata.uid = secondId;
      validate("ReleaseAccepted", accepted);
      return Response.json(accepted, { status: 202 });
    }
    return response;
  };
  const w = await openRelease();
  try {
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    expect(w.text()).not.toContain("配置已提交（202）");
  } finally {
    w.unmount();
  }
});
