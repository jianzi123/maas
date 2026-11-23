import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import contract from "../../contracts/ar1-openapi.json";
import eventSchema from "../../contracts/ar1-session-event.schema.json";
import type { components } from "./ar1-schema";
export type AR = components["schemas"];
const ajv = new Ajv({ strict: false, allErrors: false, validateFormats: true });
addFormats(ajv);
ajv.addSchema({ $id: "ar1", components: contract.components });
const checkEvent = ajv.compile({
  ...eventSchema,
  components: contract.components,
});
export function checked<K extends keyof AR>(name: K, value: unknown): AR[K] {
  const check = ajv.getSchema(`ar1#/components/schemas/${name}`);
  if (!check || !check(value)) throw Error(`AR-1 ${name} 响应不符合锁定契约。`);
  return value as AR[K];
}
export function checkedEvent(value: unknown): AR["SessionEvent"] {
  if (!checkEvent(value)) throw Error("AR-1 事件不符合锁定契约。");
  return value as AR["SessionEvent"];
}
export const activeStates = [
  "accepted",
  "running",
  "waiting_approval",
  "needs_confirmation",
];
