"""Phase 2: auth service, through nginx (https://localhost, verified by the local CA)."""
import uuid
from datetime import date

import ssl

import httpx
import jwt
import pytest

from conftest import REPO, psql

CA = str(REPO / "infra" / "certs" / "ca.crt")
CLIENT_PASSWORD = "Cliente#2026"
STAFF_PASSWORD = "Staff#2026"
CORE_AUTH = "host=pg-core.global.local dbname=auth sslmode=verify-full"


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url="https://localhost", verify=ssl.create_default_context(cafile=CA), timeout=15) as client:
        yield client


def login(http, email, password):
    return http.post("/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token(http):
    return login(http, "admin@globalscale.test", STAFF_PASSWORD).json()["access_token"]


@pytest.fixture(scope="module")
def operator_token(http):
    return login(http, "operador@globalscale.test", STAFF_PASSWORD).json()["access_token"]


def new_client_body(**overrides):
    n = uuid.uuid4().hex[:8]
    body = {
        "full_name": "Teste Cliente", "email": f"teste.{n}@cliente.test",
        "phone": f"+3519{int(n, 16) % 10**8:08d}", "password": "Teste#2026",
        "region": "EU", "document_id": f"PT{n}", "birth_date": "1995-06-15",
    }
    body.update(overrides)
    return body


# ---------- JWKS / tokens ----------

def test_jwks_publishes_only_the_public_key(http):
    keys = http.get("/.well-known/jwks.json").json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256" and "d" not in keys[0]


def test_login_returns_rs256_jwt_verifiable_with_jwks(http):
    tokens = login(http, "ana.silva@cliente.test", CLIENT_PASSWORD).json()
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == 900 and tokens["refresh_token"]
    jwk = http.get("/.well-known/jwks.json").json()["keys"][0]
    assert jwt.get_unverified_header(tokens["access_token"])["kid"] == jwk["kid"]
    claims = jwt.decode(tokens["access_token"], jwt.PyJWK(jwk).key, algorithms=["RS256"],
                        audience="global-scale", issuer="auth.global.local")
    assert claims["sub"] == "11111111-0000-4000-8000-000000000001"
    assert claims["role"] == "cliente" and claims["region"] == "EU"
    assert claims["exp"] - claims["iat"] == 900


def test_wrong_password_and_unknown_email_give_the_same_answer(http):
    a = login(http, "ana.silva@cliente.test", "Errada#123")
    b = login(http, "nao.existe@cliente.test", "Errada#123")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "credenciais inválidas"}
    # reset Ana's counter so later runs are not affected
    psql(CORE_AUTH, "UPDATE users SET failed_attempts = 0 WHERE email = 'ana.silva@cliente.test'")


# ---------- register ----------

def test_register_creates_pending_client_with_encrypted_fields(http):
    body = new_client_body()
    r = http.post("/auth/register", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PENDENTE_VERIFICACAO"
    raw = psql(CORE_AUTH, f"SELECT position(convert_to('{body['document_id']}', 'UTF8') IN document_id_enc), "
                          f"length(document_id_enc), left(password_hash, 10) "
                          f"FROM users WHERE id = '{r.json()['id']}'").stdout.strip()
    position, length, hash_prefix = raw.split("|")
    assert position == "0"                                     # plaintext not found in the stored bytes
    assert int(length) == 12 + len(body["document_id"]) + 16   # nonce + ciphertext + GCM tag
    assert hash_prefix == "$argon2id$"


def test_operator_sees_decrypted_document(http, operator_token):
    body = new_client_body()
    user_id = http.post("/auth/register", json=body).json()["id"]
    r = http.get(f"/admin/users/{user_id}", headers=bearer(operator_token))
    assert r.json()["document_id"] == body["document_id"]
    assert r.json()["birth_date"] == body["birth_date"]


def test_register_duplicate_email_is_rejected(http):
    body = new_client_body()
    assert http.post("/auth/register", json=body).status_code == 201
    again = new_client_body(email=body["email"])
    r = http.post("/auth/register", json=again)
    assert r.status_code == 409


def test_register_duplicate_phone_is_rejected(http):
    body = new_client_body()
    http.post("/auth/register", json=body)
    assert http.post("/auth/register", json=new_client_body(phone=body["phone"])).status_code == 409


@pytest.mark.parametrize("field,value", [
    ("password", "fraca"), ("password", "SemDigitos!"), ("region", "AS"),
    ("email", "sem-arroba"), ("phone", "12"),
])
def test_register_validation(http, field, value):
    assert http.post("/auth/register", json=new_client_body(**{field: value})).status_code == 422


def test_register_under_18_is_rejected(http):
    seventeen = date.today().replace(year=date.today().year - 17).isoformat()
    r = http.post("/auth/register", json=new_client_body(birth_date=seventeen))
    assert r.status_code == 422 and "18 anos" in r.text


def test_pending_client_cannot_login(http):
    body = new_client_body()
    http.post("/auth/register", json=body)
    r = login(http, body["email"], body["password"])
    assert r.status_code == 403 and "PENDENTE_VERIFICACAO" in r.text


# ---------- lockout ----------

def test_five_failures_lock_the_account_for_15_minutes(http, admin_token):
    staff = {"full_name": "Operador Teste", "email": f"op.{uuid.uuid4().hex[:8]}@globalscale.test",
             "phone": f"+2588{uuid.uuid4().int % 10**8:08d}", "password": "Teste#2026", "role": "operador"}
    assert http.post("/admin/staff", json=staff, headers=bearer(admin_token)).status_code == 201

    codes = [login(http, staff["email"], "Errada#123").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 423]
    # even the correct password is refused while locked
    r = login(http, staff["email"], staff["password"])
    assert r.status_code == 423 and "bloqueada" in r.text
    minutes = psql(CORE_AUTH, f"SELECT round(extract(epoch FROM locked_until - now()) / 60) "
                              f"FROM users WHERE email = '{staff['email']}'").stdout.strip()
    assert minutes in ("14", "15")


# ---------- refresh / logout ----------

def test_refresh_rotates_and_detects_reuse(http):
    first = login(http, "bruno.costa@cliente.test", CLIENT_PASSWORD).json()
    second = http.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    new = second.json()
    assert new["refresh_token"] != first["refresh_token"]

    # the old token was revoked by the rotation; using it again revokes the whole family
    reuse = http.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and "revogado" in reuse.text
    assert http.post("/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token(http):
    tokens = login(http, "carla.mendes@cliente.test", CLIENT_PASSWORD).json()
    r = http.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]},
                  headers=bearer(tokens["access_token"]))
    assert r.status_code == 204
    assert http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_logout_requires_a_valid_token(http):
    assert http.post("/auth/logout", json={"refresh_token": "x"}).status_code == 401
    assert http.post("/auth/logout", json={"refresh_token": "x"},
                     headers=bearer("abc.def.ghi")).status_code == 401


