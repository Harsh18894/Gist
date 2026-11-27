"""Start-time check for the public demo: the copied snapshot and the regenerated events DB are the expected data.

Exits non-zero (so the server does not start) if any hash differs from deploy/snapshot/manifest.json or
the locked events content hash.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data = Path(sys.argv[1])
manifest = json.loads((ROOT / "deploy/snapshot/manifest.json").read_text())
problems = []
for name, info in manifest["files"].items():
    if hashlib.sha256((ROOT / "deploy/snapshot" / name).read_bytes()).hexdigest() != info["sha256"]:
        problems.append(f"committed snapshot {name} does not match its manifest")
    if not (data / name).exists():
        problems.append(f"{name} was not copied")
with sqlite3.connect(f"file:{data / 'gist-events-v1.sqlite3'}?mode=ro", uri=True) as db:
    events = db.execute("SELECT value FROM meta WHERE key = 'content_sha256'").fetchone()[0]
if events != manifest["checks"]["events_content_sha256"]:
    problems.append("regenerated events database differs from the locked content hash")
if problems:
    sys.exit("Runtime check failed: " + "; ".join(problems))
print(f"Runtime data verified: snapshot {manifest['created_at']}, {manifest['checks']['learned_vectors']} learned vectors, "
      f"{manifest['checks']['stored_ai_investigations']} stored AI investigations, events {events[:12]}…")
