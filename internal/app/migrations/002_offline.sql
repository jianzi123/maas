CREATE TABLE IF NOT EXISTS product_offline_state (
 id INT PRIMARY KEY,
 cluster_id VARCHAR(128) NOT NULL,
 publication_id VARCHAR(36) CHARACTER SET ascii NOT NULL,
 key_id VARCHAR(36) CHARACTER SET ascii NOT NULL,
 key_cipher BLOB NOT NULL
) ENGINE=InnoDB;
