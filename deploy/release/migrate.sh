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
GRANT SELECT,INSERT,UPDATE ON $database.product_sessions TO maas_product_auth_runtime;
GRANT SELECT,INSERT,UPDATE ON $database.product_login_attempts TO maas_product_auth_runtime;
CREATE USER IF NOT EXISTS 'maas_runtime'@'%' IDENTIFIED BY '$password';
GRANT maas_kernel_runtime,maas_release_reader,maas_release_history_reader,maas_history_payload_reader,maas_release_operations_runtime,maas_agent_session_runtime,maas_product_auth_runtime TO 'maas_runtime'@'%';
SET DEFAULT ROLE ALL TO 'maas_runtime'@'%';
SQL
then
  echo "Runtime account/default-role provisioning failed; secret-bearing SQL is not logged." >&2
  exit 1
fi
echo "Migrations and explicit runtime roles completed; no existing password or ledger is reset."