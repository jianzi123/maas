-- Explicit installation template; no startup provisioning or CREATE USER.
-- Substitute __MAAS_DATABASE__ with the approved schema identifier.
CREATE ROLE IF NOT EXISTS maas_release_operations_runtime;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.release_management_operations TO maas_release_operations_runtime;
GRANT UPDATE(state,reason,acknowledged,cr_uid,requested_generation,publication_id,updated_at) ON __MAAS_DATABASE__.release_management_operations TO maas_release_operations_runtime;
GRANT SELECT(cluster_id,cr_uid,namespace,name,last_observed_generation,active_id,desired_mode,admission_closed,cleanup_complete,tombstone) ON __MAAS_DATABASE__.release_links TO maas_release_operations_runtime;
GRANT SELECT(cluster_id,publication_id,revision,generation,state,activated) ON __MAAS_DATABASE__.publications TO maas_release_operations_runtime;
GRANT SELECT(cluster_id,cr_uid,revision,spec_sha256) ON __MAAS_DATABASE__.retained_release_snapshots TO maas_release_operations_runtime;
-- MAAS_HISTORY_READER_DSN uses the existing maas_release_history_reader role.
-- MAAS_HISTORY_PAYLOAD_DSN uses this separate private service identity.
CREATE ROLE IF NOT EXISTS maas_history_payload_reader;
GRANT SELECT ON __MAAS_DATABASE__.release_history_directory TO maas_history_payload_reader;
GRANT SELECT(cluster_id,cr_uid,namespace,name,revision,spec_bytes,spec_sha256,revision_input_bytes,algorithm) ON __MAAS_DATABASE__.retained_release_snapshots TO maas_history_payload_reader;
GRANT SELECT(cluster_id,cr_uid,revision,snapshot_state) ON __MAAS_DATABASE__.release_history_retention TO maas_history_payload_reader;
GRANT SELECT(cluster_id,cr_uid,revision) ON __MAAS_DATABASE__.release_revisions TO maas_history_payload_reader;
