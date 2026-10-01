# DailyBasket demo and login guide

Use this guide to run a private DailyBasket demo, create an account, and explain the inventory and reminder flow. The app has no preset account: each demonstrator registers their own email and password.

## Run the local demo on Windows

Open PowerShell in the project folder, then create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Use a disposable database for a demo. This keeps demo data separate from the default `dailybasket.db` file. The next two settings apply only to the PowerShell window where they are entered:

```powershell
$env:DAILYBASKET_DB = "$PWD\dailybasket-demo.db"
$env:DAILYBASKET_DEV_MODE = "1"
python -m streamlit run app.py
```

Open the local address printed by Streamlit, normally [http://localhost:8501](http://localhost:8501). Stop the server with `Ctrl+C`. To restart it, activate `.venv` again if needed, set the same two environment variables, and rerun `python -m streamlit run app.py`.

`DAILYBASKET_DEV_MODE=1` is deliberately for local demonstrations only. It displays a verification token in the app in place of sending it by email. Do not use it in a hosted deployment.

## Create an account and use the login window

At the first screen, the login window has three tabs: **Sign in**, **Register**, and **Verify email**.

1. Open **Register** and enter **Email** and **Password (8+ characters)**.
2. Select **Create account**.
3. Copy the token from the development-only notice when local demo mode is enabled. With SMTP configured and development mode disabled, retrieve the token from the verification email instead.
4. Open **Verify email**, paste it into **Verification token**, and select **Verify email**.
5. Open **Sign in**, enter the registered email and password, and select **Sign in**.

Returning users sign in from the **Sign in** tab. After sign-in, use **Sign out** in the sidebar to end the session. If the original verification token is unavailable, use **Resend verification** on the Verify email tab. A resend replaces the old token, so only the newest token will work.

The current MVP allows an unverified account to sign in, but `worker.py` does not send reminder email for that account until it is verified. There are no preset credentials, password-reset flow, or Google sign-in option.

## Five-minute grocery walkthrough

1. On **Shopping list**, add `Spinach`, quantity `1`, unit `kg`.
2. Select **Buy → inventory** once. The shopping entry becomes checked and adds one inventory batch.
3. Open **Dashboard** to see the product and active-batch counts.
4. Open **Inventory**. The purchase action defaults the item to the `vegetable` category, `refrigerated` storage, and today’s purchase date. The app estimates a vegetable expiry date from the user’s freshness rules.
5. Open **Details and edit: Spinach**, set **Override expiry** to today or tomorrow, then select **Save batch**. Under **Save product details**, set **Expected use per week** to `0.5` and **Use-rate unit** to `kg`, then select **Save product details**.
6. Return to **Dashboard** to see the expiring-product alert and possible surplus calculation for the 1 kg batch. Select **Use 1 kg** there, or **Consume 1** in Inventory, to record consumption.

Every click of **Buy → inventory** adds another batch. Use it once during this walkthrough unless the goal is to demonstrate increased stock and a possible surplus alert.

## Daily reminder email in a local demo

The Streamlit app serves the interface; reminders are sent by the independent `worker.py` process. For a real email demonstration, configure the same database and SMTP values for both processes, leave the user’s email reminder unpaused, and run the worker after the user’s configured local reminder time:

```powershell
$env:DAILYBASKET_DB = "$PWD\dailybasket-demo.db"
$env:SMTP_HOST = "smtp.example.com"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "your-user"
$env:SMTP_PASSWORD = "your-password"
$env:SMTP_FROM = "dailybasket@example.com"
$env:DASHBOARD_URL = "http://localhost:8501"
python worker.py
```

The account must be verified. `worker.py` checks verified, unpaused users whose configured local time is due; it records one successful delivery per user and local calendar day. `DAILYBASKET_DEV_MODE` only displays verification tokens. It does not simulate or send daily reminders.

For repeated reminders, schedule `python worker.py` outside Streamlit, such as every five minutes with Windows Task Scheduler. Ensure the scheduled task receives the same `DAILYBASKET_DB` and SMTP environment settings.

## Deploy a UI demo on Streamlit Community Cloud

Before pushing, confirm Git excludes `dailybasket*.db`, SQLite journal and WAL files, `.streamlit/secrets.toml`, `.env` files, `.venv`, `__pycache__`, and `.pytest_cache`.

1. Push the project to a GitHub repository. Confirm the repository includes `app.py` as the entrypoint plus `requirements.txt`, `schema.sql`, and `dailybasket.py`.
2. In Community Cloud, create an app from that repository, select the branch to deploy, and select `app.py` as the main file. Choose Python 3.12 for this demo; a generic local `python` command can use a different installed version.
3. In the deployed app’s **Advanced settings**, add SMTP values as root-level secrets. For example:

   ```toml
   SMTP_HOST = "smtp.example.com"
   SMTP_PORT = "587"
   SMTP_USER = "your-user"
   SMTP_PASSWORD = "your-password"
   SMTP_FROM = "dailybasket@example.com"
   DASHBOARD_URL = "https://your-app.streamlit.app"
   ```

   Keep these at the root of the TOML file so Streamlit exposes them as environment variables for the current SMTP-based implementation. Do not set `DAILYBASKET_DEV_MODE` in Cloud. Never commit SMTP credentials, hosted secrets, or a SQLite database to Git.
4. Deploy, register through the public URL, and verify the mailbox token before demonstrating the app.

See Streamlit’s official documentation for [deploying a Community Cloud app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [managing secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management), and [connecting to data](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).

Community Cloud’s local SQLite file is not durable application storage. Also, `worker.py` is an independent process and cannot access the Cloud app’s database merely by using the same filename. A hosted end-to-end email demo needs a shared persistent database plus an external scheduler or supporting deployment for the worker. This project does not yet include that infrastructure.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Account creation says verification email is unavailable | Set `DAILYBASKET_DEV_MODE=1` for a local demonstration, or supply valid `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT`, and `SMTP_TIMEOUT`. |
| SMTP send fails | Check the host, port, username, password, sender address, and the provider’s TLS or app-password requirements. The registration or pending email change is rolled back when sending fails. |
| Verification token is rejected | Paste the token that was sent for the account you intend to verify. Used or replaced tokens fail; use the newest token after a resend. |
| Sign in says “Invalid email or password” | Use the registered email and its password. There are no preset credentials or password-reset flow in this MVP; register a new account if you do not have a usable login. |
| No reminder email arrives | Confirm that the account is verified, reminders are not paused in Settings, the configured IANA time zone and reminder time are due, the worker is running, and it has the same database and SMTP settings as the app. |
| Reminder time is unexpected | In Settings, use an IANA time zone such as `Asia/Kolkata`, then save it before running the worker. |
| The app cannot be reached after restart | Reactivate `.venv`, reset the demo environment variables in the new PowerShell session, rerun Streamlit, and use the newly printed localhost URL. |
