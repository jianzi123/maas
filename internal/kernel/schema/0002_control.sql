CREATE TABLE IF NOT EXISTS key_metadata (
 key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 name VARCHAR(64) NOT NULL, key_prefix VARCHAR(16) NOT NULL,
 created_at DATETIME(6) NOT NULL, revoked_at DATETIME(6) NULL,
 purpose ENUM('serving','validation') NOT NULL DEFAULT 'serving'
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS rate_rebuilds (
 epoch BIGINT PRIMARY KEY, redis_identity VARCHAR(128) NOT NULL,
 nonce CHAR(36) NOT NULL, window_start DATETIME(6) NOT NULL,
 completed_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS publication_proofs (
 proof_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 kind ENUM('runtime','gateway') NOT NULL, issuer VARCHAR(128) NOT NULL,
 payload_sha256 CHAR(64) NOT NULL, profile_sha256 CHAR(64) NOT NULL,
 observed_at DATETIME(6) NOT NULL, expires_at DATETIME(6) NOT NULL,
 revoked BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE KEY exact_payload(proof_id,payload_sha256), KEY proof_lookup(publication_id,kind)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS validation_intents (
 intent_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 policy_revision VARCHAR(128) NOT NULL, request_id CHAR(36) NOT NULL UNIQUE,
 key_id CHAR(36) NOT NULL, profile_sha256 CHAR(64) NOT NULL,
 expires_at DATETIME(6) NOT NULL, revoked BOOLEAN NOT NULL DEFAULT FALSE,
 UNIQUE KEY one_validation(publication_id,policy_revision)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS validation_receipts (
 intent_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 request_id CHAR(36) NOT NULL UNIQUE, event_id CHAR(36) NOT NULL UNIQUE,
 publication_id CHAR(36) NOT NULL, profile_sha256 CHAR(64) NOT NULL,
 finished_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;
