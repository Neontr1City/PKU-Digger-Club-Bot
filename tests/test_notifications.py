import json
import smtplib
from datetime import datetime, timedelta, timezone

import pytest

from cricket import db
from cricket import notifications as n
from cricket import service as s

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'mail.sqlite3'
    db.initialize(path)
    connection = db.connect(path)
    yield connection
    connection.close()


@pytest.fixture
def config():
    return dict(
        ADMIN_EMAIL_ENABLED=True,
        QQ_SMTP_EMAIL='sender@qq.com',
        QQ_SMTP_AUTH_CODE='private-test-code',
        ADMIN_EMAIL_TO='',
        PUBLIC_BASE_URL='https://example.com',
        DEMO_MODE=False,
    )


def nomination(conn, state='review', attempt=1, nomination_state='pending'):
    s.nominate(
        conn,
        dict(
            submission_id='a' * 32,
            nominator='测试听众',
            a_artist='艺人 A',
            a_title='歌曲 A',
            b_artist='艺人 B',
            b_title='歌曲 B',
        ),
        NOW,
    )
    report = dict(
        attempt=attempt,
        sides=dict(
            a=dict(resolved=True, warnings=['封面缺失']),
            b=dict(resolved=state == 'complete', reasons=['未找到可信匹配。']),
        ),
    )
    with conn:
        conn.execute('UPDATE enrichment_jobs SET status=?,report=?', (state, json.dumps(report)))
        conn.execute('UPDATE nominations SET status=?', (nomination_state,))


def test_actionable_email_content_dedup_and_restart(conn, config, monkeypatch):
    nomination(conn)
    sent = []
    monkeypatch.setattr(n, 'send', lambda config, mail: sent.append(mail))
    assert n.process_next(conn, config, NOW)['status'] == 'sent'
    assert not n.process_next(conn, config, NOW + timedelta(days=1))
    assert len(sent) == 1
    mail = sent[0]
    assert mail['To'] == 'sender@qq.com'
    body = mail.get_content()
    assert '艺人 A — 歌曲 A' in body and 'B：未找到可信匹配。' in body
    assert 'https://example.com/admin/nomination/1' in body
    assert '测试听众' not in body and 'private-test-code' not in mail.as_string()
    assert conn.execute('SELECT status FROM nominations').fetchone()[0] == 'pending'
    # A manual lookup retry must not repeat an already accepted notification.
    with conn:
        conn.execute("UPDATE enrichment_jobs SET status='queued'")
    assert not n.process_next(conn, config, NOW)
    with conn:
        conn.execute("UPDATE enrichment_jobs SET status='review'")
    assert not n.process_next(conn, config, NOW + timedelta(days=2))


@pytest.mark.parametrize(
    'state,attempt,nomination_state,expected',
    [
        ('queued', 0, 'pending', False),
        ('running', 1, 'pending', False),
        ('error', 1, 'pending', False),
        ('error', 2, 'pending', False),
        ('error', 3, 'pending', True),
        ('complete', 1, 'ready', False),
        ('review', 1, 'skipped', False),
        ('review', 1, 'ready', False),
    ],
)
def test_only_unresolved_or_exhausted_errors_notify(
    conn, config, monkeypatch, state, attempt, nomination_state, expected
):
    nomination(conn, state, attempt, nomination_state)
    sent = []
    monkeypatch.setattr(n, 'send', lambda config, mail: sent.append(mail))
    assert bool(n.process_next(conn, config, NOW)) == expected
    assert bool(sent) == expected


def test_failed_email_backoff_rechecks_issue_and_keeps_message_id(
    conn, config, monkeypatch, capsys
):
    nomination(conn)
    messages = []

    def failing(config, mail):
        messages.append(mail['Message-ID'])
        raise smtplib.SMTPAuthenticationError(535, b'private-test-code')

    monkeypatch.setattr(n, 'send', failing)
    assert n.process_next(conn, config, NOW)['status'] == 'failed'
    assert not n.process_next(conn, config, NOW + timedelta(minutes=14))
    monkeypatch.setattr(n, 'send', lambda config, mail: messages.append(mail['Message-ID']))
    assert n.process_next(conn, config, NOW + timedelta(minutes=15))['status'] == 'sent'
    assert messages[0] == messages[1]
    assert 'private-test-code' not in capsys.readouterr().out
    assert 'private-test-code' not in str(
        dict(conn.execute('SELECT * FROM email_notifications').fetchone())
    )


def test_resolved_issue_is_not_retried(conn, config, monkeypatch):
    nomination(conn)

    def fail(*args):
        raise OSError('network')

    monkeypatch.setattr(n, 'send', fail)
    n.process_next(conn, config, NOW)
    with conn:
        conn.execute("UPDATE nominations SET status='ready'")
    assert not n.process_next(conn, config, NOW + timedelta(hours=1))


def test_claim_prevents_second_worker_and_recovers_abandoned_send(conn, config, monkeypatch):
    nomination(conn)

    def sending(config, mail):
        assert not n.process_next(conn, config, NOW)

    monkeypatch.setattr(n, 'send', sending)
    assert n.process_next(conn, config, NOW)['status'] == 'sent'
    with conn:
        conn.execute("UPDATE email_notifications SET status='sending'")
    monkeypatch.setattr(n, 'send', lambda *args: None)
    assert not n.process_next(conn, config, NOW + timedelta(minutes=14))
    assert n.process_next(conn, config, NOW + timedelta(minutes=15))['status'] == 'sent'


@pytest.mark.parametrize('change', [dict(ADMIN_EMAIL_ENABLED=False), dict(DEMO_MODE=True)])
def test_disabled_and_demo_never_send(conn, config, monkeypatch, change):
    nomination(conn)
    config.update(change)
    monkeypatch.setattr(n, 'send', lambda *_: pytest.fail('Must not send'))
    assert not n.process_next(conn, config, NOW)
    assert not conn.execute('SELECT * FROM email_notifications').fetchone()
    with pytest.raises(ValueError):
        n.send_test(config)


def test_qq_tls_auth_and_quit_failure_does_not_retry(config, monkeypatch):
    calls = []

    class SMTP:
        def __init__(self, host, port, timeout, context):
            assert (host, port, timeout) == ('smtp.qq.com', 465, 15)
            assert context.check_hostname

        def login(self, sender, code):
            assert sender == config['QQ_SMTP_EMAIL'] and code == config['QQ_SMTP_AUTH_CODE']

        def send_message(self, mail, from_addr, to_addrs):
            calls.append((from_addr, to_addrs))
            return {}

        def quit(self):
            raise smtplib.SMTPServerDisconnected('QUIT failed after acceptance')

        def close(self):
            calls.append('closed')

    monkeypatch.setattr(n.smtplib, 'SMTP_SSL', SMTP)
    n.send_test(config)
    assert calls == [('sender@qq.com', ['sender@qq.com']), 'closed']


def test_no_recipient_header_injection(config):
    config['ADMIN_EMAIL_TO'] = 'one@example.com\r\nBcc: two@example.com'
    with pytest.raises(ValueError):
        n.message(config, 'test', 'body')
