from datetime import date, datetime, timezone
import logging
import pytest
import smtplib
import dailybasket as db
import worker

@pytest.fixture(autouse=True)
def local_development(monkeypatch):
    monkeypatch.setenv('DAILYBASKET_DEV_MODE', '1')
    monkeypatch.delenv('SMTP_HOST', raising=False)

def setup(tmp_path):
    path=str(tmp_path/'basket.db'); db.initialize(path); return path,db.connect(path)
def account(conn,email='a@example.com'):
    token=db.register(conn,email,'password1'); db.verify_email(conn,token); return db.authenticate(conn,email,'password1')
def test_spinach_transfer_and_isolation(tmp_path):
    path,conn=setup(tmp_path); first=account(conn); second=account(conn,'b@example.com')
    db.add_shopping(conn,first['id'],'spinach',1,'kg')
    assert len(db.list_shopping(conn,first['id']))==1 and not db.list_shopping(conn,second['id'])
    product=db.upsert_product(conn,first['id'],'spinach','vegetable')
    batch=db.add_batch(conn,first['id'],product,1,'kg',date(2026,1,1),'refrigerated')
    assert db.require_owned(conn,'batches',second['id'],batch) is None
    assert db.inventory(conn,second['id']) == []
def test_estimate_surplus_and_events(tmp_path):
    path,conn=setup(tmp_path); user=account(conn); db.update_preferences(conn,user['id'],timezone='UTC',soon_days=3)
    product=db.upsert_product(conn,user['id'],'spinach','vegetable',nutrition={'calories':23},basis='per 100 g',use_rate=1,use_unit='kg')
    batch=db.add_batch(conn,user['id'],product,3,'kg',date(2026,1,1),'refrigerated')
    row=db.require_owned(conn,'batches',user['id'],batch); assert row['expiry_source']=='estimated' and row['expiry_date']=='2026-01-06'
    notices=db.alerts(conn,user['id'],date(2026,1,4)); assert notices[0]['surplus']['remaining']==3
    db.change_batch(conn,user['id'],batch,3,'consumed')
    assert db.require_owned(conn,'batches',user['id'],batch)['status']=='finished'
    assert not db.alerts(conn,user['id'],date(2026,1,4))
def test_worker_records_one_success_per_local_day(tmp_path, monkeypatch):
    path,conn=setup(tmp_path); user=account(conn); db.update_preferences(conn,user['id'],timezone='UTC',reminder_time='09:00')
    sent=[]; monkeypatch.setattr(worker,'deliver',lambda *args: sent.append(args))
    now=datetime(2026,1,2,10,tzinfo=timezone.utc); worker.run(path,now); worker.run(path,now)
    row=conn.execute('SELECT * FROM reminders WHERE owner_id=?',(user['id'],)).fetchone()
    assert row['status']=='sent' and row['attempts']==1 and len(sent)==1

def test_shopping_batch_edit_and_estimate_override(tmp_path):
    path,conn=setup(tmp_path); user=account(conn); db.add_shopping(conn,user['id'],'spinach',1,'kg')
    item=db.list_shopping(conn,user['id'])[0]; db.edit_shopping(conn,user['id'],item['id'],'spinach',2,'bags')
    edited=db.list_shopping(conn,user['id'])[0]; assert (edited['quantity'],edited['unit']) == (2,'bags')
    product=db.upsert_product(conn,user['id'],'spinach','vegetable'); batch=db.add_batch(conn,user['id'],product,2,'bags',date(2026,1,1),'refrigerated')
    db.edit_batch(conn,user['id'],batch,3,'bags',date(2026,1,2),'room',date(2026,1,9))
    row=db.require_owned(conn,'batches',user['id'],batch); assert (row['quantity'],row['expiry_date'],row['expiry_source']) == (3,'2026-01-09','entered')

