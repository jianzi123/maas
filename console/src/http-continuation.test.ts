declare const process: { env: Record<string, string | undefined> };
const env = process.env;
import { afterAll, describe, expect, it } from "vitest";
import { Api, ADMIN, api } from "./api/client";
import { type S } from "./api/contracts";
import { lookupRequest, revisions } from "./api/recovery";
import { flushPromises, mount } from "@vue/test-utils";
import Keys from "./pages/Keys.vue";
import Usage from "./pages/Usage.vue";
import { releaseSample } from "./fixtures";

// Enabled only by the disposable Go/MySQL foreground harness. No vendor or inference endpoint.
const url = env.MAAS_HTTP_URL;
const network = globalThis.fetch;
const fetcher: typeof fetch = (path, init) => {
  const headers = new Headers(init?.headers);
  headers.set("Cookie", "maas_session=" + env.MAAS_HTTP_SESSION);
  if (init?.method && init.method !== "GET")
    headers.set("Origin", env.MAAS_HTTP_ORIGIN!);
  return network(new URL(String(path), url), { ...init, headers });
};
const client = new Api(fetcher);
client.csrf = env.MAAS_HTTP_CSRF ?? "";
const originalFetcher = api.fetcher,
  originalCSRF = api.csrf;
afterAll(() => {
  api.fetcher = originalFetcher;
  api.csrf = originalCSRF;
});
let created: S["KeyCreated"];
const policy = {
  window_kind: "utc_day",
  limits: { requests: "2", tokens: null, money: null },
};
describe.skipIf(!url)(
  "actual controlled Go/MySQL HTTP with strict console consumers",
  () => {
    it("requires management session", async () => {
      await expect(
        new Api((p, i) => network(new URL(String(p), url), i)).json(
          ADMIN + "/keys",
          "KeyPage",
        ),
      ).rejects.toMatchObject({ status: 401 });
    });
    it("requires CSRF for a write", async () => {
      await expect(
        new Api(fetcher).json(ADMIN + "/keys", "KeyCreated", {
          method: "POST",
          body: JSON.stringify({ name: "denied", budget_policy: policy }),
        }),
      ).rejects.toMatchObject({ status: 403 });
    });
    it("creates a key using strict response validation", async () => {
      created = await client.json(ADMIN + "/keys", "KeyCreated", {
        method: "POST",
        body: JSON.stringify({ name: "FE controlled", budget_policy: policy }),
      });
      expect(created.secret.length).toBeGreaterThan(16);
      expect(created.key.budget_policy.limits.requests).toBe("2");
    });
    it("reads key metadata and never receives its secret again", async () => {
      const p = await client.json<S["KeyPage"]>(ADMIN + "/keys", "KeyPage");
      expect(p.data.some((k) => k.id === created.key.id)).toBe(true);
      expect(JSON.stringify(p)).not.toContain(created.secret);
    });
    it("CAS updates explicit zero and rejects the old revision", async () => {
      const body = JSON.stringify({
        expected_revision: created.key.budget_policy.revision,
        limits: { ...policy.limits, requests: "0" },
      });
      const updated = await client.json<S["Key"]>(
        ADMIN + "/keys/" + created.key.id,
        "Key",
        { method: "PATCH", body },
      );
      expect(updated.budget_policy.limits.requests).toBe("0");
      await expect(
        client.json(ADMIN + "/keys/" + created.key.id, "Key", {
          method: "PATCH",
          body,
        }),
      ).rejects.toMatchObject({ status: 409 });
    });
    it("revokes a key without a generation call", async () => {
      const k = await client.json<S["Key"]>(
        ADMIN + "/keys/" + created.key.id + "/revoke",
        "Key",
        { method: "POST" },
      );
      expect(k.state).toBe("revoked");
    });
    it("exact original UUID returns unknown, without inventing a record", async () => {
      const id = "00000000-0000-4000-8000-000000000099";
      const p = await lookupRequest(client, id);
      expect(p.lookup.request_id).toBe(id);
      expect(p.lookup.resolution).toBe("unknown");
      expect(p.data).toEqual([]);
    });
    it("reads requests and summary with strict stable schemas", async () => {
      const requests = await client.json<S["RequestPage"]>(
        ADMIN + "/usage/requests",
        "RequestPage",
      );
      const summary = await client.json<S["SummaryPage"]>(
        ADMIN + "/usage/summary",
        "SummaryPage",
      );
      expect(requests.data).toEqual([]);
      expect(summary.data).toEqual([]);
    });
    it("missing authoritative history remains 503", async () => {
      await expect(revisions(client, releaseSample)).rejects.toMatchObject({
        status: 503,
      });
    });
    it("renders Key create, one-time dismissal and metadata over actual HTTP", async () => {
      api.fetcher = fetcher;
      api.csrf = client.csrf;
      const w = mount(Keys);
      try {
        await flushPromises();
        await w.find("form input").setValue("FE component HTTP");
        await w.find("select").setValue("utc_day");
        await w.find("form").trigger("submit");
        const s = (w.vm as any).$.setupState;
        await expect.poll(() => s.secret.length > 0).toBe(true);
        await w.vm.$nextTick();
        expect(w.find('[data-testid="one-time-secret"]').exists()).toBe(true);
        await w
          .findAll("button")
          .find((b) => b.text() === "我已保存，关闭原值")!
          .trigger("click");
        expect(s.secret).toBe("");
      } finally {
        w.unmount();
      }
    });
    it("renders the actual empty usage projection", async () => {
      api.fetcher = fetcher;
      api.csrf = client.csrf;
      const w = mount(Usage);
      try {
        await expect.poll(() => w.text()).toContain("当前筛选没有请求。");
      } finally {
        w.unmount();
      }
    });
  },
);
