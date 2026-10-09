"""Load data/seed_users.json into the database: create or update each listed account (name, role, password).

    python3 -m scripts.sync_users            # also deactivates accounts that are not in the file
    python3 -m scripts.sync_users --keep-others

Passwords are stored only as PBKDF2 hashes; changing a password ends that user's sessions. Nothing is printed
except usernames and roles.
"""

import json
import sys

from api import app as server
from infra import auth


def main(keep_others=False):
    users = json.loads(server.USERS_FILE.read_text())["users"]
    c = server.db()
    listed = set()
    for u in users:
        name, role, pw = u["username"].lower().strip(), u["role"], u["password"]
        listed.add(name)
        row = c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()
        if row:
            c.execute("UPDATE users SET name=?, role=?, active=1 WHERE id=?", (u["name"], role, row["id"]))
            auth.set_password(c, row["id"], pw)
            print(f"updated   {name:10s} {role}")
        else:
            auth.create_user(c, name, u["name"], role, pw)
            print(f"created   {name:10s} {role}")
    if not keep_others:
        for r in c.execute("SELECT id, username FROM users WHERE active=1").fetchall():
            if r["username"] not in listed:
                c.execute("UPDATE users SET active=0 WHERE id=?", (r["id"],))
                c.execute("DELETE FROM sessions WHERE user_id=?", (r["id"],))
                print(f"disabled  {r['username']}")
    c.commit()
    c.close()
    server.audit("system", "admin", "users_synced_from_file", str(server.USERS_FILE.name), f"{len(listed)} accounts")


if __name__ == "__main__":
    main(keep_others="--keep-others" in sys.argv)