def test_correction_finish_remove_preserve_events(tmp_path):
    path,conn=setup(tmp_path); user=account(conn); product=db.upsert_product(conn,user['id'],'milk','dairy'); batch=db.add_batch(conn,user['id'],product,3,'l',date.today(),'refrigerated',date.today())
    db.correct_batch(conn,user['id'],batch,2); db.finish_batch(conn,user['id'],batch); db.remove_batch(conn,user['id'],batch)
    row=db.require_owned(conn,'batches',user['id'],batch); events=conn.execute('SELECT reason FROM events WHERE batch_id=?',(batch,)).fetchall()
    assert row['status']=='removed' and [event['reason'] for event in events] == ['correction','consumed'] and not db.inventory(conn,user['id'],status='Active')

def test_email_change_and_image_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('DAILYBASKET_DEV_MODE','1'); path,conn=setup(tmp_path); first=account(conn); second=account(conn,'b@example.com')
    token=db.request_email_change(conn,first['id'],'new@example.com'); assert db.authenticate(conn,'new@example.com','password1') is None
    assert db.verify_email(conn,token); assert db.authenticate(conn,'new@example.com','password1')
    product=db.upsert_product(conn,first['id'],'apple','fruit'); db.update_product(conn,first['id'],product,'fruit',{},None,None,None,b'private-image','image/png')
    assert db.product_detail(conn,first['id'],product)['image_data'] == b'private-image'
    assert db.product_detail(conn,second['id'],product) is None

def test_filters_surplus_rate_allocated_and_date_boundary(tmp_path):
    path,conn=setup(tmp_path); user=account(conn); db.update_preferences(conn,user['id'],timezone='UTC',soon_days=3)
    product=db.upsert_product(conn,user['id'],'spinach','vegetable',use_rate=7,use_unit='kg')
    first=db.add_batch(conn,user['id'],product,1,'kg',date(2026,1,1),'refrigerated',date(2026,1,4)); second=db.add_batch(conn,user['id'],product,1,'kg',date(2026,1,1),'refrigerated',date(2026,1,5))
    notices=db.alerts(conn,user['id'],date(2026,1,4)); assert notices[0]['state']=='today' and notices[0]['surplus'] is None
    assert len(db.inventory(conn,user['id'],category='vegetable',status='Active')) == 2
    assert len(db.inventory(conn,user['id'],status='Soon')) == 2

def test_worker_pause_retry_and_quiet_day(tmp_path, monkeypatch):
    path,conn=setup(tmp_path); user=account(conn); db.update_preferences(conn,user['id'],timezone='UTC',reminder_time='09:00',paused=1)
    now=datetime(2026,1,2,10,tzinfo=timezone.utc); worker.run(path,now); assert not conn.execute('SELECT * FROM reminders').fetchall()
    db.update_preferences(conn,user['id'],paused=0); monkeypatch.setattr(worker,'deliver',lambda *_: (_ for _ in ()).throw(RuntimeError('temporary'))); worker.run(path,now)
    assert conn.execute('SELECT status FROM reminders').fetchone()['status']=='retry'
    monkeypatch.setattr(worker,'deliver',lambda *_: None); worker.run(path,now); assert conn.execute('SELECT attempts,status FROM reminders').fetchone()['status']=='sent'
    assert 'Nothing needs attention today.' in worker.body(conn,user['id']) and 'DailyBasket dashboard' in worker.body(conn,user['id'])

def test_missing_smtp_does_not_expose_or_create_verifiable_account(tmp_path, monkeypatch):
    monkeypatch.delenv('DAILYBASKET_DEV_MODE', raising=False); path,conn=setup(tmp_path)
    with pytest.raises(RuntimeError): db.register(conn,'blocked@example.com','password1')
    assert conn.execute("SELECT * FROM users WHERE email='blocked@example.com'").fetchone() is None

class FakeSMTP:
    sent = []
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def starttls(self): pass
    def login(self, *_): pass
    def send_message(self, message): self.sent.append(message)

def smtp_config(monkeypatch):
    monkeypatch.delenv('DAILYBASKET_DEV_MODE', raising=False)
    monkeypatch.setenv('SMTP_HOST','smtp.example.test'); monkeypatch.setenv('SMTP_FROM','noreply@example.test'); monkeypatch.setenv('SMTP_PORT','587')

