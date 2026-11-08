import { ADMIN, Api, ApiError } from "./client";
import type { S, D } from "./contracts";
export const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// Opt-in draft adapter: old servers must never silently fall back to a list.
export async function lookupRequest(
  client: Api,
  id: string,
): Promise<D["RequestLookupPage"]> {
  if (!uuid.test(id)) throw new Error("需要可信的原请求 UUID。");
  const page = await client.json<D["RequestLookupPage"]>(
    `${ADMIN}/usage/requests?request_id=${encodeURIComponent(id)}`,
    "RequestLookupPage",
    {},
    "draft",
  );
  if (
    page.lookup.request_id !== id ||
    page.data.some((row) => row.request_id !== id)
  )
    throw new Error("精确回查关联不一致，结果未知。");
  return page;
}
export function releasePath(r: S["ReleaseModelRelease"]) {
  return `${ADMIN}/model-releases/${encodeURIComponent(r.metadata.namespace)}/${encodeURIComponent(r.metadata.name)}`;
}
export function releaseUpdateAction(
  current: S["ReleaseModelRelease"],
  input: S["ReleaseReleaseInput"],
): S["ReleaseOperation"]["action"] {
  if (current.spec.lifecycle.desiredState === input.spec.lifecycle.desiredState)
    return "Update";
  return input.spec.lifecycle.desiredState === "Paused" ? "Pause" : "Resume";
}
export async function revisions(
  client: Api,
  r: S["ReleaseModelRelease"],
  cursor?: string,
): Promise<D["ReleaseRevisionPage"]> {
  const uid = r.metadata.uid;
  if (!uid || !uuid.test(uid))
    throw new Error("缺少可信 CR UID，无法读取修订。");
  const q = new URLSearchParams({ cr_uid: uid });
  if (cursor) q.set("cursor", cursor);
  const page = await client.json<D["ReleaseRevisionPage"]>(
    `${releasePath(r)}/revisions?${q}`,
    "ReleaseRevisionPage",
    {},
    "draft",
  );
  if (page.requested_cr_uid !== uid || page.data.some((x) => x.cr_uid !== uid))
    throw new Error("修订归属不一致。");
  return page;
}
export function canRollback(
  page: D["ReleaseRevisionPage"],
  row: D["ReleaseRetainedRevision"],
  r: S["ReleaseModelRelease"],
) {
  return (
    page.resource_state === "present" &&
    page.requested_cr_uid === r.metadata.uid &&
    page.resource_version === r.metadata.resourceVersion &&
    row.cr_uid === r.metadata.uid &&
    row.snapshot_state === "retained" &&
    row.rollback_eligibility.state === "eligible" &&
    row.rollback_eligibility.evaluated_resource_version ===
      page.resource_version
  );
}

// A valid response shape does not establish ownership of a write acknowledgement.
export function assertReleaseAccepted(
  accepted: S["ReleaseAccepted"],
  expected: {
    namespace: string;
    name: string;
    uid?: string;
    action: S["ReleaseOperation"]["action"];
  },
) {
  const op = accepted.operation,
    r = accepted.resource;
  if (
    op.namespace !== expected.namespace ||
    op.name !== expected.name ||
    op.action !== expected.action ||
    (expected.uid !== undefined && op.cr_uid !== expected.uid) ||
    (r &&
      (r.metadata.namespace !== expected.namespace ||
        r.metadata.name !== expected.name ||
        (expected.uid !== undefined && r.metadata.uid !== expected.uid) ||
        !r.metadata.uid ||
        op.cr_uid !== r.metadata.uid ||
        (op.requested_generation !== null &&
          op.requested_generation !== r.metadata.generation)))
  )
    throw new ApiError("protocol_error", 202, true);
}
