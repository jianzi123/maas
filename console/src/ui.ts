import { ref, shallowRef, onBeforeUnmount } from "vue";
import { ApiError } from "./api/client";
export function explain(e: unknown) {
  return e instanceof ApiError
    ? e.message +
        (e.resetAt ? " 重置时间：" + e.resetAt : "") +
        (e.retryAfter !== null
          ? " 建议等待 " + e.retryAfter + " 秒后手动操作。"
          : "")
    : e instanceof Error
      ? e.message
      : "操作未完成。";
}
export function uncertain(e: unknown) {
  return e instanceof ApiError && e.uncertain;
}
export function usePage<T>(
  load: (cursor?: string) => Promise<{
    data: T[];
    next_cursor?: string | null;
    generated_at?: string;
    data_complete?: boolean;
  }>,
) {
  const rows = shallowRef<T[]>([]),
    busy = ref(false),
    error = ref(""),
    cursor = ref<string | null>(null),
    at = ref(""),
    complete = ref(true);
  let epoch = 0;
  async function refresh(more = false) {
    const mine = ++epoch;
    busy.value = true;
    error.value = "";
    try {
      const p = await load(more ? (cursor.value ?? undefined) : undefined);
      if (mine !== epoch) return;
      rows.value = more ? [...rows.value, ...p.data] : p.data;
      cursor.value = p.next_cursor ?? null;
      at.value = p.generated_at ?? "";
      complete.value = p.data_complete ?? true;
    } catch (e) {
      if (mine === epoch) {
        error.value = explain(e);
        if (!more) rows.value = [];
      }
    } finally {
      if (mine === epoch) busy.value = false;
    }
  }
  onBeforeUnmount(() => {
    epoch++;
  });
  return { rows, busy, error, cursor, at, complete, refresh };
}
