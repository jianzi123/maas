CREATE TABLE IF NOT EXISTS release_links (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 namespace VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 name VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 gateway VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 model_alias VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 last_observed_generation BIGINT NOT NULL,
 reconcile_epoch BIGINT NOT NULL DEFAULT 0,
 activation_epoch BIGINT NOT NULL DEFAULT 0,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 desired_mode ENUM('Published','Paused','Deleting') NOT NULL,
 intent_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 candidate_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
 active_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
 admission_closed BOOLEAN NOT NULL DEFAULT TRUE,
 tombstone BOOLEAN NOT NULL DEFAULT FALSE,
 cleanup_complete BOOLEAN NOT NULL DEFAULT FALSE,
 PRIMARY KEY (cluster_id,cr_uid),
 CHECK (last_observed_generation BETWEEN 1 AND 9007199254740991),
 CHECK (reconcile_epoch BETWEEN 1 AND 9007199254740991),
 CHECK (activation_epoch BETWEEN 0 AND 9007199254740991)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS release_revisions (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 PRIMARY KEY (cluster_id,cr_uid,revision)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS publications (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 generation BIGINT NOT NULL,
 revision CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 activation_epoch BIGINT NOT NULL,
 gateway VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 state ENUM('Candidate','Active','Draining','Closed','Cleaned') NOT NULL,
 activated BOOLEAN NOT NULL DEFAULT FALSE,
 PRIMARY KEY (cluster_id,publication_id),
 UNIQUE KEY release_epoch (cluster_id,cr_uid,activation_epoch),
 KEY release_state (cluster_id,cr_uid,state),
 CHECK (generation BETWEEN 1 AND 9007199254740991),
 CHECK (activation_epoch BETWEEN 1 AND 9007199254740991)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS publish_intents (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 reconcile_epoch BIGINT NOT NULL,
 intent_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 PRIMARY KEY (cluster_id,cr_uid,reconcile_epoch)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS active_model_bindings (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 gateway VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 model_alias VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
 admission_closed BOOLEAN NOT NULL DEFAULT TRUE,
 PRIMARY KEY (cluster_id,gateway,model_alias),
 KEY owner_bindings (cluster_id,cr_uid)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS resource_inventory (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 resource_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 publication_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 api_version VARCHAR(253) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 kind VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 namespace VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 name VARCHAR(63) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 object_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
 desired_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 state ENUM('Planned','Bound','Retiring','Removed') NOT NULL,
 PRIMARY KEY (cluster_id,resource_key),
 KEY publication_inventory (cluster_id,cr_uid,publication_id,state)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS release_operations (
 cluster_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 command_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 cr_uid CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 action VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 command_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 committed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (cluster_id,command_id),
 KEY release_commands (cluster_id,cr_uid)
) ENGINE=InnoDB;
