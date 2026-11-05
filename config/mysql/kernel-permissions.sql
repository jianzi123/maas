-- Review-only template. Replace __MAAS_DATABASE__ and apply using an authorized
-- provisioning identity. No users, passwords or target-environment mutation.
CREATE ROLE IF NOT EXISTS maas_kernel_runtime;
GRANT SELECT,UPDATE ON __MAAS_DATABASE__.kernel_guard TO maas_kernel_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.platform_keys TO maas_kernel_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.budget_windows TO maas_kernel_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.rate_window_grants TO maas_kernel_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.invocation_profiles TO maas_kernel_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.generation_requests TO maas_kernel_runtime;
GRANT SELECT,UPDATE ON __MAAS_DATABASE__.concurrency_slots TO maas_kernel_runtime;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.usage_events TO maas_kernel_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.usage_daily TO maas_kernel_runtime;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.slot_release_log TO maas_kernel_runtime;
-- Add the existing maas_release_reader role for LockActive's release reads.
-- Configure/slot creation and all migrations use a separate installation role.

-- Release publisher consumes only metadata/counts from the actual kernel. It
-- receives no verifier/pepper, budget/terminal read access, or core write grant.
GRANT SELECT ON __MAAS_DATABASE__.kernel_guard TO maas_release_publisher;
GRANT SELECT ON __MAAS_DATABASE__.invocation_profiles TO maas_release_publisher;
GRANT SELECT(publication_id,result) ON __MAAS_DATABASE__.generation_requests TO maas_release_publisher;
GRANT SELECT(publication_id,state) ON __MAAS_DATABASE__.concurrency_slots TO maas_release_publisher;

CREATE ROLE IF NOT EXISTS maas_slot_worker;
GRANT SELECT,UPDATE(id) ON __MAAS_DATABASE__.kernel_guard TO maas_slot_worker;
GRANT SELECT ON __MAAS_DATABASE__.generation_requests TO maas_slot_worker;
GRANT SELECT,UPDATE ON __MAAS_DATABASE__.concurrency_slots TO maas_slot_worker;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.slot_release_log TO maas_slot_worker;
-- Install the evidence adapter's narrow read grants after its separate review.
-- No Key, budget, terminal or summary INSERT/UPDATE/DELETE is granted to worker.
