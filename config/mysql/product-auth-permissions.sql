-- Canonical product-auth declaration consumed by provisioning AND install audit.
-- No users, authentication material, broad schema grants or grant option.
CREATE ROLE IF NOT EXISTS maas_product_auth_runtime;
GRANT SELECT ON __MAAS_DATABASE__.product_admins TO maas_product_auth_runtime;
GRANT SELECT ON __MAAS_DATABASE__.product_schema_migrations TO maas_product_auth_runtime;
GRANT SELECT ON __MAAS_DATABASE__.product_offline_state TO maas_product_auth_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.product_sessions TO maas_product_auth_runtime;
GRANT SELECT,INSERT,UPDATE ON __MAAS_DATABASE__.product_login_attempts TO maas_product_auth_runtime;
