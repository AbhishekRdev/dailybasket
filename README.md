# DailyBasket

Local Streamlit MVP for private grocery planning, inventory batches, and in-app expiry and surplus reminders.

For a Windows demo setup, the exact registration and login steps, dashboard reminder walkthrough, and Streamlit Community Cloud limitations, see the [demo and onboarding guide](DEMO_GUIDE.md).

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

The SQLite database defaults to `dailybasket.db`; set `DAILYBASKET_DB` to choose another path. Verification requires SMTP by default: configure `SMTP_HOST` (plus the SMTP settings below) to deliver tokens only to the mailbox, never the UI. For an explicitly local, non-production simulation only, set `DAILYBASKET_DEV_MODE=1`; then the app displays a clearly labelled development-only token. If neither SMTP nor that explicit flag is configured, registration and email changes do not create a verification token and tell the operator what to configure. An email change remains pending and the existing verified reminder address remains active until its new token is verified.

SMTP verification requires `SMTP_HOST`, `SMTP_FROM`, and a port from `1` through `65535` (`SMTP_PORT` defaults to `587`). `SMTP_TIMEOUT` defaults to 20 seconds and must be greater than 0 and no more than 120 seconds; it bounds a stalled verification connection while the onboarding transaction is open. A connection, authentication, timeout, or send failure rolls back a new registration or pending email change, so a failed destination never becomes active. Unverified accounts can request a new token from the Verify email screen; this rotates the prior token and always returns a generic production response to avoid exposing whether an account exists.

Product pictures are stored as private SQLite blobs and are read only through the signed-in owner’s product view; no uploaded file path is exposed. Batch removal is non-destructive: it removes stock and retains the batch/event audit history.

## In-app inventory status

The Dashboard groups every active batch into **Fresh stock** or **Needs attention**. Needs-attention items are expired, due today, within the configured soon window, possible surplus, or missing an expected-use rate close to expiry. This status updates from the database whenever the Dashboard loads; no worker, SMTP configuration, or scheduled process is required for inventory reminders.

SMTP remains necessary only when email verification is enabled outside explicitly local development mode.

## Validation

```powershell
pytest -q
```

Dates are planning information: entered package dates take priority; vegetable dates are configurable freshness estimates, not food-safety guarantees. Defaults are manual nutrition and expected-use rates.