def test_tampered_token_is_rejected(http):
    token = login(http, "david.smith@cliente.test", CLIENT_PASSWORD).json()["access_token"]
    header, _, signature = token.split(".")
    forged = jwt.utils.base64url_encode(b'{"sub":"x","role":"admin"}').decode()
    r = http.get("/admin/users", headers=bearer(f"{header}.{forged}.{signature}"))
    assert r.status_code == 401


# ---------- roles ----------

def test_client_cannot_create_staff_or_approve_kyc(http):
    token = login(http, "emily.johnson@cliente.test", CLIENT_PASSWORD).json()["access_token"]
    staff = {"full_name": "X Y Z", "email": "x@y.zz", "phone": "+258840009999", "password": "Teste#2026", "role": "admin"}
    assert http.post("/admin/staff", json=staff, headers=bearer(token)).status_code == 403
    assert http.post(f"/admin/users/{uuid.uuid4()}/approve-kyc", headers=bearer(token)).status_code == 403


def test_operator_cannot_create_staff(http, operator_token):
    staff = {"full_name": "X Y Z", "email": "x@y.zz", "phone": "+258840009999", "password": "Teste#2026", "role": "admin"}
    assert http.post("/admin/staff", json=staff, headers=bearer(operator_token)).status_code == 403


def test_operator_lists_pending_users(http, operator_token):
    body = new_client_body()
    user_id = http.post("/auth/register", json=body).json()["id"]
    pending = http.get("/admin/users", params={"status": "PENDENTE_VERIFICACAO"}, headers=bearer(operator_token)).json()
    assert user_id in {u["id"] for u in pending}
    assert all(u["status"] == "PENDENTE_VERIFICACAO" for u in pending)


def test_kyc_without_accounts_service_keeps_user_pending(http, operator_token):
    """Phase 2: the api does not exist yet, so the account cannot be created → 503, user stays pending.
    The full flow (account created in the right shard) is scenario 01, Phase 3."""
    from conftest import run
    api_running = run(["docker", "ps", "-q", "-f", "name=^api-1$"], check=False).stdout.strip()
    if api_running:
        pytest.skip("api a correr: o fluxo completo é testado na Fase 3")
    user_id = http.post("/auth/register", json=new_client_body()).json()["id"]
    r = http.post(f"/admin/users/{user_id}/approve-kyc", headers=bearer(operator_token))
    assert r.status_code == 503 and "KYC não aprovado" in r.text
    status = psql(CORE_AUTH, f"SELECT status FROM users WHERE id = '{user_id}'").stdout.strip()
    assert status == "PENDENTE_VERIFICACAO"


def test_kyc_on_unknown_user_is_404(http, operator_token):
    assert http.post(f"/admin/users/{uuid.uuid4()}/approve-kyc", headers=bearer(operator_token)).status_code == 404


def test_plain_http_is_not_served():
    """Portátil: nada a ouvir na porta 80. Servidor: só um redirecionamento 301 para HTTPS."""
    try:
        r = httpx.get("http://localhost:80/health", timeout=3)
    except httpx.HTTPError:
        return
    assert r.status_code == 301 and r.headers["location"].startswith("https://")
