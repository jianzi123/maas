// New PR10 review probe only. Existing UI16 and Delete QA are not rerun.
import { afterEach, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import Usage from "./pages/Usage.vue";
import { api } from "./api/client";
import { fixtureError, fixtureFetch, resetFixtures } from "./fixtures";

const original = api.fetcher;
const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  api.fetcher = original;
  resetFixtures();
});
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;

for (const success of [false, true]) {
  for (const supersede of [false, true]) {
    it(`PR10 exact lookup reusable and stale reply ignored; success=${success}; refresh=${supersede}`, async () => {
      let resolve!: (value: Response) => void;
      const pending = new Promise<Response>((r) => {
        resolve = r;
      });
      const requests: string[] = [];
      let lookupURL = "";
      api.fetcher = async (path, init) => {
        requests.push(`${init?.method ?? "GET"} ${String(path)}`);
        if (String(path).includes("request_id=")) {
          lookupURL = String(path);
          return pending;
        }
        return fixtureFetch(path, init);
      };
      const w = mount(Usage);
      mounted.push(w);
      await flushPromises();
      await w
        .get('input[placeholder="可信的原 request_id"]')
        .setValue("00000000-0000-4000-8000-000000000001");
      await button(w, "精确回查").trigger("click");
      await flushPromises();
      expect(button(w, "回查中…").attributes("disabled")).toBeDefined();
      if (supersede) {
        await button(w, "刷新数据").trigger("click");
        await flushPromises();
      }
      resolve(
        success
          ? await fixtureFetch(lookupURL)
          : fixtureError("dependency_unavailable", 503),
      );
      await flushPromises();
      const lookup = w
        .findAll("button")
        .find((b) => ["精确回查", "回查中…"].includes(b.text()))!;
      console.log(
        JSON.stringify({
          success,
          supersede,
          button: lookup.text(),
          disabled: lookup.attributes("disabled") !== undefined,
          requests,
        }),
      );
      expect(w.find("dialog").exists()).toBe(success && !supersede);
      expect(
        requests.filter((path) => path.includes("request_id=")),
      ).toHaveLength(1);
      expect(requests.every((path) => path.startsWith("GET "))).toBe(true);
      expect(lookup.text()).toBe("精确回查");
      expect(lookup.attributes("disabled")).toBeUndefined();
    });
  }
}
