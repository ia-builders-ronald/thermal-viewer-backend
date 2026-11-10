import boto3
import pytest
from moto import mock_aws

from middleware.users import ROLES, ROLE_PERMISSIONS, UserStore, permissions_for


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-1")
        t = ddb.create_table(
            TableName="test-users",
            KeySchema=[{"AttributeName": "sub", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sub", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(table, clock):
    return UserStore(table, cache_seconds=5.0, clock=clock)


def test_permissions_map():
    assert ROLES == ("admin", "viewer", "monitor", "operator", "geo_editor", "notes")
    allp = {"view", "admin_users", "monitor_runs", "operate_runs", "edit_geo", "write_notes"}
    assert ROLE_PERMISSIONS["admin"] == allp
    assert ROLE_PERMISSIONS["viewer"] == {"view"}
    assert ROLE_PERMISSIONS["monitor"] == {"view", "monitor_runs"}
    assert ROLE_PERMISSIONS["operator"] == {"view", "monitor_runs", "operate_runs"}
    assert ROLE_PERMISSIONS["geo_editor"] == {"view", "edit_geo"}
    assert ROLE_PERMISSIONS["notes"] == {"view", "write_notes"}
    assert permissions_for("operator") == ["monitor_runs", "operate_runs", "view"]


def test_get_or_create_defaults_to_viewer(store):
    u = store.get_or_create("s1", "alice", email="a@x.com", name="Alice")
    assert u["role"] == "viewer"
    assert u["blocked"] is False
    assert u["username"] == "alice"
    assert u["created_at"].endswith("+00:00") or u["created_at"].endswith("Z")
    assert store.get("s1")["email"] == "a@x.com"


def test_get_or_create_keeps_existing_role(table, store):
    table.put_item(Item={"sub": "s1", "username": "alice", "role": "admin", "blocked": False})
    u = store.get_or_create("s1", "alice")
    assert u["role"] == "admin"


def test_record_sign_in_sets_timestamp_and_profile(store):
    store.get_or_create("s1", "alice")
    u = store.record_sign_in("s1", email="new@x.com", name="New")
    assert u["last_sign_in"]
    assert u["email"] == "new@x.com"
    assert u["name"] == "New"
    assert u["role"] == "viewer"


def test_update_role_and_block(store):
    store.get_or_create("s1", "alice")
    u = store.update("s1", role="operator", blocked=True, updated_by="boss")
    assert u["role"] == "operator"
    assert u["blocked"] is True
    assert u["updated_by"] == "boss"
    assert u["updated_at"]


def test_update_unknown_role_raises(store):
    store.get_or_create("s1", "alice")
    with pytest.raises(ValueError):
        store.update("s1", role="superuser", updated_by="boss")


def test_update_missing_user_raises(store):
    with pytest.raises(KeyError):
        store.update("nope", role="admin", updated_by="boss")


def test_cache_hides_change_until_expiry_then_shows_it(table, store, clock):
    store.get_or_create("s1", "alice")
    assert store.get("s1")["role"] == "viewer"
    table.update_item(
        Key={"sub": "s1"},
        UpdateExpression="SET #r = :r",
        ExpressionAttributeNames={"#r": "role"},
        ExpressionAttributeValues={":r": "admin"},
    )
    assert store.get("s1")["role"] == "viewer"
    clock.now += 6
    assert store.get("s1")["role"] == "admin"


def test_update_invalidates_cache(store):
    store.get_or_create("s1", "alice")
    assert store.get("s1")["role"] == "viewer"
    store.update("s1", role="monitor", updated_by="boss")
    assert store.get("s1")["role"] == "monitor"


def test_list_users_sorted(store):
    store.get_or_create("s1", "zed", email="b@x.com")
    store.get_or_create("s2", "amy", email="a@x.com")
    store.get_or_create("s3", "bob")
    # users without an email sort first (empty string), then by email
    assert [u["sub"] for u in store.list_users()] == ["s3", "s2", "s1"]


def test_count_admins_excludes_blocked(store):
    for s in ("a", "b", "c"):
        store.get_or_create(s, s)
    store.update("a", role="admin", updated_by="x")
    store.update("b", role="admin", blocked=True, updated_by="x")
    assert store.count_admins() == 1
    assert store.count_admins(exclude_blocked=False) == 2
