import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import set_role  # noqa: E402


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        t = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="thermal-viewer-dev-users",
            KeySchema=[{"AttributeName": "sub", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sub", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        t.put_item(Item={"sub": "s1", "username": "ronald", "email": "Ronald@Example.com",
                         "role": "viewer", "blocked": False})
        t.put_item(Item={"sub": "s2", "username": "other", "email": "other@example.com",
                         "role": "viewer", "blocked": False})
        yield t


def test_sets_role_by_email(table, capsys):
    assert set_role.main(["--email", "ronald@example.com", "--role", "admin"]) == 0
    row = table.get_item(Key={"sub": "s1"})["Item"]
    assert row["role"] == "admin"
    assert row["updated_by"] == "bootstrap-script"
    assert table.get_item(Key={"sub": "s2"})["Item"]["role"] == "viewer"
    assert "s1" in capsys.readouterr().out


def test_sets_role_by_sub(table):
    assert set_role.main(["--sub", "s2", "--role", "operator"]) == 0
    assert table.get_item(Key={"sub": "s2"})["Item"]["role"] == "operator"


def test_missing_user_exits_nonzero(table, capsys):
    assert set_role.main(["--email", "nobody@example.com", "--role", "admin"]) == 1
    assert "sign in" in capsys.readouterr().err


def test_ambiguous_email_exits_nonzero(table, capsys):
    table.put_item(Item={"sub": "s3", "username": "dup", "email": "RONALD@example.com",
                         "role": "viewer", "blocked": False})
    assert set_role.main(["--email", "ronald@example.com", "--role", "admin"]) == 1
    assert "More than one" in capsys.readouterr().err
    assert table.get_item(Key={"sub": "s1"})["Item"]["role"] == "viewer"
