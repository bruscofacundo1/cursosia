"""Introspect the eLearning models on the REAL instance (saas-19.3).

Run this FIRST, then fix every 'VERIFY' comment in pipeline/loader.py using the
output. Saves full output to scripts/fields_output.json.

  python scripts/fields_get.py
"""

import json
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

MODELS = ["slide.channel", "slide.slide", "slide.question", "slide.answer"]
ATTRS = ["string", "type", "required", "selection", "relation"]

url = os.environ["ODOO_URL"].rstrip("/")
db = os.environ["ODOO_DB"]
user = os.environ["ODOO_USER"]
key = os.environ["ODOO_API_KEY"]

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, user, key, {})
if not uid:
    raise SystemExit("Authentication failed — check .env")
print(f"✓ Authenticated (uid {uid}). Server: {common.version().get('server_version')}")

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

output = {}
for model in MODELS:
    fields = models.execute_kw(db, uid, key, model, "fields_get", [], {"attributes": ATTRS})
    output[model] = fields
    print(f"\n=== {model} ({len(fields)} fields) ===")
    for name in sorted(fields):
        f = fields[name]
        sel = f" selection={f['selection']}" if f.get("selection") else ""
        rel = f" -> {f['relation']}" if f.get("relation") else ""
        req = " REQUIRED" if f.get("required") else ""
        print(f"  {name:32} {f['type']:12}{req}{rel}{sel}")

out_path = Path(__file__).parent / "fields_output.json"
out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n✓ Full output saved to {out_path}")
