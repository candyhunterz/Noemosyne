"""Write the canonical OpenAPI document deterministically."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in ("apps/api", "packages/domain", "packages/db", "packages/retrieval"):
    sys.path.insert(0, str(ROOT / source))

from noemosyne_api.main import app  # noqa: E402

(ROOT / "openapi.json").write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
