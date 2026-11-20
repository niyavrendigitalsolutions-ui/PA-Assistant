# Deploy guide

You do these steps because they need your accounts. Keep every secret out of git.

## 1. Code on GitHub

Already pushed to `niyavrendigitalsolutions-ui/PA-Assistant`. Every push to `main` runs the tests, then deploys to Fly.io (once steps 3 and 4 are done).

## 2. Google (Gmail + Calendar), optional

1. console.cloud.google.com: create a project, enable the **Gmail API** and **Google Calendar API**.
2. OAuth consent screen: External, add yourself as a test user. Create an OAuth client of type **Desktop app**.
3. On your computer:
   ```bash
   pip install -r requirements.txt
   export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
   python get_google_token.py
   ```
   Approve in the browser. It prints `GOOGLE_REFRESH_TOKEN=...`.
4. While the consent screen is in "Testing", Google expires the token after 7 days. Publish the app to "In production" (you can stay unverified for personal use) to avoid that.

## 3. Fly.io

```bash
fly auth login
# edit `app = ...` in fly.toml to a unique name, then:
fly launch --no-deploy --copy-config
fly volumes create assistant_data --region bom --size 1

python -c "import secrets; print(secrets.token_urlsafe(32))"   # this is your ASSISTANT_ACCESS_TOKEN

fly secrets set \
  ANTHROPIC_API_KEY=... \
  ASSISTANT_ACCESS_TOKEN=... \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REFRESH_TOKEN=...   # Google lines optional
fly deploy
```

Open `https://<your-fly-app>.fly.dev`, enter your access token when asked, and chat.

## 4. Turn on auto-deploy from GitHub

```bash
fly tokens create deploy      # copy the output
```
GitHub repo > Settings > Secrets and variables > Actions > New secret: `FLY_API_TOKEN`.

From now on every push to `main` runs the tests, then deploys. Pull requests only run tests.

## Troubleshooting

- `fly logs` shows errors. A crash on start means `ASSISTANT_ACCESS_TOKEN` is missing or under 16 characters.
- "Wrong access token" in the page: the token doesn't match the Fly secret. Reload and re-enter it.
- Gmail errors after about a week: the Google token expired (see step 2.4).
