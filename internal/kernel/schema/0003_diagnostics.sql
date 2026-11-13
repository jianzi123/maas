CREATE TABLE IF NOT EXISTS request_snapshot_digests (
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 snapshot_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS diagnostic_policy (
 id INT PRIMARY KEY, max_records INT NOT NULL, max_bytes INT NOT NULL,
 retention_policy_ref VARCHAR(128) NOT NULL,
 CHECK(id=1 AND max_records BETWEEN 2 AND 4096 AND max_bytes BETWEEN 16384 AND 16777216)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS request_usage_diagnostics (
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 owner_fence BIGINT NOT NULL, sequence BIGINT NOT NULL,
 diagnostic_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 payload_sha256 CHAR(64) NOT NULL, record_bytes BLOB NOT NULL,
 PRIMARY KEY(request_id,owner_fence,sequence),
 CHECK(owner_fence>0 AND sequence>0 AND OCTET_LENGTH(record_bytes)<=8192)
) ENGINE=InnoDB;
