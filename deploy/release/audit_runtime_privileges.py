"""FC-M-AUTH-PRE-1 one-shot MySQL8.4.7 installation audit, not runtime drift detection.

Reads ONLY the existing approved installation/runtime client files and the same
product DSN files. No alternate credentials, receipt input, REVOKE or mysql.*
rights for runtime. Expected object/column grants come from packaged SQL bytes.
"""
import argparse
import configparser
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse

RUNTIME = "maas_runtime"
ROLES = frozenset(("maas_kernel_runtime", "maas_release_reader", "maas_agent_session_runtime", "maas_product_auth_runtime"))
PRINCIPALS = ROLES | {RUNTIME}
META_OBJECTS = frozenset(("release_revisions", "publish_intents", "resource_inventory", "release_operations", "release_history_owners", "retained_release_snapshots", "release_history_retention", "release_history_legacy_audit", "release_management_operations", "release_history_directory", "release_history_projection", "release_history_completeness"))
GLOBAL_FLAGS = ("Select_priv", "Insert_priv", "Update_priv", "Delete_priv", "Create_priv", "Drop_priv", "Reload_priv", "Shutdown_priv", "Process_priv", "File_priv", "Grant_priv", "References_priv", "Index_priv", "Alter_priv", "Show_db_priv", "Super_priv", "Create_tmp_table_priv", "Lock_tables_priv", "Execute_priv", "Repl_slave_priv", "Repl_client_priv", "Create_view_priv", "Show_view_priv", "Create_routine_priv", "Alter_routine_priv", "Create_user_priv", "Event_priv", "Trigger_priv", "Create_tablespace_priv", "Create_role_priv", "Drop_role_priv")
DB_FLAGS = ("Select_priv", "Insert_priv", "Update_priv", "Delete_priv", "Create_priv", "Drop_priv", "Grant_priv", "References_priv", "Index_priv", "Alter_priv", "Create_tmp_table_priv", "Lock_tables_priv", "Create_view_priv", "Show_view_priv", "Create_routine_priv", "Alter_routine_priv", "Execute_priv", "Event_priv", "Trigger_priv")
SQL_FILES = ("kernel-permissions.sql", "release-permissions.sql", "controlapi-projections.sql", "product-auth-permissions.sql")
IDENT = r"`?[A-Za-z_][A-Za-z0-9_]*`?"


class AuditError(Exception):
    def __init__(self, code, **facts):
        self.code, self.facts = code, facts


def split_privileges(value):
    result, start, depth = [], 0, 0
    for index, char in enumerate(value):
        if char == "(": depth += 1
        elif char == ")": depth -= 1
        elif char == "," and depth == 0:
            result.append(value[start:index].strip()); start = index + 1
        if depth < 0: raise AuditError("unsupported_template_syntax")
    if depth: raise AuditError("unsupported_template_syntax")
    return result + [value[start:].strip()]


def privilege(value):
    name = re.sub(r"[^A-Z]", "", value.upper())
    return "GRANTOPTION" if name == "GRANT" else name


