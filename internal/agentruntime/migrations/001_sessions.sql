CREATE TABLE IF NOT EXISTS agent_sessions_v1 (
 session_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 owner_id VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 revision BIGINT NOT NULL,
 document JSON NOT NULL,
 INDEX owner_sessions(owner_id, session_id)
) ENGINE=InnoDB;
