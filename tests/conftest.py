import os
import sys
import tempfile
from pathlib import Path

# Settings must exist before the modules are imported.
os.environ["ASSISTANT_DATA_DIR"] = tempfile.mkdtemp()
os.environ["ASSISTANT_TZ"] = "Asia/Kolkata"
os.environ.update(
    WHATSAPP_TOKEN="t", WHATSAPP_PHONE_NUMBER_ID="123", WHATSAPP_VERIFY_TOKEN="verify-me",
    WHATSAPP_APP_SECRET="appsecret", OWNER_WHATSAPP="+91 98765 43210",
)
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
