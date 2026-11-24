import { afterEach, expect, it } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { api, ADMIN } from "./api/client";
import {
  fixtureFetch,
  resetFixtures,
  releaseSample,
  fixtureError,
} from "./fixtures";
import Models from "./pages/Models.vue";
import Releases from "./pages/Releases.vue";
import ReleaseForm from "./components/ReleaseForm.vue";
import Usage from "./pages/Usage.vue";
import { validate } from "./api/contracts";
const mounted: ReturnType<typeof mount>[] = [];
const original = api.fetcher;
const open = (c: any, p: any = {}) => {
  const w = mount(c, p);
  mounted.push(w);
  return w;
};
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  api.fetcher = original;
  resetFixtures();
});
it("catalogue filters current models and opens original binding in a dialog", async () => {
  api.fetcher = fixtureFetch;
  const w = open(Models);
  await flushPromises();
  await w.get("input[type=search]").setValue("does-not-exist");
  expect(w.findAll(".model-card")).toHaveLength(0);
  await w.get("input[type=search]").setValue("");
  expect(w.findAll(".model-card").length).toBeGreaterThan(0);
  await button(w, "查看详情").trigger("click");
  expect(w.find("dialog").exists()).toBe(true);
  expect(w.get("dialog").text()).toContain("活动修订");
  await button(w, "私有推理").trigger("click");
  expect(
    w.findAll(".model-card").every((c) => c.text().includes("私有推理")),
  ).toBe(true);
});
it("full external form retains all fields and synchronizes structured edits with strict JSON", async () => {
  const input = {
    apiVersion: releaseSample.apiVersion,
    kind: releaseSample.kind,
    metadata: {
      name: releaseSample.metadata.name,
      namespace: releaseSample.metadata.namespace,
    },
    spec: structuredClone(releaseSample.spec),
  };
  const w = open(ReleaseForm, {
    props: {
      modelValue: JSON.stringify(input),
      "onUpdate:modelValue": (v: string) => w.setProps({ modelValue: v }),
    },
  });
  await w.get('[data-field="spec.modelAlias"]').setValue("new-alias");
  expect(
    JSON.parse((w.get("textarea").element as HTMLTextAreaElement).value).spec
      .modelAlias,
  ).toBe("new-alias");
  await button(w, "3 批准引用").trigger("click");
  expect(w.findAll("input")).toHaveLength(8); // gateway + three business refs, name/revision each
  await w
    .get('[data-field="spec.businessRefs.pricePolicyRef.revision"]')
    .setValue("price-v2");
  const value = JSON.parse(
    (w.get("textarea").element as HTMLTextAreaElement).value,
  );
  expect(value.spec.businessRefs.pricePolicyRef.revision).toBe("price-v2");
  expect(value.spec.source).toEqual(input.spec.source);
  expect(() => validate("ReleaseReleaseInput", value)).not.toThrow();
  await w.get("textarea").setValue("{ invalid");
  expect(w.text()).toContain("尚未通过完整 Schema");
  await button(w, "5 确认提交").trigger("click");
  expect(button(w, "校验并提交配置").attributes("disabled")).toBeDefined();
});
it("private form exposes every runtime/placement field and blocks empty references", async () => {
  api.fetcher = fixtureFetch;
  const w = open(Releases);
  await flushPromises();
  await button(w, "新建私有推理 CR").trigger("click");
  const form = w.findComponent(ReleaseForm);
  await button(form as any, "2 模型来源").trigger("click");
  for (const field of [
    "weights.sha256",
    "runtimeProfileRef.revision",
    "placementProfileRef.revision",
    "image",
    "groups",
    "tensorParallelSize",
  ]) {
    expect(
      form.find('[data-field="spec.source.selfHosted.' + field + '"]').exists(),
    ).toBe(true);
  }
  await button(form as any, "5 确认提交").trigger("click");
  expect(
    button(form as any, "校验并提交配置").attributes("disabled"),
  ).toBeDefined();
});
it("request detail preserves unknown accounting and original identifiers", async () => {
  api.fetcher = fixtureFetch;
  const w = open(Usage);
  await flushPromises();
  await button(w, "请求详情").trigger("click");
  expect(w.get("dialog").text()).toContain("未知 / 不可获取");
  expect(w.get("dialog").text()).toContain("Key ID");
  await button(w, "查看此 Key 用量").trigger("click");
  await flushPromises();
  expect(w.find("dialog").exists()).toBe(false);
  expect(w.text()).toContain("按 Key 查询");
});
it("Delete terminal recovery unlocks creation without rereading an absent CR or replaying DELETE", async () => {
  let op: any;
  let writes = 0;
  api.fetcher = async (p, i) => {
    if (String(p).includes("/release-operations/"))
      return Response.json({ ...op, state: "Succeeded" });
    const res = await fixtureFetch(p, i);
    if (i?.method === "DELETE") {
      writes++;
      const accepted = await res.json();
      accepted.operation.state = "Unknown";
      accepted.resource = null;
      op = accepted.operation;
      return Response.json(accepted, { status: 202 });
    }
    return res;
  };
  const w = open(Releases);
  await flushPromises();
  await w.get(".release-card").trigger("click");
  await flushPromises();
  await button(w, "下线并清理").trigger("click");
  await button(w, "确认下线").trigger("click");
  await flushPromises();
  expect(button(w, "新建外部 API CR").attributes("disabled")).toBeDefined();
  await button(w, "查询原操作").trigger("click");
  await flushPromises();
  expect(button(w, "新建外部 API CR").attributes("disabled")).toBeUndefined();
  expect(w.text()).toContain(op.id);
  expect(w.text()).toContain("原删除操作已确认完成");
  expect(writes).toBe(1);
});
it("a failed exact lookup cannot fabricate an empty successful record", async () => {
  api.fetcher = async (p, i) =>
    String(p).includes("request_id=")
      ? fixtureError("dependency_unavailable", 503)
      : fixtureFetch(p, i);
  const w = open(Usage);
  await flushPromises();
  await w
    .get('input[placeholder="可信的原 request_id"]')
    .setValue("00000000-0000-4000-8000-000000000001");
  await button(w, "精确回查").trigger("click");
  await flushPromises();
  expect(w.find("dialog").exists()).toBe(false);
  expect(w.find("[role=alert]").text()).toContain("依赖");
});

it("new generation never inherits old target progress while active callable stays independent", async () => {
  api.fetcher = async (p, i) => {
    const response = await fixtureFetch(p, i);
    if (!i?.method && String(p).endsWith("/" + releaseSample.metadata.name)) {
      const resource = await response.json();
      resource.metadata.generation = 99;
      return Response.json(resource);
    }
    return response;
  };
  const w = open(Releases);
  await flushPromises();
  await w.get(".release-card").trigger("click");
  await flushPromises();
  expect(w.get(".info-strip").text()).toContain("等待观测新配置");
  expect(
    w
      .findAll(".release-progress li.done")
      .every((c) => c.text().includes("可调用")),
  ).toBe(true);
});
