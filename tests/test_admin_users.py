import logging

import boto3
import pytest
from moto import mock_aws

from middleware.cognito_admin import CognitoAdmin
from tests.test_app_routes import app_module  # noqa: F401  (fixture)

ADMIN = "sub-admin"
VIEWER = "sub-viewer"
OTHER_ADMIN = "sub-admin2"


class FailingCognito:
    def disable(self, username):
        raise RuntimeError("cognito down")

    def enable(self, username):
        raise RuntimeError("cognito down")


@pytest.fixture
def env(app_module, make_token):  # noqa: F811
    from middleware.auth import AuthConfig
    cfg = AuthConfig.from_env()
    idp = boto3.client("cognito-idp", region_name="ap-southeast-1")
    pool_id = idp.create_user_pool(PoolName="p")["UserPool"]["Id"]
    for name in ("admin", "viewer", "admin2"):
        idp.admin_create_user(UserPoolId=pool_id, Username=name)
    ext = app_module.app.extensions["auth"]
    ext["cognito_admin"] = CognitoAdmin(idp, pool_id)
    table = ext["store"]._table
    rows = [
        (ADMIN, "admin", "admin", "a@x.com"),
        (VIEWER, "viewer", "viewer", "v@x.com"),
    ]
    for sub, username, role, email in rows:
        table.put_item(Item={"sub": sub, "username": username, "role": role,
                             "blocked": False, "email": email, "created_at": "t"})

    class E:
        pass
    e = E()
    e.app, e.ext, e.idp, e.pool_id, e.table = app_module.app, ext, idp, pool_id, table
    e.client = app_module.app.test_client()
    e.hdr = lambda sub, username: {"Authorization": "Bearer " + make_token(
        iss=cfg.issuer, client_id=cfg.client_id, sub=sub, username=username)}
    e.admin = e.hdr(ADMIN, "admin")
    e.viewer = e.hdr(VIEWER, "viewer")
    e.add_admin2 = lambda: table.put_item(Item={
        "sub": OTHER_ADMIN, "username": "admin2", "role": "admin", "blocked": False,
        "email": "b@x.com", "created_at": "t"})
    return e


def enabled(e, username):
    return e.idp.admin_get_user(UserPoolId=e.pool_id, Username=username)["Enabled"]


def row(e, sub):
    return e.table.get_item(Key={"sub": sub})["Item"]


def test_list_requires_admin(env):
    assert env.client.get("/api/admin/users", headers=env.viewer).status_code == 403
    r = env.client.get("/api/admin/users", headers=env.admin)
    assert r.status_code == 200
    users = r.get_json()["users"]
    assert [u["email"] for u in users] == ["a@x.com", "v@x.com"]
    assert set(users[0]) == {"sub", "username", "email", "name", "role", "blocked",
                             "last_sign_in", "created_at"}


def test_change_role_takes_effect_on_next_request(env):
    r = env.client.patch(f"/api/admin/users/{VIEWER}", json={"role": "monitor"}, headers=env.admin)
    assert r.status_code == 200
    assert r.get_json()["role"] == "monitor"
    me = env.client.get("/api/me", headers=env.viewer)
    assert me.status_code == 200
    assert me.get_json()["role"] == "monitor"


def test_block_disables_cognito_user_and_next_request_403(env):
    r = env.client.patch(f"/api/admin/users/{VIEWER}", json={"blocked": True}, headers=env.admin)
    assert r.status_code == 200 and r.get_json()["blocked"] is True
    assert enabled(env, "viewer") is False
    r = env.client.get("/api/me", headers=env.viewer)
    assert r.status_code == 403 and r.get_json()["code"] == "blocked"


def test_unblock_enables(env):
    env.client.patch(f"/api/admin/users/{VIEWER}", json={"blocked": True}, headers=env.admin)
    r = env.client.patch(f"/api/admin/users/{VIEWER}", json={"blocked": False}, headers=env.admin)
    assert r.status_code == 200 and r.get_json()["blocked"] is False
    assert enabled(env, "viewer") is True
    assert env.client.get("/api/me", headers=env.viewer).status_code == 200


def test_cannot_change_self(env):
    r = env.client.patch(f"/api/admin/users/{ADMIN}", json={"role": "viewer"}, headers=env.admin)
    assert r.status_code == 409 and r.get_json()["code"] == "self"
    r = env.client.patch(f"/api/admin/users/{ADMIN}", json={"role": "admin"}, headers=env.admin)
    assert r.status_code == 409 and r.get_json()["code"] == "self"


def test_demote_admin_succeeds_with_two_admins(env):
    env.add_admin2()
    r = env.client.patch(f"/api/admin/users/{OTHER_ADMIN}", json={"role": "viewer"}, headers=env.admin)
    assert r.status_code == 200 and r.get_json()["role"] == "viewer"


def test_cannot_demote_or_block_last_admin(env):
    # A caller is always an unblocked admin, so the guard only fires when the store
    # reports a single unblocked admin (e.g. a concurrent change); simulate that.
    env.add_admin2()
    env.ext["store"].count_admins = lambda exclude_blocked=True: 1
    for body in ({"role": "viewer"}, {"blocked": True}):
        r = env.client.patch(f"/api/admin/users/{OTHER_ADMIN}", json=body, headers=env.admin)
        assert r.status_code == 409 and r.get_json()["code"] == "last_admin"
    assert row(env, OTHER_ADMIN)["role"] == "admin"
    assert row(env, OTHER_ADMIN)["blocked"] is False
    assert enabled(env, "admin2") is True


def test_unknown_role_400(env):
    r = env.client.patch(f"/api/admin/users/{VIEWER}", json={"role": "root"}, headers=env.admin)
    assert r.status_code == 400 and r.get_json()["code"] == "invalid"


@pytest.mark.parametrize("body", [{}, {"blocked": "yes"}, {"role": 5}, {"foo": 1}])
def test_bad_body_400(env, body):
    r = env.client.patch(f"/api/admin/users/{VIEWER}", json=body, headers=env.admin)
    assert r.status_code == 400 and r.get_json()["code"] == "invalid"


def test_missing_user_404(env):
    r = env.client.patch("/api/admin/users/nope", json={"role": "monitor"}, headers=env.admin)
    assert r.status_code == 404 and r.get_json()["code"] == "not_found"


def test_cognito_failure_rolls_back_502(env):
    env.ext["cognito_admin"] = FailingCognito()
    r = env.client.patch(f"/api/admin/users/{VIEWER}",
                         json={"role": "monitor", "blocked": True}, headers=env.admin)
    assert r.status_code == 502 and r.get_json()["code"] == "cognito"
    after = row(env, VIEWER)
    assert after["role"] == "viewer" and after["blocked"] is False
    assert env.client.get("/api/me", headers=env.viewer).get_json()["role"] == "viewer"


def test_change_is_logged(env, caplog):
    with caplog.at_level(logging.INFO):
        env.client.patch(f"/api/admin/users/{VIEWER}", json={"role": "monitor"}, headers=env.admin)
    assert (f"admin_change actor={ADMIN} target={VIEWER} role=viewer->monitor "
            "blocked=False->False") in caplog.text
