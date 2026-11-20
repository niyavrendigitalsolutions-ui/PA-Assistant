# Deploy guide

You do these steps because they need your accounts. Keep every secret out of git.

## 1. Get the code onto GitHub

```bash
git remote add origin https://github.com/<you>/personal-assistant.git   # a PRIVATE repo
git push -u origin main
```
Or: `gh auth login` then `gh repo create personal-assistant --private --source . --push`

## 2. Meta WhatsApp Cloud API

1. developers.facebook.com > Create app > type **Business** > add the **WhatsApp** product.
2. WhatsApp > API setup: note the **Phone number ID**. Add your own number as a recipient and verify it.
3. For a token that doesn't expire: Business settings > System users > create one > add the app > generate a token with `whatsapp_business_messaging` and `whatsapp_business_management`. This is `WHATSAPP_TOKEN`.
4. App settings > Basic: copy the **App secret** (`WHATSAPP_APP_SECRET`).
5. Invent a long random string for `WHATSAPP_VERIFY_TOKEN`.

## 3. Google (Gmail + Calendar), optional

1. console.cloud.google.com: create a project, enable the **Gmail API** and **Google Calendar API**.
2. OAuth consent screen: External, add yourself as a test user. Create an OAuth client of type **Desktop app**.
3. On your computer:
   ```bash
   pip install -r requirements.txt
   export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
   python get_google_token.py
   ```
   Approve in the browser. It prints `GOOGLE_REFRESH_TOKEN=...`.
4. Note: while the consent screen is in "Testing", Google expires the token after 7 days. Publish the app to "In production" (you can stay unverified for personal use) to avoid that.

## 4. Fly.io

```bash
fly auth login
# edit `app = ...` in fly.toml to a unique name, then:
fly launch --no-deploy --copy-config
fly volumes create assistant_data --region bom --size 1
fly secrets set \
  ANTHROPIC_API_KEY=... \
  WHATSAPP_TOKEN=... WHATSAPP_PHONE_NUMBER_ID=... \
  WHATSAPP_VERIFY_TOKEN=... WHATSAPP_APP_SECRET=... \
  OWNER_WHATSAPP=919876543210 \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... GOOGLE_REFRESH_TOKEN=...
fly deploy
```

## 5. Connect WhatsApp to your app

In the Meta dashboard: WhatsApp > Configuration > Webhook:
- Callback URL: `https://<your-fly-app>.fly.dev/webhook`
- Verify token: your `WHATSAPP_VERIFY_TOKEN`
- Subscribe to the **messages** field.

Send "hi" from your phone to the WhatsApp number.

## 6. Turn on auto-deploy from GitHub

```bash
fly tokens create deploy      # copy the output
```
GitHub repo > Settings > Secrets and variables > Actions > New secret: `FLY_API_TOKEN`.

From now on every push to `main` runs the tests, then deploys. Pull requests only run tests.

## Troubleshooting

- `fly logs` shows errors. A crash on start means a secret is missing (the app lists which).
- No reply: check the webhook is subscribed to `messages`, and that `OWNER_WHATSAPP` matches your number (digits only, with country code).
- 403 on webhook: `WHATSAPP_APP_SECRET` is wrong.
- Gmail errors after about a week: the Google token expired (see step 3.4).
