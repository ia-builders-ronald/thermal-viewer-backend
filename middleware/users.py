"""Users table store (DynamoDB) and role -> permission map."""
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from botocore.exceptions import ClientError

ROLES = ("admin", "viewer", "monitor", "operator", "geo_editor", "notes")
DEFAULT_ROLE = "viewer"

_ALL_PERMISSIONS = frozenset(
    {"view", "admin_users", "monitor_runs", "operate_runs", "edit_geo", "write_notes"}
)

ROLE_PERMISSIONS = {
    "admin": _ALL_PERMISSIONS,
    "viewer": frozenset({"view"}),
    "monitor": frozenset({"view", "monitor_runs"}),
    "operator": frozenset({"view", "monitor_runs", "operate_runs"}),
    "geo_editor": frozenset({"view", "edit_geo"}),
    "notes": frozenset({"view", "write_notes"}),
}


def permissions_for(role: str) -> list:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserStore:
    def __init__(self, table, cache_seconds: float = 5.0, clock: Callable[[], float] = time.time):
        self._table = table
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._cache: Dict[str, tuple] = {}

    def invalidate(self, sub: str) -> None:
        self._cache.pop(sub, None)

    def get(self, sub: str) -> Optional[dict]:
        hit = self._cache.get(sub)
        if hit and self._clock() - hit[0] < self._cache_seconds:
            return hit[1]
        item = self._table.get_item(Key={"sub": sub}).get("Item")
        if item is not None:
            self._cache[sub] = (self._clock(), item)
        else:
            self._cache.pop(sub, None)
        return item

    def get_or_create(self, sub: str, username: str, email: Optional[str] = None,
                      name: Optional[str] = None) -> dict:
        existing = self.get(sub)
        if existing is not None:
            return existing
        item = {
            "sub": sub,
            "username": username,
            "role": DEFAULT_ROLE,
            "blocked": False,
            "created_at": _now_iso(),
        }
        if email:
            item["email"] = email
        if name:
            item["name"] = name
        try:
            self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(#s)",
                ExpressionAttributeNames={"#s": "sub"},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            self.invalidate(sub)
            return self.get(sub)
        self.invalidate(sub)
        return item

    def record_sign_in(self, sub: str, email: Optional[str] = None,
                       name: Optional[str] = None) -> dict:
        sets = ["last_sign_in = :t"]
        values = {":t": _now_iso()}
        if email:
            sets.append("email = :e")
            values[":e"] = email
        if name:
            sets.append("#n = :n")
            values[":n"] = name
        kwargs = {}
        if name:
            kwargs["ExpressionAttributeNames"] = {"#n": "name"}
        resp = self._table.update_item(
            Key={"sub": sub},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
            **kwargs,
        )
        self.invalidate(sub)
        return resp["Attributes"]

    def list_users(self) -> List[dict]:
        items: List[dict] = []
        kwargs: dict = {}
        while True:
            resp = self._table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        items.sort(key=lambda u: (u.get("email") or "", u.get("username") or ""))
        return items

    def update(self, sub: str, *, role: Optional[str] = None, blocked: Optional[bool] = None,
               updated_by: str) -> dict:
        if role is not None and role not in ROLES:
            raise ValueError("unknown role: %r" % (role,))
        sets = ["updated_by = :ub", "updated_at = :ua"]
        values = {":ub": updated_by, ":ua": _now_iso()}
        names = {}
        if role is not None:
            sets.append("#r = :r")
            values[":r"] = role
            names["#r"] = "role"
        if blocked is not None:
            sets.append("blocked = :b")
            values[":b"] = bool(blocked)
        names["#s"] = "sub"
        kwargs = {"ExpressionAttributeNames": names}
        try:
            resp = self._table.update_item(
                Key={"sub": sub},
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression="attribute_exists(#s)",
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
                **kwargs,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise KeyError(sub)
            raise
        self.invalidate(sub)
        return resp["Attributes"]

    def count_admins(self, exclude_blocked: bool = True) -> int:
        return sum(
            1 for u in self.list_users()
            if u.get("role") == "admin" and not (exclude_blocked and u.get("blocked"))
        )
