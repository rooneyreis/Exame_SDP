"""Role-Based Access Control: the single source of truth for who may do what.

The JWT only carries the ROLE (signed by auth, cannot be changed by the user). The
permissions are derived HERE, on the server, at every request — never trusted from the
client. Each endpoint declares the permission it needs with require_permission(...).
"""

# permission -> description (shown in the admin "Perfis e permissões" page)
PERMISSIONS = {
    # client self-service
    "accounts:read:own": "Consultar as próprias contas",
    "transfers:create:own": "Transferir a partir das próprias contas",
    "transfers:read:own": "Consultar as próprias transferências",
    "beneficiaries:manage:own": "Gerir os próprios beneficiários",
    "fx:read": "Consultar taxas de câmbio",
    "accounts:request:own": "Pedir a abertura ou o encerramento de contas próprias",
    # bank operations
    "accounts:read:any": "Consultar qualquer conta e extrato",
    "accounts:cash": "Registar depósitos e levantamentos",
    "accounts:manage": "Alterar limites e estado das contas",
    "transfers:read:any": "Consultar todas as transferências",
    "transfer_requests:create": "Registar transferências em nome de clientes",
    "transfer_requests:read": "Consultar pedidos de transferência",
    "transfer_requests:decide": "Aprovar ou rejeitar pedidos de transferência",
    "beneficiaries:read:any": "Consultar beneficiários de qualquer cliente",
    "beneficiaries:manage:any": "Gerir beneficiários de qualquer cliente",
    "kyc:approve": "Aprovar a abertura de contas (KYC)",
    "account_requests:read": "Consultar pedidos de abertura e encerramento de contas",
    "account_requests:decide": "Aprovar ou rejeitar pedidos de abertura e encerramento de contas",
    "accounts:create:direct": "Abrir contas para clientes ao balcão",
    # users and configuration
    "users:read": "Consultar utilizadores",
    "users:read:sensitive": "Ver dados pessoais decifrados (documento, nascimento)",
    "users:manage": "Criar, editar, bloquear e desativar utilizadores e alterar perfis",
    "settings:read": "Consultar limites institucionais",
    "settings:manage": "Configurar limites de transferências",
    # oversight
    "audit:read": "Consultar registos de auditoria, segurança e consistência",
    "reports:read": "Consultar volumes financeiros e relatórios",
    "system:status": "Monitorizar servidores, nós e bases de dados",
    "system:chaos": "Simular falhas (demonstração)",
    # internal
    "accounts:create:internal": "Criar contas após KYC (serviço auth)",
}

ROLES = {
    "cliente": {
        "accounts:read:own", "transfers:create:own", "transfers:read:own", "beneficiaries:manage:own", "fx:read",
        "accounts:request:own",
    },
    "operador": {
        "accounts:read:any", "accounts:cash", "transfers:read:any", "transfer_requests:create",
        "transfer_requests:read", "beneficiaries:read:any", "beneficiaries:manage:any", "kyc:approve",
        "users:read", "users:read:sensitive", "settings:read", "fx:read",
        "account_requests:read", "account_requests:decide", "accounts:create:direct",
    },
    "auditor": {   # read-only by construction: no create/manage/decide permission
        "accounts:read:any", "transfers:read:any", "transfer_requests:read", "beneficiaries:read:any",
        "users:read", "settings:read", "audit:read", "reports:read", "system:status", "fx:read",
        "account_requests:read",
    },
    "admin": {
        "accounts:read:any", "accounts:manage", "transfers:read:any", "transfer_requests:read",
        "transfer_requests:decide", "beneficiaries:read:any", "beneficiaries:manage:any", "users:read",
        "users:read:sensitive", "users:manage", "settings:read", "settings:manage", "audit:read",
        "reports:read", "system:status", "system:chaos", "fx:read", "account_requests:read",
    },
    "service": {"accounts:create:internal"},
}

STAFF_ROLES = ("operador", "auditor", "admin")   # the only roles an administrator can assign


def permissions_of(role: str | None) -> set[str]:
    return ROLES.get(role or "", set())


def has_permission(role: str | None, permission: str) -> bool:
    return permission in permissions_of(role)


def matrix() -> dict:
    """{role: [permissions]} + descriptions, for the admin interface."""
    return {"permissions": PERMISSIONS,
            "roles": {r: sorted(p) for r, p in ROLES.items() if r != "service"}}
