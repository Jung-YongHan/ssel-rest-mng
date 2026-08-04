"""인증 — CONTRACT.md §2.1.

초대코드 / 첫 가입자 자동 admin / 중복 이메일 / 비밀번호 길이 /
httpOnly 쿠키 왕복 / 권한 분리.
"""

from __future__ import annotations

from app.core.config import settings

COOKIE = settings.cookie_name


# ── 가입 ──────────────────────────────────────────────────────────
def test_register_requires_correct_invite_code(client, register):
    resp = register(client, invite_code="완전히-틀린-코드")
    assert resp.status_code == 403
    assert "초대코드" in resp.json()["detail"]
    # 실패했으므로 쿠키도 없어야 한다
    assert COOKIE not in resp.cookies
    assert client.get("/api/auth/me").status_code == 401


def test_register_sets_cookie_and_returns_user_out(client, register):
    resp = register(client, email="new@test.local", name="신규회원")
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert set(body) == {"id", "email", "name", "role", "is_active", "created_at"}
    assert body["email"] == "new@test.local"
    assert body["name"] == "신규회원"
    assert body["is_active"] is True
    assert "password" not in resp.text and "hash" not in resp.text

    assert COOKIE in resp.cookies
    # 가입만으로 바로 인증된 상태여야 한다
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]


def test_first_user_becomes_admin_second_is_member(client, register):
    first = register(client, email="first@test.local", name="첫번째")
    assert first.status_code == 201
    assert first.json()["role"] == "admin", "첫 가입자는 자동으로 admin (§2.1)"

    second = register(client, email="second@test.local", name="두번째")
    assert second.status_code == 201
    assert second.json()["role"] == "member"

    third = register(client, email="third@test.local", name="세번째")
    assert third.json()["role"] == "member"


def test_duplicate_email_conflicts(client, register):
    assert register(client, email="dup@test.local").status_code == 201
    resp = register(client, email="dup@test.local", name="다른이름")
    assert resp.status_code == 409
    assert resp.json()["detail"]


def test_short_password_is_unprocessable(client, register):
    resp = register(client, email="short@test.local", password="1234567")  # 7자
    assert resp.status_code == 422, "비밀번호 최소 8자 (§2.1)"
    # 8자는 통과해야 한다
    assert register(client, email="ok8@test.local", password="12345678").status_code == 201


def test_register_rejects_invalid_email(client, register):
    resp = register(client, email="이메일아님")
    assert resp.status_code == 422


# ── 로그인 / 로그아웃 / me ─────────────────────────────────────────
def test_login_logout_me_cookie_round_trip(client, register):
    email, password = "round@test.local", "password1234"
    assert register(client, email=email, password=password).status_code == 201

    # 쿠키를 버리면 인증이 끊긴다
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401

    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    assert login.json()["email"] == email
    assert COOKIE in login.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert "message" in logout.json()

    # 로그아웃 후에는 다시 401
    assert client.get("/api/auth/me").status_code == 401


def test_login_with_wrong_password_is_unauthorized(client, register):
    register(client, email="wrongpw@test.local", password="password1234")
    client.cookies.clear()

    resp = client.post(
        "/api/auth/login", json={"email": "wrongpw@test.local", "password": "틀린비밀번호"}
    )
    assert resp.status_code == 401
    assert "이메일 또는 비밀번호" in resp.json()["detail"]


def test_login_with_unknown_email_is_unauthorized(client):
    resp = client.post(
        "/api/auth/login", json={"email": "nobody@test.local", "password": "password1234"}
    )
    assert resp.status_code == 401
    assert "이메일 또는 비밀번호" in resp.json()["detail"]


def test_me_without_cookie_is_unauthorized(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert "로그인" in resp.json()["detail"]


def test_bearer_token_fallback_works(client, register):
    """쿠키를 못 쓰는 스크립트/테스트용 폴백 (§0)."""
    from app.core.security import create_access_token

    user = register(client, email="bearer@test.local").json()
    client.cookies.clear()
    token = create_access_token(user["id"])

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == user["id"]


def test_invalid_token_is_unauthorized(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401


# ── 권한 ──────────────────────────────────────────────────────────
def test_admin_users_is_forbidden_for_member(member_client):
    resp = member_client.get("/api/admin/users")
    assert resp.status_code == 403
    assert "관리자" in resp.json()["detail"]


def test_admin_users_is_allowed_for_admin(admin_client):
    resp = admin_client.get("/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert users[0]["role"] == "admin"


def test_admin_endpoints_require_auth(client):
    for path in ("/api/admin/users", "/api/admin/invite-code"):
        assert client.get(path).status_code == 401, path


def test_admin_cannot_demote_self(admin_client):
    me = admin_client.user
    demote = admin_client.patch(f"/api/admin/users/{me['id']}", json={"role": "member"})
    assert demote.status_code == 400, "마지막 관리자 잠금 방지 (§2.6)"

    deactivate = admin_client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
    assert deactivate.status_code == 400


def test_admin_can_promote_member(admin_client, member_client):
    member_id = member_client.user["id"]
    resp = admin_client.patch(f"/api/admin/users/{member_id}", json={"role": "admin"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_invite_code_endpoint_returns_configured_code(admin_client, invite_code):
    resp = admin_client.get("/api/admin/invite-code")
    assert resp.status_code == 200
    assert resp.json() == {"invite_code": invite_code}


# ── health (인증 불필요) ───────────────────────────────────────────
def test_health_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ocr_enabled"] is False  # 테스트는 OCR_PROVIDER=disabled
    assert body["low_balance_threshold"] == settings.low_balance_threshold
