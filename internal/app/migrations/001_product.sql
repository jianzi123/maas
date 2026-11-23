CREATE TABLE IF NOT EXISTS product_admins (
 admin_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 username VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL UNIQUE,
 salt VARBINARY(32) NOT NULL,
 verifier VARBINARY(32) NOT NULL,
 policy_revision VARCHAR(36) CHARACTER SET ascii NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS product_sessions (
 token_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 admin_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 csrf_token VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 expires_at DATETIME(6) NOT NULL,
 revoked BOOLEAN NOT NULL DEFAULT FALSE,
 INDEX admin_sessions(admin_id,expires_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS product_login_attempts (
 identity_sha256 CHAR(64) CHARACTER SET ascii PRIMARY KEY,
 window_start BIGINT NOT NULL,
 attempts INT NOT NULL
) ENGINE=InnoDB;
