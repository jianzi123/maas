#!/bin/bash
set -euo pipefail
database="${MAAS_INSTALL_DATABASE:-maas}"
[[ "$database" =~ ^[A-Za-z0-9_]+$ ]] || exit 2
# This process is one-shot and holds only installation credentials.
# Application serve is never given the migration DSN/bootstrap password.
/maas migrate --config /etc/maas/migration.json
if [[ "${MAAS_INSTALL_PROVISION_ROLES:-1}" == 0 ]]; then
  echo "Migrations complete; installer uses pre-provisioned roles."
  exit 0
fi
for file in release-permissions.sql kernel-permissions.sql controlapi-projections.sql; do
  sed "s/__MAAS_DATABASE__/$database/g" "/app/sql/$file" |
    mysql --defaults-extra-file=/run/secrets/mysql-client.cnf
done
sed "s/__MAAS_DATABASE__/$database/g" /app/sql/agent-runtime-role.sql |
  mysql --defaults-extra-file=/run/secrets/mysql-client.cnf
password="$(cat /run/secrets/maas_runtime_password)"
[[ "$password" =~ ^[A-Za-z0-9_-]{32,128}$ ]] || exit 2
if ! mysql --defaults-extra-file=/run/secrets/mysql-client.cnf >/dev/null 2>/dev/null <<SQL
CREATE ROLE IF NOT EXISTS maas_product_auth_runtime;
GRANT SELECT ON $database.product_admins TO maas_product_auth_runtime;
GRANT SELECT ON $database.product_schema_migrations TO maas_product_auth_runtime;
GRANT SELECT ON $database.product_offline_state TO maas_product_auth_runtime;
GRANT SELECT,INSERT,UPDATE ON $database.product_sessions TO maas_product_auth_runtime;
GRANT SELECT,INSERT,UPDATE ON $database.product_login_attempts TO maas_product_auth_runtime;
CREATE USER IF NOT EXISTS 'maas_runtime'@'%' IDENTIFIED BY '$password';
SQL
then
  echo "Runtime account/default-role provisioning failed; secret-bearing SQL is not logged." >&2
  exit 1
fi
# Reject older overgrants instead of silently retaining them. Also reject any
# inherited role beneath a permitted role; DBA review remains necessary for
# direct object grants and modifications to the role templates themselves.
unexpected="$(mysql --defaults-extra-file=/run/secrets/mysql-client.cnf --batch --skip-column-names <<'SQL'
SELECT
 (SELECT COUNT(*) FROM mysql.role_edges WHERE
   (TO_USER='maas_runtime' AND TO_HOST='%' AND
    (FROM_HOST<>'%' OR FROM_USER NOT IN ('maas_kernel_runtime','maas_release_reader','maas_agent_session_runtime','maas_product_auth_runtime') OR WITH_ADMIN_OPTION<>'N'))
   OR (TO_HOST='%' AND TO_USER IN ('maas_kernel_runtime','maas_release_reader','maas_agent_session_runtime','maas_product_auth_runtime')))
 + (SELECT COUNT(*) FROM mysql.default_roles WHERE USER='maas_runtime' AND HOST='%' AND
    (DEFAULT_ROLE_HOST<>'%' OR DEFAULT_ROLE_USER NOT IN ('maas_kernel_runtime','maas_release_reader','maas_agent_session_runtime','maas_product_auth_runtime')));
SQL
)"
if [[ "$unexpected" != 0 ]]; then
  echo "Runtime has unexpected direct/default/inherited roles; request authorized DBA review. No existing roles were revoked." >&2
  exit 1
fi
mysql --defaults-extra-file=/run/secrets/mysql-client.cnf <<'SQL'
GRANT maas_kernel_runtime,maas_release_reader,maas_agent_session_runtime,maas_product_auth_runtime TO 'maas_runtime'@'%';
SET DEFAULT ROLE maas_kernel_runtime,maas_release_reader,maas_agent_session_runtime,maas_product_auth_runtime TO 'maas_runtime'@'%';
SQL
echo "Migrations and explicit runtime roles completed; no existing password or ledger is reset."
