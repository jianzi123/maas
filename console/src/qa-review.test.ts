// Independent QA probes for PR #4 at 6d01604. Synthetic responses only.
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { api, ADMIN } from "./api/client";
import Keys from "./pages/Keys.vue";
import Playground from "./pages/Playground.vue";
import Releases from "./pages/Releases.vue";
import {
  fixtureFetch,
  fixtureError,
  keySample,
  lookupSample,
  releaseSample,
  resetFixtures,
  rid,
  now,
} from "./fixtures";

const otherId = "00000000-0000-4000-8000-000000000022";
const mounted: ReturnType<typeof mount>[] = [];
function open(component: any) {
  const w = mount(component);
  mounted.push(w);
  return w;
}
afterEach(() => {
  mounted.forEach((w) => w.unmount());
  mounted.length = 0;
  vi.restoreAllMocks();
  resetFixtures();
});
function finished(id: string) {
  const payload = {
    id: "chatcmpl-" + id,
    object: "chat.completion.chunk",
    created: 1,
    model: "model-a",
    choices: [
      { index: 0, delta: { content: "QA synthetic" }, finish_reason: "stop" },
    ],
  };
  return new Response(`data: ${JSON.stringify(payload)}\n\ndata: [DONE]\n\n`, {
    headers: { "Content-Type": "text/event-stream", "X-Request-ID": id },
  });
}