def test_smtp_registration_success_and_single_use_token(tmp_path, monkeypatch):
    smtp_config(monkeypatch); monkeypatch.setattr(smtplib,'SMTP',FakeSMTP); FakeSMTP.sent=[]; path,conn=setup(tmp_path)
    assert db.register(conn,'smtp@example.com','password1') is None and len(FakeSMTP.sent)==1
    token=conn.execute("SELECT verification_token FROM users WHERE email='smtp@example.com'").fetchone()['verification_token']
    assert db.verify_email(conn,token) and not db.verify_email(conn,token)

def test_smtp_send_failure_rolls_back_registration_and_email_change(tmp_path, monkeypatch):
    smtp_config(monkeypatch)
    class BrokenSMTP(FakeSMTP):
        def send_message(self, message): raise OSError('credentials must not leak')
    monkeypatch.setattr(smtplib,'SMTP',BrokenSMTP); path,conn=setup(tmp_path)
    with pytest.raises(RuntimeError,match='Could not send'): db.register(conn,'failed@example.com','password1')
    assert conn.execute("SELECT * FROM users WHERE email='failed@example.com'").fetchone() is None
    monkeypatch.setenv('DAILYBASKET_DEV_MODE','1'); token=db.register(conn,'old@example.com','password1'); db.verify_email(conn,token)
    monkeypatch.delenv('DAILYBASKET_DEV_MODE',raising=False)
    with pytest.raises(RuntimeError,match='Could not send'): db.request_email_change(conn,db.authenticate(conn,'old@example.com','password1')['id'],'new@example.com')
    user=db.authenticate(conn,'old@example.com','password1'); assert user and user['email']=='old@example.com'
    assert conn.execute('SELECT pending_email FROM users WHERE id=?',(user['id'],)).fetchone()['pending_email'] is None

@pytest.mark.parametrize(
    ('failure_factory', 'error_class', 'summary'),
    [
        (lambda text: smtplib.SMTPAuthenticationError(535, text.encode()), 'SMTPAuthenticationError', 'smtp_authentication_failure'),
        (lambda text: smtplib.SMTPNotSupportedError(text), 'SMTPNotSupportedError', 'smtp_tls_not_supported'),
        (lambda text: smtplib.SMTPRecipientsRefused({'recipient-secret@example.test': (550, text.encode())}), 'SMTPRecipientsRefused', 'smtp_recipient_rejected'),
        (lambda text: smtplib.SMTPDataError(554, text.encode()), 'SMTPDataError', 'smtp_data_rejected'),
        (lambda text: OSError(text), 'OSError', 'network_or_connection_failure'),
        (lambda text: RuntimeError(text), 'Exception', 'unexpected_delivery_failure'),
    ],
)
def test_verification_failure_logs_only_safe_diagnostics(monkeypatch, caplog, failure_factory, error_class, summary):
    smtp_config(monkeypatch)
    recipient = 'recipient-secret@example.test'
    sender = 'sender-secret@example.test'
    smtp_user = 'smtp-user-secret'
    smtp_password = 'smtp-password-secret'
    token = 'verification-token-secret'
    monkeypatch.setenv('SMTP_FROM', sender)
    monkeypatch.setenv('SMTP_USER', smtp_user)
    monkeypatch.setenv('SMTP_PASSWORD', smtp_password)
    sensitive_text = f'{recipient} {sender} {smtp_user} {smtp_password} {token}'

    class BrokenSMTP(FakeSMTP):
        def send_message(self, message):
            raise failure_factory(sensitive_text)

    monkeypatch.setattr(smtplib, 'SMTP', BrokenSMTP)
    with caplog.at_level(logging.WARNING, logger='dailybasket'):
        with pytest.raises(RuntimeError) as raised:
            db.send_verification_email(recipient, token)

    error = raised.value
    assert str(error) == 'Could not send verification email. Check SMTP configuration and try again.'
    assert error.__cause__ is None and error.__suppress_context__
    record = next(record for record in caplog.records if record.name == 'dailybasket')
    assert record.msg == 'Verification email delivery failed; exception_class=%s summary=%s'
    assert record.args == (error_class, summary)
    assert record.exc_info is None and record.exc_text is None
    for secret in (recipient, sender, smtp_user, smtp_password, token):
        assert secret not in record.getMessage()
        assert secret not in record.msg
        assert secret not in repr(record.args)

