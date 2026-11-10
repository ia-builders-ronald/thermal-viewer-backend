#!/usr/bin/env python3
"""Set a user's role directly in the users table (bootstrap the first admin).

The person must have signed in once so their row exists.

    python scripts/set_role.py --email me@example.com --role admin
    python scripts/set_role.py --sub <cognito-sub> --role admin
"""
import argparse
import json
import os
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from middleware.users import ROLES, UserStore  # noqa: E402

DEFAULT_TABLE = "thermal-viewer-dev-users"
UPDATED_BY = "bootstrap-script"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email")
    who.add_argument("--sub")
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    args = parser.parse_args(argv)

    region = os.environ.get("AWS_REGION", "ap-southeast-1")
    store = UserStore(boto3.resource("dynamodb", region_name=region).Table(args.table),
                      cache_seconds=0)

    if args.sub:
        sub = args.sub
    else:
        wanted = args.email.strip().lower()
        if not wanted:
            print("--email must not be blank.", file=sys.stderr)
            return 1
        matches = [u for u in store.list_users() if (u.get("email") or "").lower() == wanted]
        if not matches:
            print("No user with email %s in %s. Ask them to sign in once first." % (args.email, args.table),
                  file=sys.stderr)
            return 1
        if len(matches) > 1:
            print("More than one user has email %s (subs: %s); use --sub." % (
                args.email, ", ".join(u["sub"] for u in matches)), file=sys.stderr)
            return 1
        sub = matches[0]["sub"]

    try:
        row = store.update(sub, role=args.role, updated_by=UPDATED_BY)
    except KeyError:
        print("No user with sub %s in %s. Ask them to sign in once first." % (sub, args.table),
              file=sys.stderr)
        return 1
    print(json.dumps(row, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
