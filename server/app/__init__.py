from __future__ import annotations

import sys
from pathlib import Path

# Auto-register monorepo `shared/` directory in local dev (Docker copies `whitz_rag` into `/app/whitz_rag`)
_SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
if _SHARED_DIR.is_dir() and str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
