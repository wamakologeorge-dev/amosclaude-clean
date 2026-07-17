#!/usr/bin/env python3
"""
manage_keys.py — admin CLI for the Amosclaud Autonomous server.

This is the ONLY way keys get created or revoked. There is no HTTP
endpoint that issues keys — an admin must have shell access to this
machine to run this script. That's intentional: whoever can call the
agent's API is controlled entirely by whoever can run this file.

Usage:
    python manage_keys.py create "label for this key"
    python manage_keys.py list
    python manage_keys.py revoke <key-id>
"""

import sys
from auth import create_key, list_keys, revoke_key


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "create":
        if len(sys.argv) < 3:
            print("Usage: python manage_keys.py create \"label for this key\"")
            sys.exit(1)
        label = sys.argv[2]
        plaintext = create_key(label)
        print("Key created. This is the ONLY time the plaintext key is shown —")
        print("store it now; it cannot be recovered later.\n")
        print(f"  label : {label}")
        print(f"  key   : {plaintext}\n")
        print("Give this key to whoever should be able to call the agent's API.")
        print("Requests must send it as:  X-Amosclaud-Key: " + plaintext)

    elif command == "list":
        keys = list_keys()
        if not keys:
            print("No keys issued yet.")
            return
        print(f"{'ID':<14}{'LABEL':<30}{'CREATED':<22}{'STATUS'}")
        for k in keys:
            import datetime
            created = datetime.datetime.fromtimestamp(k["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
            status = "REVOKED" if k["revoked"] else "active"
            print(f"{k['id']:<14}{k['label']:<30}{created:<22}{status}")

    elif command == "revoke":
        if len(sys.argv) < 3:
            print("Usage: python manage_keys.py revoke <key-id>")
            sys.exit(1)
        key_id = sys.argv[2]
        if revoke_key(key_id):
            print(f"Key {key_id} revoked.")
        else:
            print(f"No key found with id {key_id}.")
            sys.exit(1)

    else:
        print(f"Unknown command: {command}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
