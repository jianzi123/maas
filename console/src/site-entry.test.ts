import { afterEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import App from "./App.vue";
import { api, ADMIN } from "./api/client";
import { fixtureFetch, fixtureError, resetFixtures } from "./fixtures";
const original = api.fetcher;
let wrapper: ReturnType<typeof mount> | undefined;
afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  api.fetcher = original;
  api.csrf = "";
  location.hash = "";
  vi.restoreAllMocks();
  resetFixtures();
});
for (const denied of [false, true])
  it(
    "bootstrap session response must settle before credentials become editable; denied=" +
      denied,
    async () => {
      let release!: (response: Response) => void;
      const pending = new Promise<Response>((resolve) => {
        release = resolve;
      });
      const calls: { path: string; method: string; body: unknown }[] = [];
      api.fetcher = vi.fn(async (input, init) => {
        const path = String(input),
          method = init?.method ?? "GET";
        calls.push({
          path,
          method,
          body: init?.body ? JSON.parse(String(init.body)) : null,
        });
        if (path === ADMIN + "/session" && method === "GET") return pending;
        if (path === ADMIN + "/session" && method === "POST" && denied)
          return fixtureError("unauthenticated", 401);
        return fixtureFetch(input, init);
      }) as typeof fetch;
      wrapper = mount(App);
      await flushPromises();
      expect(
        wrapper.get('input[autocomplete="username"]').attributes("disabled"),
      ).toBeDefined();
      expect(
        wrapper.get('input[type="password"]').attributes("disabled"),
      ).toBeDefined();
      expect(calls.filter((c) => c.method === "POST")).toEqual([]);
      release(fixtureError("unauthenticated", 401));
      await flushPromises();
      expect(
        wrapper.get('input[type="password"]').attributes("disabled"),
      ).toBeUndefined();
      await wrapper
        .get('input[autocomplete="username"]')
        .setValue("fixture-admin");
      await wrapper.get('input[type="password"]').setValue("fixture-password");
      await wrapper.get("form").trigger("submit");
      await flushPromises();
      expect(calls.filter((c) => c.method === "POST")).toEqual([
        {
          path: ADMIN + "/session",
          method: "POST",
          body: { username: "fixture-admin", password: "fixture-password" },
        },
      ]);
      if (denied) {
        expect(
          (wrapper.get('input[type="password"]').element as HTMLInputElement)
            .value,
        ).toBe("");
        expect(
          wrapper.get('input[type="password"]').attributes("disabled"),
        ).toBeUndefined();
      } else expect(wrapper.text()).toContain("退出会话");
    },
  );