def load_policy(sql_dir, database, agent_template=None, source_lock=None):
    if not re.fullmatch(r"[A-Za-z0-9_]+", database): raise AuditError("invalid_database_identifier")
    files = [Path(sql_dir) / name for name in SQL_FILES] + [Path(agent_template) if agent_template else Path(sql_dir) / "agent-runtime-role.sql"]
    try:
        lock = json.loads(Path(source_lock or "/app/build-sources.lock.json").read_text(encoding="utf-8"))
        code = lock["backend"]["sourceCommit"]
        if not re.fullmatch(r"[0-9a-f]{40}", code) or any(lock[c]["sourceCommit"] != code for c in ("console", "deployment")): raise ValueError()
    except (OSError, ValueError, KeyError): raise AuditError("approved_source_lock_unavailable_or_invalid") from None
    grants, hashes = set(), {}
    for file in files:
        try: raw = file.read_bytes()
        except OSError: raise AuditError("template_unavailable", template=file.name) from None
        hashes[file.name] = hashlib.sha256(raw).hexdigest()
        component = "deployment" if file == files[-1] else "backend"
        locked_name = "deploy/agent/session-role.sql" if file == files[-1] else "config/mysql/"+file.name
        if lock[component]["files"].get(locked_name) != hashes[file.name]: raise AuditError("template_source_lock_mismatch", template=file.name)
        source = re.sub(r"--[^\n]*", "", raw.decode("utf-8")).replace("__MAAS_DATABASE__", database)
        for statement in source.split(";"):
            statement = statement.strip()
            if not statement: continue
            if re.fullmatch(r"CREATE\s+ROLE\s+IF\s+NOT\s+EXISTS\s+" + IDENT, statement, re.I): continue
            match = re.fullmatch(r"GRANT\s+(.+?)\s+ON\s+(" + IDENT + r")\.(" + IDENT + r")\s+TO\s+(" + IDENT + r")", statement, re.I | re.S)
            if not match: raise AuditError("unsupported_template_syntax", template=file.name)
            rights, schema, table, role = match.groups()
            schema, table, role = (v.strip("`") for v in (schema, table, role))
            if role == RUNTIME: raise AuditError("template_direct_runtime_grant_not_approved", template=file.name)
            if role not in ROLES: continue
            if schema != database: raise AuditError("template_wrong_database", template=file.name)
            for item in split_privileges(rights):
                rule = re.fullmatch(r"([A-Za-z ]+?)(?:\(([^()]*)\))?", item)
                if not rule: raise AuditError("unsupported_template_syntax", template=file.name)
                right, columns = rule.groups(); right = privilege(right)
                if right not in {"SELECT", "INSERT", "UPDATE", "DELETE", "SHOWVIEW"}: raise AuditError("unapproved_template_privilege", template=file.name)
                if columns is None: grants.add((role, "%", database, table, "", right))
                else:
                    if right == "SHOWVIEW": raise AuditError("unsupported_template_syntax", template=file.name)
                    for column in columns.split(","):
                        if not re.fullmatch(IDENT, column.strip()): raise AuditError("unsupported_template_syntax", template=file.name)
                        grants.add((role, "%", database, table, column.strip().strip("`"), right))
    show = {g[3] for g in grants if g[0] == "maas_release_reader" and g[5] == "SHOWVIEW" and not g[4]}
    if show != META_OBJECTS or any(g[5] == "SHOWVIEW" and g[0] != "maas_release_reader" for g in grants):
        raise AuditError("FC-M-META-1_template_not_exact", missing=sorted(META_OBJECTS-show), extra=sorted(show-META_OBJECTS))
    for name in ("audit_runtime_privileges.py", "migrate.sh"):
        file = Path(__file__).with_name(name)
        if lock["deployment"]["files"].get("deploy/release/"+name) != hashlib.sha256(file.read_bytes()).hexdigest(): raise AuditError("installer_source_lock_mismatch", file=name)
    return {"database": database, "grants": grants, "templateSha256": hashes, "sourceCodeCommit": code,
            "policySha256": hashlib.sha256(json.dumps(sorted(grants), separators=(",", ":")).encode()).hexdigest()}


def client_file(path):
    path = Path(path)
    try:
        if os.name == "posix" and path.stat().st_mode & 0o022: raise AuditError("credential_file_writable")
        raw = path.read_text(encoding="utf-8")
        if re.search(r"^\s*!", raw, re.M): raise AuditError("credential_include_not_supported")
        parser = configparser.ConfigParser(interpolation=None, strict=True, empty_lines_in_values=False)
        parser.read_string(raw)
        if parser.sections() != ["client"] or parser.defaults(): raise AuditError("credential_file_groups_not_supported")
        values = {key.replace("_", "-"): value for key, value in parser["client"].items()}
    except (OSError, ValueError, configparser.Error): raise AuditError("credential_file_unavailable_or_invalid") from None
    allowed = {"host", "port", "user", "password", "protocol", "database", "ssl-mode", "ssl-ca", "ssl-capath", "ssl-cert", "ssl-key", "tls-version", "tls-ciphersuites", "connect-timeout", "default-character-set"}
    if set(values)-allowed: raise AuditError("credential_file_options_not_supported")
    if not all(values.get(k) for k in ("user", "password", "host")): raise AuditError("explicit_existing_credentials_required")
    if any("\n" in value or "\r" in value or "\\" in value or value[:1] in ("'", '"') for key, value in values.items() if key in ("user", "password", "host")):
        raise AuditError("credential_encoding_not_supported")
    if values.get("protocol", "tcp").lower() != "tcp": raise AuditError("only_explicit_tcp_binding_supported")
    return values


