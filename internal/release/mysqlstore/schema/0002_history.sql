CREATE TABLE IF NOT EXISTS retained_release_snapshots (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 namespace VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 name VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 generation BIGINT NOT NULL, model_alias VARCHAR(64) NOT NULL,
 source_type ENUM('SelfHosted','ExternalAPI') NOT NULL,
 spec_bytes BLOB NOT NULL, spec_sha256 CHAR(64) NOT NULL,
 source_resource_version VARCHAR(128) NOT NULL,
 created_at DATETIME(6) NOT NULL,
 snapshot_state ENUM('retained','pruning','unavailable') NOT NULL DEFAULT 'retained',
 PRIMARY KEY(cluster_id,cr_uid,revision),
 KEY history_page(cluster_id,cr_uid,created_at DESC,revision DESC),
 CHECK(generation BETWEEN 1 AND 9007199254740991 AND OCTET_LENGTH(spec_bytes)<=65535)
) ENGINE=InnoDB;
