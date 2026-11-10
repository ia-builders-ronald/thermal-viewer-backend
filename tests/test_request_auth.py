import boto3
import pytest
from flask import Flask, g, jsonify
from moto import mock_aws

from middleware.auth import init_auth, require_auth, require_permission
from middleware.users import UserStore

BLOCKED_MSG = "Your access has been blocked. Contact your administrator."


@pytest.fixture
def table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-1")
        yield ddb.create_table(
            TableName="test-users",
            KeySchema=[{"AttributeName": "sub", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sub", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


@pytest.fixture
def info():
    return {"email": "u@example.com", "name": "U Ser"}


@pytest.fixture
def client(table, auth_config, info):
    store = UserStore(table, cache_seconds=0)
    app = Flask(__name__)
    init_auth(app, config=auth_config, store=store, userinfo_fetcher=lambda c, t: dict(info))

    @app.route("/who")
    @require_auth
    def who():
        return jsonify({k: v for k, v in g.user.items() if k != "access_token"})

    @app.route("/admin")
    @require_auth
    @require_permission("admin_users")
    def admin():
        return jsonify({"ok": True})

    app.test_store = store
    c = app.test_client()
    c.store = store
    return c


def hdr(tok):
    return {"Authorization": "Bearer " + tok}


def test_missing_header_401_unauthenticated(client):
    r = client.get("/who")
    assert r.status_code == 401
    assert r.get_json()["code"] == "unauthenticated"


def test_malformed_header_401(client):
    r = client.get("/who", headers={"Authorization": "Token abc"})
    assert r.status_code == 401 and r.get_json()["code"] == "unauthenticated"


def test_invalid_token_401(client):
    r = client.get("/who", headers=hdr("garbage"))
    assert r.status_code == 401
    assert r.get_json()["code"] == "unauthenticated"


def test_first_request_creates_viewer_row_with_userinfo(client, make_token):
    r = client.get("/who", headers=hdr(make_token()))
    assert r.status_code == 200
    assert r.get_json()["role"] == "viewer"
    row = client.store.get("user-sub-123")
    assert row["email"] == "u@example.com" and row["name"] == "U Ser"
    assert row["username"] == "testuser" and row["role"] == "viewer"


def test_userinfo_failure_still_creates_row(table, auth_config, make_token):
    from flask import Flask
    app = Flask(__name__)
    init_auth(app, config=auth_config, store=UserStore(table, cache_seconds=0),
              userinfo_fetcher=lambda c, t: {"email": None, "name": None})

    @app.route("/api/me")
    @require_auth
    def me():
        return jsonify({"username": g.user["username"], "email": g.user["email"]})

    r = app.test_client().get("/api/me", headers=hdr(make_token()))
    assert r.status_code == 200
    assert r.get_json() == {"username": "testuser", "email": None}
    assert table.get_item(Key={"sub": "user-sub-123"})["Item"]["role"] == "viewer"


def test_blocked_user_403_blocked_code_and_exact_message(client, make_token):
    client.store.get_or_create("user-sub-123", "testuser")
    client.store.update("user-sub-123", blocked=True, updated_by="admin")
    r = client.get("/who", headers=hdr(make_token()))
    assert r.status_code == 403
    assert r.get_json() == {"error": BLOCKED_MSG, "code": "blocked"}


def test_require_permission_forbidden_for_viewer_allowed_for_admin(client, make_token):
    tok = make_token()
    r = client.get("/admin", headers=hdr(tok))
    assert r.status_code == 403 and r.get_json()["code"] == "forbidden"
    client.store.update("user-sub-123", role="admin", updated_by="x")
    assert client.get("/admin", headers=hdr(tok)).status_code == 200


def test_preflight_options_passes_without_token(client):
    r = client.options("/who")
    assert r.status_code == 200