def test_failed_resend_preserves_prior_token(tmp_path, monkeypatch):
    path, conn = setup(tmp_path)
    token = db.register(conn, 'resend-failure@example.test', 'password1')
    smtp_config(monkeypatch)

    class BrokenSMTP(FakeSMTP):
        def send_message(self, message): raise OSError('delivery failed')

    monkeypatch.setattr(smtplib, 'SMTP', BrokenSMTP)
    with pytest.raises(RuntimeError, match='Could not send verification email'):
        db.resend_verification(conn, 'resend-failure@example.test')
    current = conn.execute("SELECT verification_token FROM users WHERE email='resend-failure@example.test'").fetchone()['verification_token']
    assert current == token

def test_successful_verification_delivery_emits_no_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger='dailybasket'):
        assert db.send_verification_email('dev@example.test', 'dev-token') == 'dev-token'
    assert not [record for record in caplog.records if record.name == 'dailybasket']

    smtp_config(monkeypatch)
    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='dailybasket'):
        assert db.send_verification_email('smtp@example.test', 'smtp-token') is None
    assert not [record for record in caplog.records if record.name == 'dailybasket']

def test_smtp_configuration_and_resend_rotation(tmp_path, monkeypatch):
    monkeypatch.delenv('DAILYBASKET_DEV_MODE',raising=False); path,conn=setup(tmp_path)
    monkeypatch.setenv('SMTP_HOST','x'); monkeypatch.delenv('SMTP_FROM',raising=False)
    with pytest.raises(RuntimeError,match='SMTP_FROM'): db.register(conn,'bad@example.com','password1')
    smtp_config(monkeypatch); monkeypatch.setattr(smtplib,'SMTP',FakeSMTP); db.register(conn,'resend@example.com','password1')
    first=conn.execute("SELECT verification_token FROM users WHERE email='resend@example.com'").fetchone()['verification_token']; assert db.resend_verification(conn,'resend@example.com') is None
    second=conn.execute("SELECT verification_token FROM users WHERE email='resend@example.com'").fetchone()['verification_token']
    assert first != second and not db.verify_email(conn,first) and db.verify_email(conn,second)

def test_smtp_timeout_is_bounded_and_invalid_timeout_blocks_mutation(tmp_path, monkeypatch):
    smtp_config(monkeypatch); path,conn=setup(tmp_path); captured=[]
    class CapturingSMTP(FakeSMTP):
        def __init__(self, *args, **kwargs): captured.append(kwargs['timeout'])
    monkeypatch.setattr(smtplib,'SMTP',CapturingSMTP); db.register(conn,'timeout@example.com','password1')
    assert captured == [20.0]
    monkeypatch.setenv('SMTP_TIMEOUT','0')
    with pytest.raises(RuntimeError,match='SMTP_TIMEOUT'): db.register(conn,'invalid-timeout@example.com','password1')
    assert conn.execute("SELECT * FROM users WHERE email='invalid-timeout@example.com'").fetchone() is None

def test_worker_missing_smtp_is_retry_not_sent(tmp_path, monkeypatch):
    path,conn=setup(tmp_path); user=account(conn); db.update_preferences(conn,user['id'],timezone='UTC',reminder_time='09:00')
    monkeypatch.delenv('SMTP_HOST',raising=False); worker.run(path,datetime(2026,1,2,10,tzinfo=timezone.utc))
    row=conn.execute('SELECT * FROM reminders WHERE owner_id=?',(user['id'],)).fetchone()
    assert row['status']=='retry' and 'SMTP_HOST' in row['error']

def test_worker_atomic_claim_blocks_contending_send(tmp_path, monkeypatch):
    path,conn=setup(tmp_path); user=account(conn); db.update_preferences(conn,user['id'],timezone='UTC',reminder_time='09:00')
    sends=[]
    def overlapping(*args):
        sends.append(args); worker.run(path,datetime(2026,1,2,10,tzinfo=timezone.utc))
    monkeypatch.setattr(worker,'deliver',overlapping); worker.run(path,datetime(2026,1,2,10,tzinfo=timezone.utc))
    assert len(sends)==1 and conn.execute('SELECT status FROM reminders').fetchone()['status']=='sent'
