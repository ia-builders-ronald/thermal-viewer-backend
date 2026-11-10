"""Cognito Hosted UI userInfo lookup (best effort)."""
import logging

import requests

logger = logging.getLogger(__name__)


def fetch_userinfo(config, access_token: str) -> dict:
    """Return {"email", "name"} from the userInfo endpoint; Nones on any failure."""
    empty = {"email": None, "name": None}
    try:
        resp = requests.get(
            config.userinfo_url,
            headers={"Authorization": "Bearer " + access_token},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return empty
        return {"email": data.get("email"), "name": data.get("name")}
    except Exception as e:
        logger.warning("userInfo lookup failed: %s", e)
        return empty
