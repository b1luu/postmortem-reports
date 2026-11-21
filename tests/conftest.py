import os
import sys
import tempfile
from pathlib import Path

# Make repo importable as 'app.*'
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate tests from the developer's environment and .env, before any `app`
# import (load_dotenv never overrides variables that are already set).
# Heuristic mode, no tracing, and an Ollama URL nothing listens on.
os.environ["POSTMORTEM_MODE"] = "heuristic"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGCHAIN_API_KEY"] = ""
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"

# Per-process temp DB so tests never touch the real one.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["POSTMORTEM_DB_PATH"] = _tmp_db.name
_tmp_db.close()
