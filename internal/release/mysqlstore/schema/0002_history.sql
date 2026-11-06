CREATE TABLE IF NOT EXISTS release_history_owners (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 namespace VARCHAR(63) NOT NULL,name VARCHAR(63) NOT NULL,
 authorization_domain VARCHAR(128) NOT NULL,source_kind VARCHAR(64) NOT NULL,
 history_seq BIGINT NOT NULL DEFAULT 0,catalog_version BIGINT NOT NULL DEFAULT 1,
 PRIMARY KEY(cluster_id,cr_uid)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS retained_release_snapshots (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 namespace VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 name VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 generation BIGINT NOT NULL, model_alias VARCHAR(64) NOT NULL,
 source_type ENUM('SelfHosted','ExternalAPI') NOT NULL,
 spec_bytes BLOB NOT NULL, spec_sha256 CHAR(64) NOT NULL,
 revision_input_bytes BLOB NOT NULL,algorithm VARCHAR(64) NOT NULL,
 summary_bytes BLOB NOT NULL,summary_sha256 CHAR(64) NOT NULL,
 history_seq BIGINT NOT NULL,
 source_resource_version VARCHAR(128) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 PRIMARY KEY(cluster_id,cr_uid,revision),
 KEY history_page(cluster_id,cr_uid,created_at DESC,revision DESC),
 CHECK(generation BETWEEN 1 AND 9007199254740991 AND OCTET_LENGTH(spec_bytes)<=65535)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS release_history_retention (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 snapshot_state ENUM('retained','pruning','unavailable') NOT NULL DEFAULT 'retained',
 row_version BIGINT NOT NULL DEFAULT 1,retention_policy_ref VARCHAR(128) NULL,
 PRIMARY KEY(cluster_id,cr_uid,revision)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS release_history_legacy_audit (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 verification_state VARCHAR(32) NOT NULL,missing_fields VARCHAR(256) NOT NULL,
 evidence_locator VARCHAR(256) NULL,migration_version INT NOT NULL,
 PRIMARY KEY(cluster_id,cr_uid,revision)
) ENGINE=InnoDB;
INSERT IGNORE INTO release_history_legacy_audit SELECT v.cluster_id,v.cr_uid,v.revision,'missing','original_spec,resolution,received_at,generation,authorization_domain',NULL,2 FROM release_revisions v LEFT JOIN retained_release_snapshots h ON h.cluster_id=v.cluster_id AND h.cr_uid=v.cr_uid AND h.revision=v.revision WHERE h.revision IS NULL;
CREATE OR REPLACE VIEW release_history_directory AS SELECT l.cluster_id,l.cr_uid,l.namespace,l.name,o.authorization_domain,o.history_seq,o.catalog_version FROM release_links l LEFT JOIN release_history_owners o ON o.cluster_id=l.cluster_id AND o.cr_uid=l.cr_uid;
CREATE OR REPLACE VIEW release_history_projection AS SELECT h.cluster_id,h.cr_uid,h.revision,h.namespace,h.name,h.generation,h.model_alias,h.source_type,h.summary_bytes,h.summary_sha256,h.created_at,h.history_seq,r.snapshot_state FROM retained_release_snapshots h JOIN release_history_retention r ON r.cluster_id=h.cluster_id AND r.cr_uid=h.cr_uid AND r.revision=h.revision;
CREATE OR REPLACE VIEW release_history_completeness AS SELECT v.cluster_id,v.cr_uid,v.revision FROM release_revisions v LEFT JOIN retained_release_snapshots h ON h.cluster_id=v.cluster_id AND h.cr_uid=v.cr_uid AND h.revision=v.revision WHERE h.revision IS NULL;
