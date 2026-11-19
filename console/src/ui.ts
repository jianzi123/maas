import { ref, shallowRef, onBeforeUnmount } from "vue";
import { ApiError } from "./api/client";
export function explain(e: unknown) {
  return e instanceof ApiError
    ? e.message +
        (e.status === 403
          ? " 请核对当前身份及权限。"
          : e.status === 409
            ? " 刷新权威记录后再手动决定。"
            : e.status === 503
              ? " 请待依赖恢复后重新查询。"
              : "") +
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

const labels: Record<string, string> = {
  idle: "等待输入",
  streaming: "正在接收",
  completed: "传输完成",
  stopped: "已停止接收",
  interrupted: "传输中断",
  in_progress: "进行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "已超时",
  verified: "已核验",
  unverified: "待核验",
  unsupported: "不支持",
  unknown: "未知",
  available: "检查可用",
  unavailable: "不可用",
  Pending: "待处理",
  Preparing: "准备中",
  Validating: "验证中",
  Ready: "目标就绪",
  Updating: "更新中",
  Paused: "已暂停",
  Draining: "排空中",
  Deleting: "清理中",
  Degraded: "部分受阻",
  Failed: "失败",
  Accepted: "已受理",
  Running: "执行中",
  Succeeded: "已完成",
  Unknown: "结果未知",
};
export function statusLabel(value: string) {
  return labels[value] ?? value;
}
const reasons: Record<string, string> = {
  DependencyMissing: "依赖尚未装配；请联系管理员核对配置。",
  CredentialsUnavailable: "凭证引用尚不可用；请核对批准引用。",
  GatewayNotApplied: "网关尚未确认配置；等待管理员核验。",
  ValidationAuthorizationMissing: "缺少验证授权；请联系管理员。",
  ValidationUnknown: "验证结果未知；仅回查原操作，不重复发起。",
  AccountingUnavailable: "计量依赖未就绪；请联系管理员。",
  ProfileUnapproved: "配置引用尚未批准；请核对引用版本。",
  DrainTimeout: "排空等待超时；保留资源并核对原请求。",
  CleanupBlocked: "安全清理条件未满足；请核对排空证据。",
  AliasConflict: "模型别名已占用；请核对归属后调整。",
};
export function reasonLabel(reason: string) {
  return reasons[reason] ?? "服务端原因：" + reason + "；请核对下方原始信息。";
}
