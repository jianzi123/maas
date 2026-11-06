-- Review template: replace __MAAS_DATABASE__ with the approved schema identifier.
-- Run only with an explicitly authorized provisioning identity. No passwords,
-- CREATE USER, automatic startup migration, or grants on business ledgers here.
CREATE ROLE IF NOT EXISTS maas_release_publisher;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.release_links TO maas_release_publisher;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.release_revisions TO maas_release_publisher;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.publish_intents TO maas_release_publisher;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.publications TO maas_release_publisher;
GRANT SELECT,INSERT,UPDATE,DELETE ON __MAAS_DATABASE__.active_model_bindings TO maas_release_publisher;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.resource_inventory TO maas_release_publisher;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.release_operations TO maas_release_publisher;
GRANT SELECT ON __MAAS_DATABASE__.release_schema_migrations TO maas_release_publisher;

-- The Operator has no MySQL identity; it uses the authenticated release-control
-- interface. The Go kernel's connection owns business writes, and needs SELECT
-- on these release tables for LockActive in its one admission transaction.
CREATE ROLE IF NOT EXISTS maas_release_reader;
GRANT SELECT ON __MAAS_DATABASE__.release_links TO maas_release_reader;
GRANT SELECT ON __MAAS_DATABASE__.publications TO maas_release_reader;
GRANT SELECT ON __MAAS_DATABASE__.active_model_bindings TO maas_release_reader;

-- The existing core must separately grant only the required guard/evidence
-- reads to the publisher adapter. Its exact DDL/ownership is not in this repo.
-- Publisher guard reads use FOR SHARE (SELECT only), not FOR UPDATE, which
-- would additionally require UPDATE/DELETE/LOCK TABLES privileges in MySQL.
-- No Key/budget/request/usage/terminal/slot UPDATE or INSERT is authorized by
-- this template. Migration uses a separate, temporary DDL identity.
GRANT SELECT,INSERT ON __MAAS_DATABASE__.retained_release_snapshots TO maas_release_publisher;
GRANT SELECT,INSERT,UPDATE(history_seq) ON __MAAS_DATABASE__.release_history_owners TO maas_release_publisher;
GRANT SELECT,INSERT ON __MAAS_DATABASE__.release_history_retention TO maas_release_publisher;
CREATE ROLE IF NOT EXISTS maas_release_history_reader;
GRANT SELECT ON __MAAS_DATABASE__.release_history_directory TO maas_release_history_reader;
GRANT SELECT ON __MAAS_DATABASE__.release_history_projection TO maas_release_history_reader;
GRANT SELECT ON __MAAS_DATABASE__.release_history_completeness TO maas_release_history_reader;
GRANT SELECT ON __MAAS_DATABASE__.release_links TO maas_release_history_reader;
GRANT SELECT ON __MAAS_DATABASE__.publications TO maas_release_history_reader;
