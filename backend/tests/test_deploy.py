"""Phase 5.3 deployment configuration: snapshot integrity, no secrets in config, public-by-default start."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRET_KEYS = {"OPENAI_API_KEY", "GIST_PUBLIC_AI_ACCESS_CODE", "GIST_CORS_ORIGIN"}


def test_snapshot_matches_manifest_and_passed_its_checks():
    manifest = json.loads((ROOT / "deploy/snapshot/manifest.json").read_text())
    for name, info in manifest["files"].items():
        assert hashlib.sha256((ROOT / "deploy/snapshot" / name).read_bytes()).hexdigest() == info["sha256"], name
    checks = manifest["checks"]
    assert checks["dataset_version"] == "v2" and checks["learned_vectors"] == 536 and checks["privacy_scan"] == "clean"
    lock = json.loads((ROOT / "evals/phase44/lock.json").read_text())["fingerprint"]
    assert checks["events_content_sha256"] == lock["events_content_sha256"]


def test_render_config_holds_no_secret_values():
    text = (ROOT / "render.yaml").read_text()
    blocks = re.findall(r"- key: (\w+)[^\n]*\n\s+(value|sync): ([^\n#]+)", text)
    seen = {key: (kind, value.strip()) for key, kind, value in blocks}
    for key in SECRET_KEYS:
        assert seen[key] == ("sync", "false"), key
    assert seen["GIST_PUBLIC_MODE"] == ("value", '"true"')
    assert seen["GIST_PUBLIC_AI"] == ("value", '"false"') and seen["GIST_ENABLE_PAID_API"] == ("value", '"false"')
    assert not re.search(r"sk-[A-Za-z0-9_-]{16,}", text)


def test_start_script_is_public_by_default_and_verifies_data():
    script = (ROOT / "deploy/render-start.sh").read_text()
    assert 'GIST_PUBLIC_MODE="${GIST_PUBLIC_MODE:-true}"' in script
    assert "verify_runtime.py" in script and "set -euo pipefail" in script
    assert "--no-answer-key" in script            # the server never writes the answer key


def test_frontend_declares_node_20():
    assert json.loads((ROOT / "frontend/package.json").read_text())["engines"]["node"].startswith(">=20")
