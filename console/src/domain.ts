import type { S } from "./api/contracts";
export function display(value: string | number | null | undefined) {
  return value == null ? "未知 / 不可获取" : String(value);
}
export function integer(value: string) {
  if (!/^(0|[1-9][0-9]{0,37})$/.test(value))
    throw new Error("限额需为最多 38 位的非负整数字符串。");
  return value;
}
export function budgetInput(form: {
  window: string;
  requests: string;
  tokens: string;
  money: string;
  currency: string;
}): S["BudgetPolicyInput"] {
  if (!["utc_day", "utc_month"].includes(form.window))
    throw new Error("请选择 UTC 周期。");
  if (form.money !== "" && !/^[A-Z]{3}$/.test(form.currency))
    throw new Error("请输入三位大写币种。");
  return {
    window_kind: form.window as "utc_day" | "utc_month",
    limits: {
      requests: form.requests === "" ? null : integer(form.requests),
      tokens: form.tokens === "" ? null : integer(form.tokens),
      money:
        form.money === ""
          ? null
          : { currency: form.currency, limit_atomic: integer(form.money) },
    },
  };
}
export function condition(
  r: S["ReleaseModelRelease"],
  name: S["ReleaseCondition"]["type"],
) {
  return r.status?.conditions.find((c) => c.type === name);
}
// Old active publication may remain callable while the desired candidate fails. Do not derive from phase.
export function callableLabel(r: S["ReleaseModelRelease"]) {
  const c = condition(r, "Callable");
  return c?.status === "True"
    ? "活动版本可调用"
    : c?.status === "False"
      ? "不可调用"
      : "可调用状态未知";
}
export function latestOnly<T>() {
  let version = 0;
  return {
    invalidate: () => ++version,
    run: async (task: () => Promise<T>, commit: (v: T) => void) => {
      const mine = ++version;
      const value = await task();
      if (mine === version) commit(value);
    },
  };
}
