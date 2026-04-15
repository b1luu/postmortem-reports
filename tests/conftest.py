import os
import sys
import tempfile
from pathlib import Path

# Make repo importable as 'app.*'
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force heuristic-only path for fast, deterministic tests.
os.environ.setdefault("POSTMORTEM_ENABLE_WRITER_LLM", "")

# Per-process temp DB so tests never touch the real one.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["POSTMORTEM_DB_PATH"] = _tmp_db.name
_tmp_db.close()
