import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import stable from "../../contracts/openapi-v0.4.json";
import draft from "../../contracts/query-recovery-draft.json";
import type { components } from "./schema";
import type { components as Draft } from "./draft-schema";
export type S = components["schemas"];
export type D = Draft["schemas"];
const ajv = new Ajv({ strict: false, allErrors: false, validateFormats: true });
addFormats(ajv);
ajv.addSchema({ $id: "stable", components: stable.components });
ajv.addSchema({ $id: "draft", components: draft.components });
export function validate<T>(
  name: string,
  value: unknown,
  version: "stable" | "draft" = "stable",
): T {
  const check = ajv.getSchema(`${version}#/components/schemas/${name}`);
  if (!check || !check(value))
    throw new Error(`接口数据不符合 ${name} 契约，请核对服务版本或输入字段。`);
  return value as T;
}
