"""One-time helper: run on YOUR computer to get a Google refresh token.

1. In Google Cloud Console: create a project, enable the Gmail API and Google
   Calendar API, configure the OAuth consent screen (add yourself as a test user),
   and create an OAuth client ID of type "Desktop app".
2. export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
3. python get_google_token.py   (a browser opens; approve access)
4. Store the printed token as the GOOGLE_REFRESH_TOKEN secret. Never commit it.
"""
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from google_tools import SCOPES

cid, secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
if not cid or not secret:
    sys.exit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first.")

flow = InstalledAppFlow.from_client_config(
    {"installed": {"client_id": cid, "client_secret": secret,
                   "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                   "token_uri": "https://oauth2.googleapis.com/token",
                   "redirect_uris": ["http://localhost"]}},
    SCOPES,
)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nGOOGLE_REFRESH_TOKEN=" + creds.refresh_token)
