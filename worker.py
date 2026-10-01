"""Run periodically outside Streamlit to send one local-day reminder per account."""
import os, smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import dailybasket as db

def body(conn, owner_id):
    notices=db.alerts(conn,owner_id); lines=["DailyBasket summary"]
    if not notices: lines.append("Nothing needs attention today.")
    else:
        for item in notices:
            source="estimated planning date" if item['expiry_source']=='estimated' else "package date"
            lines.append(f"- {item['name']}: {item['remaining_quantity']} {item['unit']}, expiry {item['expiry_date']} ({source})")
            if item['surplus']: lines.append(f"  Possible surplus, not certain waste: {item['surplus']['remaining']} remaining vs {item['surplus']['expected']} expected use.")
            elif item['usage_rate_needed']: lines.append("  Usage rate needed for surplus estimate.")
    return "\n".join(lines) + "\n\n" + os.getenv("DASHBOARD_URL", "Open your DailyBasket dashboard.")
def deliver(email, content):
    if not os.getenv("SMTP_HOST"): raise RuntimeError("SMTP_HOST is not configured; reminder was not delivered.")
    message=EmailMessage(); message["Subject"]="DailyBasket daily summary"; message["From"]=os.environ["SMTP_FROM"]; message["To"]=email; message.set_content(content)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT","587"))) as smtp:
        smtp.starttls();
        if os.getenv("SMTP_USER"): smtp.login(os.environ["SMTP_USER"],os.environ.get("SMTP_PASSWORD",""))
        smtp.send_message(message)
def run(path=None, now=None):
    db.initialize(path); conn=db.connect(path); now=now or datetime.now(timezone.utc)
    for account in conn.execute("SELECT u.*,p.timezone,p.reminder_time,p.paused FROM users u JOIN preferences p ON p.owner_id=u.id WHERE u.verified=1 AND p.paused=0"):
        local=now.astimezone(ZoneInfo(account['timezone'])); local_day=local.date().isoformat()
        if local.strftime('%H:%M') < account['reminder_time']: continue
        # Claim first in a committed transaction. Other workers skip sent/in-progress rows;
        # only retry rows may be reclaimed after an explicitly recorded failed attempt.
        with conn:
            created=conn.execute("INSERT OR IGNORE INTO reminders(owner_id,local_date,status,attempts) VALUES(?,?,?,1)",(account['id'],local_day,'in_progress')).rowcount
            retried=0 if created else conn.execute("UPDATE reminders SET status='in_progress',attempts=attempts+1,error=NULL WHERE owner_id=? AND local_date=? AND status='retry'",(account['id'],local_day)).rowcount
        if not (created or retried): continue
        try:
            deliver(account['email'],body(conn,account['id'])); conn.execute("UPDATE reminders SET status='sent',sent_at=?,error=NULL WHERE owner_id=? AND local_date=?",(now.isoformat(),account['id'],local_day))
        except Exception as error: conn.execute("UPDATE reminders SET status='retry',error=? WHERE owner_id=? AND local_date=?",(str(error),account['id'],local_day))
        conn.commit()
if __name__ == '__main__': run()
