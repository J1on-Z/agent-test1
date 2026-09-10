"""认证 API 端到端测试：注册/登录/me/刷新/改密/吊销。"""
from tests.conftest import create_user


class TestRegisterLogin:
    async def test_register_login_me(self, client):
        r = await client.post("/api/auth/register", json={"username": "alice", "password": "abc12345"})
        assert r.status_code == 200
        assert r.json()["role"] == "user"

        r = await client.post("/api/auth/login", json={"username": "alice", "password": "abc12345"})
        assert r.status_code == 200
        data = r.json()
        assert data["access_token"] and data["refresh_token"]
        assert data["user"]["username"] == "alice"

        r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        assert r.status_code == 200
        assert r.json()["username"] == "alice"

    async def test_register_duplicate_rejected(self, client, db_session):
        await create_user(db_session, "bob")
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "abc12345"})
        assert r.status_code == 400
        assert r.json()["code"] == "username_taken"

    async def test_wrong_password_rejected(self, client, db_session):
        await create_user(db_session, "carol")
        r = await client.post("/api/auth/login", json={"username": "carol", "password": "wrong12345"})
        assert r.status_code == 401

    async def test_me_without_token_rejected(self, client):
        r = await client.get("/api/auth/me")
        assert r.status_code == 401


class TestRefreshAndLogout:
    async def test_refresh_rotation(self, client, db_session):
        await create_user(db_session, "dave")
        login = (await client.post("/api/auth/login", json={"username": "dave", "password": "test123456"})).json()

        # 旧 refresh 换新对（refresh token 含唯一 jti，必然不同；access 同秒签发可能相同）
        r = await client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 200
        new_pair = r.json()
        assert new_pair["refresh_token"] != login["refresh_token"]

        # 旧 refresh 已被吊销（rotation 防重放）
        r = await client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 401

    async def test_logout_revokes_refresh(self, client, db_session):
        await create_user(db_session, "erin")
        login = (await client.post("/api/auth/login", json={"username": "erin", "password": "test123456"})).json()
        r = await client.post("/api/auth/logout", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 200
        r = await client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 401


class TestChangePassword:
    async def test_change_password_flow(self, client, db_session):
        await create_user(db_session, "frank")
        login = (await client.post("/api/auth/login", json={"username": "frank", "password": "test123456"})).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        # 旧密码错误 → 拒绝
        r = await client.post(
            "/api/auth/change-password",
            json={"old_password": "bad123456", "new_password": "newpass123"},
            headers=headers,
        )
        assert r.status_code == 400

        # 改密成功
        r = await client.post(
            "/api/auth/change-password",
            json={"old_password": "test123456", "new_password": "newpass123"},
            headers=headers,
        )
        assert r.status_code == 200

        # 旧密码登录失败，新密码成功
        r = await client.post("/api/auth/login", json={"username": "frank", "password": "test123456"})
        assert r.status_code == 401
        r = await client.post("/api/auth/login", json={"username": "frank", "password": "newpass123"})
        assert r.status_code == 200

        # 改密后旧 refresh 全部吊销
        r = await client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
        assert r.status_code == 401

    async def test_admin_role_survives_login(self, client, db_session):
        await create_user(db_session, "root", role="admin")
        login = (await client.post("/api/auth/login", json={"username": "root", "password": "test123456"})).json()
        assert login["user"]["role"] == "admin"