def bind_dsn(path, client, database, runtime=False):
    try: text = Path(path).read_text(encoding="utf-8").strip()
    except OSError: raise AuditError("declared_dsn_unavailable") from None
    match = re.fullmatch(r"([^:@/]+):(.*)@tcp\(([^()]+)\)/([^?]+)(?:\?(.*))?", text)
    if not match: raise AuditError("dsn_binding_format_not_supported")
    user, password, address, db, query = match.groups()
    if runtime and user != RUNTIME: raise AuditError("runtime_dsn_principal_not_approved")
    parsed = urllib.parse.urlsplit("//"+address)
    try: host, port = parsed.hostname, parsed.port or 3306
    except ValueError: raise AuditError("dsn_binding_address_invalid") from None
    if not host or parsed.username or parsed.password or parsed.path: raise AuditError("dsn_binding_address_invalid")
    if user != client["user"] or not hmac.compare_digest(password.encode(), client["password"].encode()) or host.lower() != client["host"].strip("[]").lower() or str(port) != client.get("port", "3306") or urllib.parse.unquote(db) != database or client.get("database", database) != database:
        raise AuditError("client_and_declared_dsn_binding_differ")
    params = urllib.parse.parse_qs(query or "", keep_blank_values=True, strict_parsing=True)
    if set(params)-{"parseTime", "loc", "timeout", "readTimeout", "writeTimeout", "tls"}: raise AuditError("dsn_options_not_supported_for_binding")
    if any(len(v) != 1 for v in params.values()): raise AuditError("ambiguous_dsn_options")
    tls = params.get("tls", ["false"])[0]
    if tls == "true":
        if client.get("ssl-mode", "").upper() != "VERIFY_IDENTITY": raise AuditError("verified_tls_client_binding_required")
    elif tls != "false": raise AuditError("custom_or_insecure_tls_binding_not_supported")
    elif client.get("ssl-mode", "DISABLED").upper() != "DISABLED": raise AuditError("tls_client_and_dsn_binding_differ")
    return "VERIFY_IDENTITY" if tls == "true" else "DISABLED"


def queries():
    users = ",".join("'"+name+"'" for name in sorted(PRINCIPALS))
    where = "User IN ("+users+")"
    return [
        ("identity", "SELECT JSON_ARRAY('identity',CURRENT_USER(),DATABASE(),@@GLOBAL.server_uuid,VERSION(),@@GLOBAL.mandatory_roles,@@GLOBAL.activate_all_roles_on_login)"),
        ("accounts", "SELECT JSON_ARRAY('accounts',User,Host,"+",".join(GLOBAL_FLAGS)+") FROM mysql.user WHERE "+where),
        ("schema_grants", "SELECT JSON_ARRAY('schema_grants',User,Host,Db,"+",".join(DB_FLAGS)+") FROM mysql.db WHERE "+where),
        ("table_grants", "SELECT JSON_ARRAY('table_grants',User,Host,Db,Table_name,Table_priv,Column_priv) FROM mysql.tables_priv WHERE "+where),
        ("column_grants", "SELECT JSON_ARRAY('column_grants',User,Host,Db,Table_name,Column_name,Column_priv) FROM mysql.columns_priv WHERE "+where),
        ("dynamic_grants", "SELECT JSON_ARRAY('dynamic_grants',USER,HOST,PRIV,WITH_GRANT_OPTION) FROM mysql.global_grants WHERE USER IN ("+users+")"),
        ("routine_grants", "SELECT JSON_ARRAY('routine_grants',User,Host,Db,Routine_name,Proc_priv) FROM mysql.procs_priv WHERE "+where),
        ("proxy_grants", "SELECT JSON_ARRAY('proxy_grants',User,Host,Proxied_user,Proxied_host,With_grant) FROM mysql.proxies_priv WHERE "+where),
        ("role_edges", "SELECT JSON_ARRAY('role_edges',TO_USER,TO_HOST,FROM_USER,FROM_HOST,WITH_ADMIN_OPTION) FROM mysql.role_edges WHERE TO_USER IN ("+users+")"),
        ("default_roles", "SELECT JSON_ARRAY('default_roles',USER,HOST,DEFAULT_ROLE_USER,DEFAULT_ROLE_HOST) FROM mysql.default_roles WHERE USER IN ("+users+")"),
        ("identity_end", "SELECT JSON_ARRAY('identity_end',CURRENT_USER(),DATABASE(),@@GLOBAL.server_uuid,VERSION(),@@GLOBAL.mandatory_roles,@@GLOBAL.activate_all_roles_on_login)"),
    ]


