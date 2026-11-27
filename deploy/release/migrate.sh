#!/bin/bash
set -euo pipefail
database="${MAAS_INSTALL_DATABASE:-maas}"
[[ "$database" =~ ^[A-Za-z0-9_]+$ ]] || exit 2
mode="${MAAS_INSTALL_PROVISION_ROLES:-1}"
[[ "$mode" == 0 || "$mode" == 1 ]] || exit 2
# Reject existing overgrants/defaults BEFORE provision writes. Missing approved
# grants may be filled in mode1; a precheck never authorizes application startup.
audit=(python3 /app/audit_runtime_privileges.py --config /etc/maas/migration.json --database "$database")
"${audit[@]}" --phase precheck
/maas migrate --config /etc/maas/migration.json
if [[ "$mode" == 1 ]]; then
  for file in release-permissions.sql kernel-permissions.sql controlapi-projections.sql agent-runtime-role.sql product-auth-permissions.sql; do
    sed "s/__MAAS_DATABASE__/$database/g" "/app/sql/$file" |
      mysql --defaults-file=/run/secrets/mysql-client.cnf --no-login-paths
  done
  password="$(cat /run/secrets/maas_runtime_password)"
  [[ "$password" =~ ^[A-Za-z0-9_-]{32,128}$ ]] || exit 2
  if ! mysql --defaults-file=/run/secrets/mysql-client.cnf --no-login-paths >/dev/null 2>/dev/null <<SQL
CREATE USER IF NOT EXISTS 'maas_runtime'@'%' IDENTIFIED BY '$password';
GRANT maas_kernel_runtime,maas_release_reader,maas_agent_session_runtime,maas_product_auth_runtime TO 'maas_runtime'@'%';
SET DEFAULT ROLE maas_kernel_runtime,maas_release_reader,maas_agent_session_runtime,maas_product_auth_runtime TO 'maas_runtime'@'%';
SQL
  then
    echo "Runtime provisioning failed; credential-bearing SQL is not logged." >&2
    exit 1
  fi
else
  echo "Provisioning skipped; existing authorization still requires complete audit."
fi
# Mandatory in BOTH modes. No REVOKE, grant cleanup or external audit receipt.
"${audit[@]}" --phase final
echo "Migrations and one-shot runtime authorization audit completed."
