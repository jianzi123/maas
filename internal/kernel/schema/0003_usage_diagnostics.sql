CREATE TABLE IF NOT EXISTS request_snapshot_digests (
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 snapshot_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS request_usage_diagnostics (
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 owner_fence BIGINT NOT NULL, sequence BIGINT NOT NULL,
 diagnostic_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 record_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 record_json JSON NOT NULL,
 PRIMARY KEY(request_id,owner_fence,sequence),
 CHECK(owner_fence BETWEEN 1 AND 9007199254740991),
 CHECK(sequence BETWEEN 1 AND 64)
) ENGINE=InnoDB;