class MysqlClient:
    def __init__(self, defaults, database, prefix=None, tls_mode="DISABLED"):
        self.defaults, self.database = str(defaults), database
        self.prefix = prefix or ["mysql"]  # prefix injection is internal test plumbing, never a CLI/auth option.
        self.tls_mode = tls_mode

    def collect(self, statements):
        sql = "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;\n" + ";\n".join(q for _, q in statements) + ";\nCOMMIT;\n"
        args = self.prefix + ["--defaults-file="+self.defaults, "--no-login-paths", "--ssl-mode="+self.tls_mode, "--connect-timeout=5", "--default-character-set=utf8mb4", "--batch", "--raw", "--skip-column-names", "--database="+self.database]
        if self.tls_mode == "DISABLED": args.append("--get-server-public-key")
        try: result = subprocess.run(args, input=sql.encode(), capture_output=True, timeout=25)
        except (OSError, subprocess.TimeoutExpired): raise AuditError("audit_connection_or_deadline_failed") from None
        if result.returncode:
            error = re.search(rb"ERROR\s+(\d+)", result.stderr)
            line = re.search(rb"at line\s+(\d+)", result.stderr)
            index = int(line.group(1))-2 if line else -1
            scope = statements[index][0] if 0 <= index < len(statements) else "connection_or_transaction"
            raise AuditError("audit_metadata_unavailable", scope=scope, database=self.database, principals=sorted(PRINCIPALS), mysqlError=int(error.group(1)) if error else None)
        if len(result.stdout) > 4*1024*1024: raise AuditError("audit_metadata_size_exceeded")
        rows = {name: [] for name, _ in statements}
        try:
            for line in result.stdout.decode("utf-8").splitlines():
                row = json.loads(line)
                if not isinstance(row, list) or not row or row[0] not in rows: raise ValueError()
                rows[row[0]].append(row[1:])
        except (ValueError, UnicodeError): raise AuditError("audit_metadata_incomplete_or_invalid") from None
        return rows


def evaluate(policy, rows, allow_missing=False):
    problems = []
    def fail(code, **facts): problems.append({"code": code, **facts})
    identity = rows.get("identity", [])
    if len(identity) != 1 or rows.get("identity_end") != identity: raise AuditError("audit_identity_or_server_state_changed")
    caller, db, server_uuid, version, mandatory, activate = identity[0]
    if db != policy["database"] or not server_uuid or not re.fullmatch(r"8\.4\.7(?:[-+].*)?", version): raise AuditError("unsupported_or_unbound_audit_server")
    if mandatory: fail("mandatory_roles_not_in_approved_install_profile")
    accounts = set()
    for row in rows.get("accounts", []):
        if len(row) != len(GLOBAL_FLAGS)+2: raise AuditError("account_metadata_incomplete")
        user, host, *flags = row
        if user not in PRINCIPALS or host != "%": fail("principal_shadow_or_host_not_approved", principal=user, host=host)
        if (user, host) in accounts: raise AuditError("duplicate_account_metadata")
        accounts.add((user, host))
        for name, value in zip(GLOBAL_FLAGS, flags):
            if value not in ("N", "Y"): raise AuditError("account_metadata_invalid")
            if value == "Y": fail("global_privilege", principal=user, privilege=name)
    if not allow_missing:
        for user in sorted(PRINCIPALS):
            if (user, "%") not in accounts: fail("required_principal_missing", principal=user)
    for row in rows.get("schema_grants", []):
        if len(row) != len(DB_FLAGS)+3: raise AuditError("schema_metadata_incomplete")
        if any(value == "Y" for value in row[3:]): fail("schema_wide_privilege", principal=row[0], schema=row[2])
        if any(value not in ("N", "Y") for value in row[3:]): raise AuditError("schema_metadata_invalid")
    for scope in ("dynamic_grants", "routine_grants", "proxy_grants"):
        if rows.get(scope): fail(scope+"_not_approved", count=len(rows[scope]))
    expected_edges = {(RUNTIME, "%", role, "%", "N") for role in ROLES}
    edges = [tuple(row) for row in rows.get("role_edges", [])]
    defaults = [tuple(row) for row in rows.get("default_roles", [])]
    expected_defaults = {(RUNTIME, "%", role, "%") for role in ROLES}
    if len(set(edges)) != len(edges) or set(edges)-expected_edges: fail("role_edge_or_admin_option_not_approved")
    if len(set(defaults)) != len(defaults) or set(defaults)-expected_defaults: fail("default_or_inherited_role_not_approved")
    if not allow_missing and set(edges) != expected_edges: fail("required_role_edge_missing")
    if not allow_missing and set(defaults) != expected_defaults: fail("required_default_role_missing")
    actual, aggregates, column_union = set(), {}, {}
    for row in rows.get("table_grants", []):
        if len(row) != 6: raise AuditError("table_metadata_incomplete")
        user, host, schema, table, table_priv, column_priv = row; key = (user, host, schema, table)
        if key in aggregates: raise AuditError("duplicate_table_metadata")
        aggregates[key] = {privilege(p) for p in column_priv.split(",") if p}
        for right in table_priv.split(","):
            if right: actual.add(key+("", privilege(right)))
    for row in rows.get("column_grants", []):
        if len(row) != 6: raise AuditError("column_metadata_incomplete")
        user, host, schema, table, column, rights = row; key = (user, host, schema, table)
        for right in rights.split(","):
            if not right: continue
            item = key+(column, privilege(right))
            if item in actual: raise AuditError("duplicate_column_metadata")
            actual.add(item); column_union.setdefault(key, set()).add(privilege(right))
    if any(aggregates.get(key, set()) != column_union.get(key, set()) for key in set(aggregates)|set(column_union)):
        raise AuditError("column_metadata_coverage_inconsistent")
    extra = actual-policy["grants"]; missing = policy["grants"]-actual
    for item in sorted(extra): fail("object_or_column_grant_not_approved", grant=list(item))
    if not allow_missing:
        for item in sorted(missing): fail("required_object_or_column_grant_missing", grant=list(item))
    return {"installationAccount": caller, "database": db, "serverUUID": server_uuid, "serverVersion": version,
            "activateAllRolesOnLogin": bool(activate), "problems": problems, "runtimeExists": (RUNTIME, "%") in accounts}


