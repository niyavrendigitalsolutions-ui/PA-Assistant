import os
import sys
import tempfile
from pathlib import Path

# Settings must exist before the modules are imported.
os.environ["ASSISTANT_DATA_DIR"] = tempfile.mkdtemp()
os.environ["ASSISTANT_TZ"] = "Asia/Kolkata"
os.environ["ASSISTANT_ACCESS_TOKEN"] = "test-access-token-1234"
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
