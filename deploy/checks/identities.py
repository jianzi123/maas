"""Offline identity plan validation; never reads Secret bodies or contacts MySQL."""
EXPECTED = {
    "core": {"maas_kernel_runtime", "maas_release_reader"},
    "publisher": {"maas_release_publisher"},
    "historyReader": {"maas_release_history_reader"},
    "payloadReader": {"installation-reviewed-payload-reader"},
    "operationReader": {"installation-reviewed-operation-projection"},
}

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