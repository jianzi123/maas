"""Offline identity plan validation; never reads Secret bodies or contacts MySQL."""
PAYLOAD_ROLE = "maas_history_payload_reader"
EXPECTED = {
    "core": {"maas_kernel_runtime", "maas_release_reader"},
    "publisher": {"maas_release_publisher"},
    "historyReader": {"maas_release_history_reader"},
    "payloadReader": {PAYLOAD_ROLE},
    "operationReader": {"maas_release_operations_runtime"},
}

# Names are fixed by the reviewed candidate, never supplied as arbitrary env.
DATABASE_ENV = {
    "core": "MAAS_MYSQL_DSN",
    "historyReader": "MAAS_HISTORY_READER_DSN",
    "operationReader": "MAAS_OPERATIONS_DSN",
    "payloadReader": "MAAS_HISTORY_PAYLOAD_DSN",
}

def binding_blockers(values, plan, interface):
    problems = []
    refs = values.get("core", {}).get("databaseSecrets", {})
    consumed = interface.get("backend", {}).get("core", {}).get("environmentNames", [])
    for name, variable in DATABASE_ENV.items():
        actual = refs.get(name, {})
        expected = plan.get("connections", {}).get(name, {}).get("secretRef", {})
        if not all(actual.get(k) for k in ("name", "key")) or actual != {k: expected.get(k) for k in ("name", "key")}:
            problems.append("identities." + name + ".envBinding")
        if variable not in consumed:
            problems.append("identities." + name + ".unconsumedVariable")
    return problems

def identity_blockers(plan, namespace):
    problems = []
    if plan.get("productionWiringVerified") is not True:
        problems.append("identities.productionWiring")
    connections = plan.get("connections", {})
    if set(connections) != set(EXPECTED):
        return problems + ["identities.inventory"]
    principals, refs = [], []
    for name, expected in EXPECTED.items():
        c = connections[name]
        if set(c.get("roles", [])) != expected:
            problems.append("identities." + name + ".roles")
        if c.get("bindingStatus") != "verified" or not c.get("grantEvidenceRef"):
            problems.append("identities." + name + ".evidence")
        principal = c.get("principalRef")
        if not principal:
            problems.append("identities." + name + ".principal")
        else:
            principals.append(principal)
        ref = c.get("secretRef", {})
        if set(ref) != {"namespace", "name", "key"} or not all(ref.values()) or ref.get("namespace") != namespace:
            problems.append("identities." + name + ".secretRef")
        else:
            refs.append((ref["namespace"], ref["name"], ref["key"]))
        # These inputs are references only, never raw DSNs or passwords.
        if set(c) - {"roles", "forbiddenRoles", "bindingStatus", "secretRef", "principalRef", "grantEvidenceRef"}:
            problems.append("identities." + name + ".unknownFields")
    if len(set(principals)) != len(principals):
        problems.append("identities.sharedPrincipal")
    if len(set(refs)) != len(refs):
        problems.append("identities.sharedSecretKey")
    return problems
