# DailyBasket

Local Streamlit MVP for private grocery planning, inventory batches, and daily reminders.

For a Windows demo setup, the exact registration and login steps, reminder email setup, and Streamlit Community Cloud limitations, see the [demo and onboarding guide](DEMO_GUIDE.md).

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

## Reminder worker

Run independently of Streamlit (for example, every 5 minutes with Task Scheduler):

```powershell
python worker.py
```

It checks each verified, unpaused account at its local reminder time, atomically claims a customer/day before sending, records retry state, and will not resend a successfully delivered local-day reminder. Missing SMTP is recorded as a retryable failure, never a delivery. Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, and optionally `DASHBOARD_URL` for email delivery. SMTP cannot guarantee exactly-once delivery if a server accepts a message but the client loses the response; an `in_progress` claim is therefore not automatically resent after a crash, preventing a possible duplicate and requiring operator review/retry of the recorded delivery.

## Validation

```powershell
pytest -q
```

Dates are planning information: entered package dates take priority; vegetable dates are configurable freshness estimates, not food-safety guarantees. Defaults are manual nutrition, expected-use rates, and quiet-day reminder emails.
