CREATE TABLE IF NOT EXISTS kernel_guard (
 id INT PRIMARY KEY, cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 rate_revision VARCHAR(128) NOT NULL, rate_epoch BIGINT NOT NULL,
 rate_ready BOOLEAN NOT NULL DEFAULT FALSE, window_ms BIGINT NOT NULL,
 global_limit BIGINT NOT NULL, key_limit BIGINT NOT NULL,
 CHECK(id=1), CHECK(rate_epoch BETWEEN 1 AND 9007199254740991),
 CHECK(window_ms>0 AND global_limit>0 AND key_limit>0)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS platform_keys (
 key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 verifier CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 key_epoch BIGINT NOT NULL, revoked BOOLEAN NOT NULL DEFAULT FALSE,
 blocked BOOLEAN NOT NULL DEFAULT FALSE, policy_json JSON NOT NULL,
 retained_currency CHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL,
 CHECK(key_epoch BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS budget_windows (
 key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 window_start DATETIME(6) NOT NULL, window_end DATETIME(6) NOT NULL,
 dimension ENUM('requests','tokens','money') NOT NULL,
 known_used DECIMAL(38,0) NOT NULL DEFAULT 0,
 inflight_reserved DECIMAL(38,0) NOT NULL DEFAULT 0,
 uncertainty_held DECIMAL(38,0) NOT NULL DEFAULT 0,
 PRIMARY KEY(key_id,window_start,dimension),
 CHECK(known_used>=0 AND inflight_reserved>=0 AND uncertainty_held>=0)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS rate_window_grants (
 scope_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 window_start DATETIME(6) NOT NULL, policy_id VARCHAR(128) NOT NULL,
 window_end DATETIME(6) NOT NULL, grants BIGINT NOT NULL,
 PRIMARY KEY(scope_id,window_start,policy_id), CHECK(grants>=0)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS invocation_profiles (
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 snapshot_json JSON NOT NULL, snapshot_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 blocked BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS generation_requests (
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 owner_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 owner_fence BIGINT NOT NULL, hard_deadline DATETIME(6) NOT NULL,
 snapshot_json JSON NOT NULL,
 result ENUM('in_progress','succeeded','failed','cancelled','timed_out','interrupted') NOT NULL,
 terminal_event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL UNIQUE,
 KEY publication_requests(publication_id,result), KEY recover_requests(result,hard_deadline),
 CHECK(owner_fence BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS concurrency_slots (
 slot_id BIGINT PRIMARY KEY, state ENUM('FREE','HELD','QUARANTINED') NOT NULL,
 allocation_fence BIGINT NOT NULL DEFAULT 0, row_version BIGINT NOT NULL DEFAULT 0,
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL UNIQUE,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
 hard_deadline DATETIME(6) NULL,
 release_not_before DATETIME(6) NULL, quarantine_reason VARCHAR(64) NULL,
 KEY publication_slots(publication_id,state),
 CHECK(allocation_fence BETWEEN 0 AND 9007199254740991),
 CHECK(row_version BETWEEN 0 AND 9007199254740991),
 CHECK((state='FREE' AND request_id IS NULL AND publication_id IS NULL AND hard_deadline IS NULL AND release_not_before IS NULL) OR
       (state<>'FREE' AND request_id IS NOT NULL AND publication_id IS NOT NULL AND hard_deadline IS NOT NULL AND release_not_before IS NOT NULL))
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS usage_events (
 event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 event_type VARCHAR(32) NOT NULL, input_sha256 CHAR(64) NOT NULL,
 event_json JSON NOT NULL, committed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY only_terminal(request_id,event_type)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS usage_daily (
 key_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 quota_date DATE NOT NULL, result VARCHAR(16) NOT NULL,
 finalized_total BIGINT NOT NULL DEFAULT 0,
 PRIMARY KEY(key_id,quota_date,result)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS slot_release_log (
 slot_id BIGINT NOT NULL, allocation_fence BIGINT NOT NULL,
 request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 reason VARCHAR(32) NOT NULL, evidence_ref CHAR(36) NOT NULL,
 actor_id CHAR(36) NOT NULL, hard_deadline DATETIME(6) NOT NULL,
 released_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(slot_id,allocation_fence)
) ENGINE=InnoDB;