def authenticate_runtime(client, expected_server):
    rows = client.collect([("runtime", "SELECT JSON_ARRAY('runtime',CURRENT_USER(),DATABASE(),@@GLOBAL.server_uuid,CURRENT_ROLE(),@@proxy_user,VERSION())")])
    if len(rows["runtime"]) != 1: raise AuditError("runtime_identity_unavailable")
    user, db, server, roles, proxy, version = rows["runtime"][0]
    tokens = roles.split(",")
    if any(not re.fullmatch(r"`[a-z0-9_]+`@`%`", token) for token in tokens): raise AuditError("runtime_role_activation_not_approved")
    active = [token.split("`")[1] for token in tokens]
    if user != RUNTIME+"@%" or proxy is not None or db != expected_server["database"] or server != expected_server["serverUUID"] or version != expected_server["serverVersion"] or len(active) != 4 or set(active) != ROLES:
        raise AuditError("runtime_authenticated_identity_or_activation_not_approved")
    return {"currentUser": user, "database": db, "serverUUID": server, "activeRoles": sorted(active), "proxyUsed": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--database", default="maas")
    p.add_argument("--sql-dir", type=Path, default=Path("/app/sql"))
    p.add_argument("--agent-template", type=Path)
    p.add_argument("--source-lock", type=Path, default=Path("/app/build-sources.lock.json"))
    p.add_argument("--installer-defaults-file", type=Path, default=Path("/run/secrets/mysql-client.cnf"))
    p.add_argument("--runtime-defaults-file", type=Path, default=Path("/run/secrets/runtime-client.cnf"))
    p.add_argument("--phase", choices=("precheck", "final"), default="final")
    a = p.parse_args()
    try:
        policy = load_policy(a.sql_dir, a.database, a.agent_template, a.source_lock)
        config = json.loads(a.config.read_text(encoding="utf-8"))
        installer = client_file(a.installer_defaults_file); runtime = client_file(a.runtime_defaults_file)
        installer_tls = bind_dsn(config["mysql"]["migration_dsn_file"], installer, a.database)
        runtime_tls = bind_dsn(config["mysql"]["runtime_dsn_file"], runtime, a.database, runtime=True)
        observed = MysqlClient(a.installer_defaults_file, a.database, tls_mode=installer_tls).collect(queries())
        result = evaluate(policy, observed, allow_missing=a.phase == "precheck")
        result.update(phase=a.phase, sourceCodeCommit=policy["sourceCodeCommit"], templateSha256=policy["templateSha256"], policySha256=policy["policySha256"], scope="one-shot-install-account-role-object-column-audit-not-runtime-drift")
        if result["problems"]:
            result["problemCount"] = len(result["problems"]); result["problems"] = result["problems"][:64]
            result["completeAudit"] = False; print(json.dumps(result)); return 1
        if a.phase == "final":
            result["runtimeIdentity"] = authenticate_runtime(MysqlClient(a.runtime_defaults_file, a.database, tls_mode=runtime_tls), result)
        result.pop("runtimeExists", None); result["completeAudit"] = a.phase == "final"
        print(json.dumps(result)); return 0
    except AuditError as e:
        print(json.dumps({"completeAudit": False, "phase": a.phase, "error": e.code, **e.facts})); return 1
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"completeAudit": False, "phase": a.phase, "error": "audit_input_or_metadata_invalid"})); return 1


if __name__ == "__main__": raise SystemExit(main())
