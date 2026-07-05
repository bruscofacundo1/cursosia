"""Smoke test: auth + read + create + unlink against the real Odoo instance.

Same test that was already validated on 04/07/2026 (all four passed on the
One App Free plan). Re-run any time to check the API is still open.

  python scripts/test_connection.py
"""

import os
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv  # noqa: E402

# Windows consoles often default to cp1252, which can't print ✓/⚠ and crashes.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

url = os.environ["ODOO_URL"].rstrip("/")
db = os.environ["ODOO_DB"]
user = os.environ["ODOO_USER"]
key = os.environ["ODOO_API_KEY"]

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, user, key, {})
print(f"1. authenticate: {'✓ uid=' + str(uid) if uid else '✗ FAILED'}")
if not uid:
    raise SystemExit(1)

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

courses = models.execute_kw(db, uid, key, "slide.channel", "search_read", [[]], {"fields": ["name"], "limit": 5})
print(f"2. read: ✓ {len(courses)} course(s): {[c['name'] for c in courses]}")

test_id = models.execute_kw(db, uid, key, "slide.channel", "create", [{"name": "TEST API - borrar"}])
print(f"3. create: ✓ id={test_id}")

models.execute_kw(db, uid, key, "slide.channel", "unlink", [[test_id]])
print("4. unlink: ✓")

print("\n✓ API fully functional.")