describe("independent QA race and error probes", () => {
  it("QA-R01: a late lookup must not attach request A accounting to request B", async () => {
    let releaseA!: (r: Response) => void;
    let posts = 0;
    const reads: string[] = [];
    api.fetcher = async (path, init) => {
      if (String(path) === "/v1/chat/completions")
        return finished(++posts === 1 ? rid : otherId);
      if (String(path).includes("request_id=")) {
        reads.push(String(path));
        if (String(path).endsWith(rid))
          return new Promise((r) => {
            releaseA = r;
          });
      }
      return fixtureFetch(path, init);
    };
    const w = open(Playground);
    await flushPromises();
    await w.find("form select").setValue("model-a");
    await w.find('input[type="password"]').setValue("qa_fixture_only_key");
    await w.find("textarea").setValue("first synthetic request");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(reads).toHaveLength(1);
    await w.find("textarea").setValue("second synthetic request");
    await w.find("form").trigger("submit");
    await flushPromises();
    releaseA(Response.json(lookupSample));
    await flushPromises();
    const state = (w.vm as any).$.setupState;
    console.log(
      "QA-R01 observed",
      JSON.stringify({
        currentId: state.id,
        lookupId: state.lookup?.lookup.request_id,
        posts,
        lookupReads: reads.length,
      }),
    );
    expect(state.id).toBe(otherId);
    expect(state.lookup?.lookup.request_id).not.toBe(rid);
  });

  it("QA-R02: late Key creation must not repopulate a destroyed page secret", async () => {
    let releaseCreate!: (r: Response) => void;
    let releaseRefresh!: (r: Response) => void;
    let reads = 0;
    api.fetcher = async (path, init) => {
      if (String(path) === ADMIN + "/keys" && init?.method === "POST")
        return new Promise((r) => {
          releaseCreate = r;
        });
      if (String(path) === ADMIN + "/keys" && ++reads > 1)
        return new Promise((r) => {
          releaseRefresh = r;
        });
      return fixtureFetch(path, init);
    };
    const w = open(Keys);
    await w.find('[data-testid="create-key"]').trigger("click");
    await flushPromises();
    await w.find("form input").setValue("QA synthetic key");
    await w.find("form select").setValue("utc_day");
    await w.find("form").trigger("submit");
    const internal = (w.vm as any).$.setupState;
    w.unmount();
    expect(internal.secret).toBe("");
    releaseCreate(
      Response.json(
        {
          key: keySample,
          secret: "qa_fixture_only_late_secret_0000000000000001",
        },
        { status: 201 },
      ),
    );
    await flushPromises();
    const observed = internal.secret;
    releaseRefresh?.(
      Response.json({
        data: [keySample],
        next_cursor: null,
        generated_at: now,
        data_complete: true,
      }),
    );
    await flushPromises();
    console.log(
      "QA-R02 observed",
      JSON.stringify({
        secretRepopulated: observed !== "",
        postUnmountRefresh: reads > 1,
      }),
    );
    expect(observed).toBe("");
    expect(reads).toBe(1);
  });

  it("QA-R03: late operation A query must not replace new accepted operation B", async () => {
    let releaseA!: (r: Response) => void;
    let writes = 0;
    const operation = (id: string) => ({
      id,
      action: "Pause",
      state: "Accepted",
      namespace: releaseSample.metadata.namespace,
      name: releaseSample.metadata.name,
      cr_uid: releaseSample.metadata.uid,
      requested_generation: 2,
      publication_id: null,
      created_at: now,
      updated_at: now,
      reason: null,
      message: "QA synthetic operation",
    });
    api.fetcher = async (path, init) => {
      if (String(path).includes("/release-operations/"))
        return new Promise((r) => {
          releaseA = r;
        });
      if (init?.method === "PUT") {
        writes++;
        const resource = structuredClone(releaseSample);
        resource.metadata.resourceVersion = String(420 + writes);
        resource.metadata.generation = 2 + writes;
        resource.spec.lifecycle.desiredState = JSON.parse(
          String(init.body),
        ).spec.lifecycle.desiredState;
        return Response.json(
          {
            operation: {
              ...operation(writes === 1 ? rid : otherId),
              action: writes === 1 ? "Pause" : "Resume",
              requested_generation: 2 + writes,
            },
            resource,
          },
          { status: 202 },
        );
      }
      return fixtureFetch(path, init);
    };
    const w = open(Releases);
    await flushPromises();
    await w.find(".release-card").trigger("click");
    await flushPromises();
    const button = (label: string) =>
      w.findAll("button").find((b) => b.text() === label)!;
    await button("暂停发布").trigger("click");
    await flushPromises();
    await button("查询原操作").trigger("click");
    await flushPromises();
    expect(button("恢复发布").attributes("disabled")).toBeUndefined();
    await button("恢复发布").trigger("click");
    await flushPromises();
    expect((w.vm as any).$.setupState.operation.id).toBe(otherId);
    releaseA(Response.json(operation(rid)));
    await flushPromises();
    const current = (w.vm as any).$.setupState.operation.id;
    console.log(
      "QA-R03 observed",
      JSON.stringify({
        writes,
        expectedOperation: otherId,
        actualOperation: current,
      }),
    );
    expect(current).toBe(otherId);
  });

  it("QA-C01: Key budget 409 preserves edits and sends one PATCH", async () => {
    let patches = 0;
    api.fetcher = async (path, init) => {
      if (init?.method === "PATCH") {
        patches++;
        return fixtureError("policy_changed", 409);
      }
      return fixtureFetch(path, init);
    };
    const w = open(Keys);
    await flushPromises();
    await w
      .findAll("button")
      .find((b) => b.text() === "修改预算")!
      .trigger("click");
    await w.findAll("form input")[1]!.setValue("8");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toContain("预算策略已变化");
    expect(
      (w.findAll("form input")[1]!.element as HTMLInputElement).value,
    ).toBe("8");
    expect(patches).toBe(1);
  });

  it("QA-C02: missing trusted response ID leaves an interrupted request unknown", async () => {
    let lookups = 0;
    api.fetcher = async (path, init) => {
      if (String(path) === "/v1/chat/completions")
        return new Response("data: ", {
          headers: {
            "Content-Type": "text/event-stream",
            "X-Request-ID": "not-a-uuid",
          },
        });
      if (String(path).includes("request_id=")) lookups++;
      return fixtureFetch(path, init);
    };
    const w = open(Playground);
    await flushPromises();
    await w.find("form select").setValue("model-a");
    await w.find('input[type="password"]').setValue("qa_fixture_only_key");
    await w.find("textarea").setValue("QA synthetic prompt");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toContain("未收到可信原请求 ID，结果未知");
    expect(w.text()).toContain("interrupted");
    expect(lookups).toBe(0);
  });
});
