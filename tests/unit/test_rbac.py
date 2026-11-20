"""RBAC matrix (common/rbac.py): the rules the backend applies to every request."""
from common.rbac import PERMISSIONS, ROLES, STAFF_ROLES, has_permission, matrix

WRITE_PERMISSIONS = {p for p in PERMISSIONS if any(w in p for w in (":create", ":manage", ":decide", ":cash", ":approve", "chaos"))}


def test_every_role_permission_is_defined():
    for role, perms in ROLES.items():
        assert perms <= PERMISSIONS.keys(), role


def test_auditor_is_strictly_read_only():
    assert not (ROLES["auditor"] & WRITE_PERMISSIONS)
    assert has_permission("auditor", "audit:read") and has_permission("auditor", "transfers:read:any")


def test_operator_processes_but_does_not_administer():
    for p in ("transfer_requests:create", "accounts:cash", "beneficiaries:manage:any", "kyc:approve"):
        assert has_permission("operador", p)
    for p in ("users:manage", "settings:manage", "transfer_requests:decide", "accounts:manage", "audit:read"):
        assert not has_permission("operador", p)


def test_admin_administers_and_approves_but_does_not_originate_money_movements():
    for p in ("users:manage", "settings:manage", "transfer_requests:decide", "accounts:manage", "system:status"):
        assert has_permission("admin", p)
    # segregação de funções: quem aprova não regista transferências nem mexe em caixa
    assert not has_permission("admin", "transfer_requests:create")
    assert not has_permission("admin", "accounts:cash")


def test_client_only_has_own_scope():
    assert all(p.endswith(":own") or p == "fx:read" for p in ROLES["cliente"])


def test_unknown_or_missing_role_has_nothing():
    assert not has_permission(None, "accounts:read:own")
    assert not has_permission("superuser", "users:manage")


def test_assignable_roles_never_include_client_or_service():
    assert set(STAFF_ROLES) == {"operador", "auditor", "admin"}
    assert "service" not in matrix()["roles"]
