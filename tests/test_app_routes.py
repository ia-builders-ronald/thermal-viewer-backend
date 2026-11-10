import importlib
import sys

import boto3
import pytest
from moto import mock_aws

AMPLIFY = "https://master.d1aqqm159oe3x8.amplifyapp.com"

ENV = {
    "AWS_REGION": "ap-southeast-1",
    "AWS_DEFAULT_REGION": "ap-southeast-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "COGNITO_USER_POOL_ID": "ap-southeast-1_TESTPOOL",
    "COGNITO_CLIENT_ID": "test-client-id",
    "COGNITO_DOMAIN": "test.auth.ap-southeast-1.amazoncognito.com",
    "USERS_TABLE": "test-users-app",
}


def _import_app():
    sys.modules.pop("app", None)
    return importlib.import_module("app")


@pytest.fixture
def app_module(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with mock_aws():
        boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="test-users-app",
            KeySchema=[{"AttributeName": "sub", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sub", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        mod = _import_app()
        yield mod
    sys.modules.pop("app", None)


def test_every_api_route_requires_auth(app_module):
    client = app_module.app.test_client()
    seen = 0
    for rule in app_module.app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        url = rule.rule
        for arg in rule.arguments:
            url = url.replace("<%s>" % arg, "x")
        for method in rule.methods & {"GET", "POST"}:
            r = client.open(url, method=method)
            assert r.status_code == 401, (method, rule.rule)
            assert r.get_json()["code"] == "unauthenticated"
            seen += 1
    assert seen > 10
    assert client.get("/health").status_code == 200


@pytest.mark.xfail(strict=True, reason="route added in Task 4")
def test_cors_preflight_patch_from_amplify_origin(app_module):
    r = app_module.app.test_client().options(
        "/api/admin/users/x",
        headers={
            "Origin": AMPLIFY,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == AMPLIFY


def test_cors_preflight_get_from_amplify_origin_allows_authorization(app_module):
    r = app_module.app.test_client().options(
        "/api/me",
        headers={
            "Origin": AMPLIFY,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == AMPLIFY


def test_cors_other_origin_not_allowed(app_module):
    r = app_module.app.test_client().options(
        "/api/me",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "Access-Control-Allow-Origin" not in r.headers


def test_app_refuses_to_start_without_config(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("COGNITO_CLIENT_ID")
    with mock_aws():
        with pytest.raises(RuntimeError):
            _import_app()
    sys.modules.pop("app", None)


def test_me_records_last_sign_in_and_returns_permissions(app_module, make_token, auth_config, monkeypatch):
    # app was built from ENV; token must match that config
    from middleware.auth import AuthConfig
    cfg = AuthConfig.from_env()
    ext = app_module.app.extensions["auth"]
    ext["userinfo_fetcher"] = lambda c, t: {"email": "a@b.com", "name": "A B"}
    tok = make_token(iss=cfg.issuer, client_id=cfg.client_id)
    client = app_module.app.test_client()
    r = client.get("/api/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    body = r.get_json()
    assert body == {
        "sub": "user-sub-123", "username": "testuser", "email": "a@b.com",
        "name": "A B", "role": "viewer", "permissions": ["view"],
    }
    row = ext["store"]._table.get_item(Key={"sub": "user-sub-123"})["Item"]
    assert row["last_sign_in"]
