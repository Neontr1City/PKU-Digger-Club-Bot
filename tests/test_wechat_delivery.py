import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cricket import db, wechat
from cricket import service as s

NOW = datetime(2026, 9, 28, 5, tzinfo=timezone.utc)
DAY = '2026-09-28'


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'db.sqlite3'
    db.initialize(path)
    connection = db.connect(path)
    yield connection
    connection.close()


@pytest.fixture
def config(tmp_path):
    return dict(
        WECHAT_SEND_ENABLED=True,
        WECHAT_GROUP='PKU Digger Bot测试',
        WECHAT_OUTBOX=str(tmp_path / 'outbox'),
        ADMIN_EMAIL_ENABLED=True,
        QQ_SMTP_EMAIL='sender@qq.com',
        QQ_SMTP_AUTH_CODE='private-code',
        PUBLIC_BASE_URL='https://example.com',
        OUTPUT_DIR=str(tmp_path),
        DEMO_MODE=False,
    )


def heartbeat(config, state='ready', reason='', now=NOW):
    wechat.write_private(
        Path(config['WECHAT_OUTBOX']) / 'health.json',
        dict(state=state, reason=reason, checked_at=now.timestamp()),
    )


def prepare(conn, day=DAY):
    messages = [
        dict(kind='text', text='让我们恭喜青葉市子👏'),
        dict(kind='text', text='今天的曲目：A vs B\n投票链接：https://example.com'),
    ]
    with conn:
        conn.execute(
            'INSERT INTO dispatches VALUES (?,?,?,?)',
            (day, s.encode(messages), 'prepared', s.stamp(NOW)),
        )
    return messages


def receipt(config, state, reason=''):
    root = Path(config['WECHAT_OUTBOX'])
    requests = sorted((root / 'requests').glob('*.json'))
    for path in requests:
        target = root / 'receipts' / path.name
        if not target.exists():
            request = json.loads(path.read_text())
            value = {k: request[k] for k in ('key', 'digest', 'group')}
            wechat.write_private(target, dict(**value, state=state, reason=reason))
            return value


def test_order_unicode_and_idempotent_restart(conn, config):
    messages = prepare(conn)
    heartbeat(config)
    assert wechat.dispatch_next(conn, config, NOW)['position'] == 0
    requests = list((Path(config['WECHAT_OUTBOX']) / 'requests').glob('*.json'))
    assert len(requests) == 1
    first = json.loads(requests[0].read_text())
    assert first['payload']['text'] == messages[0]['text']
    assert (
        first['digest']
        == hashlib.sha256(
            json.dumps(first['payload'], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    )
    assert wechat.dispatch_next(conn, config, NOW)['state'] == 'queued'
    assert len(list(requests[0].parent.glob('*.json'))) == 1
    receipt(config, 'confirmed')
    assert wechat.dispatch_next(conn, config, NOW)['position'] == 1
    receipt(config, 'confirmed')
    assert wechat.dispatch_next(conn, config, NOW)['state'] == 'sent'
    assert not wechat.dispatch_next(conn, config, NOW)
    assert conn.execute('SELECT count(*) FROM wechat_deliveries').fetchone()[0] == 2


def test_uncertain_send_never_retried_and_admin_must_wait(conn, config):
    prepare(conn)
    heartbeat(config)
    wechat.dispatch_next(conn, config, NOW)
    value = receipt(config, 'uncertain', 'interrupted_send')
    assert wechat.dispatch_next(conn, config, NOW)['state'] == 'uncertain'
    wechat.dispatch_next(conn, config, NOW + timedelta(minutes=4))
    with pytest.raises(ValueError, match='五分钟'):
        wechat.resolve_delivery(conn, config, value['key'], 'retry', NOW + timedelta(minutes=4))
    wechat.resolve_delivery(conn, config, value['key'], 'confirm', NOW + timedelta(minutes=5))
    heartbeat(config, now=NOW + timedelta(minutes=5))
    assert wechat.dispatch_next(conn, config, NOW + timedelta(minutes=5))['position'] == 1


@pytest.mark.parametrize('change', [dict(DEMO_MODE=True), dict(WECHAT_SEND_ENABLED=False)])
def test_disabled_does_not_create_requests(conn, config, change):
    prepare(conn)
    heartbeat(config)
    config.update(change)
    assert not wechat.dispatch_next(conn, config, NOW)
    assert not (Path(config['WECHAT_OUTBOX']) / 'requests').exists()
    assert not wechat.monitor(conn, config, NOW)


def test_missing_heartbeat_wrong_target_and_stale_day_hold(conn, config):
    prepare(conn)
    assert not wechat.dispatch_next(conn, config, NOW)
    heartbeat(config, 'blocked', 'target_not_verified')
    assert not wechat.dispatch_next(conn, config, NOW)
    heartbeat(config, now=NOW - timedelta(minutes=4))
    assert wechat.health(config, NOW)['reason'] == 'heartbeat_missing'
    heartbeat(config, now=NOW + timedelta(days=1))
    assert not wechat.dispatch_next(conn, config, NOW + timedelta(days=1))
    assert not (Path(config['WECHAT_OUTBOX']) / 'requests').exists()


@pytest.mark.parametrize(
    'url',
    [
        'https://elsewhere.test/rounds/2026-09-28/result/1.png',
        'file:///etc/passwd',
        'https://example.com/rounds/2026-09-28/result/1.png?url=http://localhost',
        'https://example.com/artwork/../../secret',
    ],
)
def test_images_must_be_frozen_local_result(conn, config, url):
    with pytest.raises(ValueError):
        wechat.materialize(conn, config, dict(kind='image', url=url))
    with pytest.raises(ValueError, match='frozen'):
        wechat.materialize(
            conn,
            config,
            dict(kind='image', url='https://example.com/rounds/2026-09-28/result/1.png'),
        )


def test_offline_alert_debounce_dedup_recovery_and_second_outage(conn, config, monkeypatch):
    sent = []
    monkeypatch.setattr(wechat.notifications, 'send', lambda cfg, mail: sent.append(mail))
    heartbeat(config, 'blocked', 'logged_out')
    assert wechat.monitor(conn, config, NOW)['state'] == 'observing'
    assert not wechat.monitor(conn, config, NOW + timedelta(minutes=1))
    assert wechat.monitor(conn, config, NOW + timedelta(minutes=2))['state'] == 'mail_sent'
    assert not wechat.monitor(conn, config, NOW + timedelta(minutes=10))
    assert len(sent) == 1
    assert 'private-code' not in sent[0].as_string()
    assert '重新登录' in sent[0].get_content()
    heartbeat(config, now=NOW + timedelta(minutes=11))
    assert not wechat.monitor(conn, config, NOW + timedelta(minutes=11))
    assert not conn.execute('SELECT recovered_at FROM wechat_incidents').fetchone()[0]
    heartbeat(config, now=NOW + timedelta(minutes=13))
    wechat.monitor(conn, config, NOW + timedelta(minutes=13))
    assert conn.execute('SELECT recovered_at FROM wechat_incidents').fetchone()[0]
    heartbeat(config, 'blocked', 'logged_out', NOW + timedelta(minutes=32))
    wechat.monitor(conn, config, NOW + timedelta(minutes=32))
    wechat.monitor(conn, config, NOW + timedelta(minutes=34))
    assert len(sent) == 2 and sent[0]['Message-ID'] != sent[1]['Message-ID']


def test_transient_offline_does_not_email_and_smtp_failure_backs_off(conn, config, monkeypatch):
    calls = []

    def fail(cfg, mail):
        calls.append(mail['Message-ID'])
        raise OSError('private-code')

    monkeypatch.setattr(wechat.notifications, 'send', fail)
    wechat.monitor(conn, config, NOW)
    heartbeat(config, now=NOW + timedelta(minutes=1))
    wechat.monitor(conn, config, NOW + timedelta(minutes=1))
    assert not calls
    heartbeat(config, now=NOW + timedelta(minutes=3))
    wechat.monitor(conn, config, NOW + timedelta(minutes=3))
    heartbeat(config, 'blocked', 'logged_out', NOW + timedelta(minutes=4))
    wechat.monitor(conn, config, NOW + timedelta(minutes=4))
    assert wechat.monitor(conn, config, NOW + timedelta(minutes=6))['state'] == 'mail_failed'
    assert not wechat.monitor(conn, config, NOW + timedelta(minutes=20))
    monkeypatch.setattr(
        wechat.notifications, 'send', lambda cfg, mail: calls.append(mail['Message-ID'])
    )
    assert wechat.monitor(conn, config, NOW + timedelta(minutes=21))['state'] == 'mail_sent'
    assert calls[0] == calls[1]


def test_exact_group_title_guard():
    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    assert sender.target_matches('PKU Digger Bot 测试 (4)', 'PKU Digger Bot测试')
    assert not sender.target_matches('PKU Digger Bot测试二群 (4)', 'PKU Digger Bot测试')
    assert not sender.target_matches('PKU Digger Bot (4)', 'PKU Digger Bot测试')
    assert not sender.target_matches('今天你滚了吗（pku版）', 'PKU Digger Bot测试')


@pytest.mark.parametrize('width', [1080, 864])
def test_poster_fingerprint_rejects_wrong_image(width):
    from PIL import Image, ImageDraw

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    reference = Image.new('RGB', (1080, 1474), '#fafafa')
    draw = ImageDraw.Draw(reference)
    draw.rectangle((0, 0, 1080, 260), fill='#151515')
    draw.rectangle((60, 340, 500, 900), fill='#9d532e')
    draw.rectangle((580, 340, 1020, 900), fill='#3c687e')
    reference = reference.resize((width, round(1474 * width / 1080)))
    frame = Image.new('RGB', (917, 667), '#fafafa')
    frame.paste(reference.resize((166, 227)), (670, 220))
    ui = sender.Desktop('test')
    assert ui.image_matches(frame, reference, (450, 82, 880, 517))
    wrong = reference.copy()
    ImageDraw.Draw(wrong).rectangle((0, 300, 1080, 1474), fill='#331166')
    assert not ui.image_matches(frame, wrong, (450, 82, 880, 517))
    assert not ui.image_matches(
        Image.new('RGB', frame.size, 'white'), reference, (450, 82, 880, 517)
    )


def test_admin_recovery_requires_login_and_csrf(conn, config):
    import time

    from cricket import create_app

    past = s.utcnow() - timedelta(minutes=10)
    day = past.astimezone(s.SHANGHAI).date().isoformat()
    prepare(conn, day)
    heartbeat(config, now=past)
    wechat.dispatch_next(conn, config, past)
    value = receipt(config, 'uncertain', 'interrupted_send')
    wechat.dispatch_next(conn, config, past)
    app = create_app(
        dict(
            config,
            TESTING=True,
            SECRET_KEY='test-key',
            ADMIN_PASSWORD='test-password',
            DATABASE=conn.execute('PRAGMA database_list').fetchone()['file'],
        )
    )
    client = app.test_client()
    client.get('/health')
    with client.session_transaction() as session:
        csrf = session['csrf']
    route = '/admin/wechat/delivery/' + value['key']
    assert client.post(route, data=dict(csrf=csrf, action='confirm')).status_code == 403
    with client.session_transaction() as session:
        session['admin_until'] = time.time() + 60
    assert client.post(route, data=dict(action='confirm')).status_code == 400
    assert client.post(route, data=dict(csrf=csrf, action='confirm')).status_code == 303
    assert conn.execute('SELECT state FROM wechat_deliveries').fetchone()[0] == 'confirmed'


@pytest.mark.parametrize('eventually_ready', [True, False])
def test_image_waits_for_complete_preview_before_send(monkeypatch, eventually_ready):
    import io

    from PIL import Image

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('test')
    ui.geometry = dict(WIDTH='917', HEIGHT='667', X='0', Y='0')
    checks, send_boundaries = [], []
    monkeypatch.setattr(ui, 'guard', lambda: ui.geometry)
    monkeypatch.setattr(ui, 'empty_composer', lambda: True)
    monkeypatch.setattr(ui, 'clipboard', lambda *args: None)
    monkeypatch.setattr(ui, 'keys', lambda *args: None)
    monkeypatch.setattr(ui, 'click', lambda *args: None)
    monkeypatch.setattr(ui, 'wait_send_ready', lambda: None)
    monkeypatch.setattr(ui, 'screen', lambda: Image.new('RGB', (917, 667), 'white'))
    monkeypatch.setattr(sender.time, 'sleep', lambda *args: None)

    def compare(*args):
        checks.append(True)
        return eventually_ready and len(checks) >= 3

    def before_click():
        assert len(checks) == 3
        send_boundaries.append(True)

    monkeypatch.setattr(ui, 'image_matches', compare)
    image = io.BytesIO()
    Image.new('RGB', (1080, 1474), 'white').save(image, format='PNG')
    if eventually_ready:
        assert ui.send_image(image.getvalue(), before_click)['state'] == 'confirmed'
        assert send_boundaries == [True]
    else:
        with pytest.raises(sender.GuardError, match='image_preview_not_verified'):
            ui.send_image(image.getvalue(), before_click)
        assert not send_boundaries


def test_expired_unsent_message_can_be_dismissed_without_claiming_delivery(conn, config):
    prepare(conn)
    heartbeat(config)
    wechat.dispatch_next(conn, config, NOW)
    value = receipt(config, 'blocked', 'draft_present')
    wechat.dispatch_next(conn, config, NOW)
    wechat.monitor(conn, config, NOW)
    with pytest.raises(ValueError, match='跨日'):
        wechat.resolve_delivery(conn, config, value['key'], 'skip', NOW + timedelta(minutes=6))
    tomorrow = NOW + timedelta(days=1)
    with pytest.raises(ValueError, match='跨日'):
        wechat.resolve_delivery(conn, config, value['key'], 'retry', tomorrow)
    wechat.resolve_delivery(conn, config, value['key'], 'skip', tomorrow)
    assert conn.execute('SELECT state FROM wechat_deliveries').fetchone()[0] == 'skipped'
    assert conn.execute('SELECT status FROM dispatches').fetchone()[0] == 'expired'
    heartbeat(config, now=tomorrow)
    assert not wechat.monitor(conn, config, tomorrow)
    heartbeat(config, now=tomorrow + timedelta(minutes=2))
    wechat.monitor(conn, config, tomorrow + timedelta(minutes=2))
    assert conn.execute('SELECT recovered_at FROM wechat_incidents').fetchone()[0]


def test_rehearsal_result_still_requires_frozen_local_round(conn, config):
    with pytest.raises(ValueError, match='frozen'):
        wechat.materialize(
            conn,
            config,
            dict(kind='image', url='https://example.com/rounds/2026-09-28-test-1420/result/1.png'),
        )
    with pytest.raises(ValueError, match='Only local'):
        wechat.materialize(
            conn,
            config,
            dict(
                kind='image',
                url='https://example.com/rounds/2026-09-28-test-arbitrary/result/1.png',
            ),
        )


def test_brief_recoveries_do_not_rearm_email(conn, config, monkeypatch):
    sent = []
    monkeypatch.setattr(wechat.notifications, 'send', lambda cfg, mail: sent.append(mail))
    heartbeat(config, 'blocked', 'check_timeout')
    wechat.monitor(conn, config, NOW)
    wechat.monitor(conn, config, NOW + timedelta(minutes=2))
    for minute in (3, 6, 9, 35):
        heartbeat(config, now=NOW + timedelta(minutes=minute))
        wechat.monitor(conn, config, NOW + timedelta(minutes=minute))
        heartbeat(config, 'blocked', 'check_timeout', NOW + timedelta(minutes=minute + 1))
        wechat.monitor(conn, config, NOW + timedelta(minutes=minute + 1))
    assert len(sent) == 1
    assert conn.execute('SELECT count(*) FROM wechat_incidents').fetchone()[0] == 1
    assert '微信推送检查异常' in str(sent[0]['Subject'])


def test_same_interface_problem_has_cooldown_after_stable_recovery(conn, config, monkeypatch):
    sent = []
    monkeypatch.setattr(wechat.notifications, 'send', lambda cfg, mail: sent.append(mail))
    heartbeat(config, 'blocked', 'client_unavailable')
    wechat.monitor(conn, config, NOW)
    wechat.monitor(conn, config, NOW + timedelta(minutes=2))
    for minute in (3, 5):
        heartbeat(config, now=NOW + timedelta(minutes=minute))
        wechat.monitor(conn, config, NOW + timedelta(minutes=minute))
    heartbeat(config, 'blocked', 'check_timeout', NOW + timedelta(minutes=6))
    wechat.monitor(conn, config, NOW + timedelta(minutes=6))
    wechat.monitor(conn, config, NOW + timedelta(minutes=8))
    assert len(sent) == 1
    heartbeat(config, 'blocked', 'check_timeout', NOW + timedelta(minutes=33))
    wechat.monitor(conn, config, NOW + timedelta(minutes=33))
    assert len(sent) == 2


def test_idle_title_cache_never_bypasses_changed_window_or_send_check(monkeypatch):
    from PIL import Image

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Test Group')
    ui.window = '1'
    ui.geometry = {'X': 0, 'Y': 0, 'WIDTH': 1000, 'HEIGHT': 700}
    frame = Image.new('RGB', (1000, 700), 'white')
    calls = []
    monkeypatch.setattr(ui, 'screen', lambda: frame)
    monkeypatch.setattr(ui, 'ocr', lambda *args: calls.append(1) or 'Test Group')
    assert ui.check(reuse_title=True)['state'] == 'ready'
    assert ui.check(reuse_title=True)['state'] == 'ready'
    assert len(calls) == 1
    assert ui.check()['state'] == 'ready'  # Sending always performs fresh OCR.
    assert len(calls) == 2
    frame.putpixel((400, 40), (0, 0, 0))
    assert ui.check(reuse_title=True)['state'] == 'ready'
    assert len(calls) == 3
    ui.window = '2'
    assert ui.check(reuse_title=True)['state'] == 'ready'
    assert len(calls) == 4
    ui._verified_at -= 301
    assert ui.check(reuse_title=True)['state'] == 'ready'
    assert len(calls) == 5


def test_timeout_is_not_classified_as_logout(monkeypatch):
    import subprocess

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Test Group')

    def timeout():
        raise subprocess.TimeoutExpired('scrot', 15)

    monkeypatch.setattr(ui, 'screen', timeout)
    assert ui.check()['reason'] == 'check_timeout'


def test_existing_incidents_migrate_without_losing_alert_history(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with db.connect(path) as connection:
        connection.execute(
            'CREATE TABLE wechat_incidents (id INTEGER PRIMARY KEY, reason TEXT NOT NULL, started_at TEXT NOT NULL, recovered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, message_id TEXT NOT NULL, retry_at TEXT NOT NULL, sent_at TEXT)'
        )
        connection.execute(
            'INSERT INTO wechat_incidents (reason,started_at,message_id,retry_at,sent_at) VALUES (?,?,?,?,?)',
            ('check_timeout', s.stamp(NOW), 'old-message', s.stamp(NOW), s.stamp(NOW)),
        )
    db.initialize(path)
    db.initialize(path)
    with db.connect(path) as connection:
        row = connection.execute('SELECT * FROM wechat_incidents').fetchone()
        assert row['sent_at'] == s.stamp(NOW)
        assert row['message_id'] == 'old-message'
        assert row['recovery_started_at'] is None


def test_small_login_window_is_recognized_and_never_ready(monkeypatch):
    from PIL import Image

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Test Group')
    monkeypatch.setattr(
        sender,
        'run',
        lambda *args: b'42' if args[1] == 'search' else b'X=10\nY=10\nWIDTH=360\nHEIGHT=480',
    )
    assert ui.locate()['WIDTH'] == 360
    monkeypatch.setattr(ui, 'screen', lambda: Image.new('RGB', (360, 480)))
    monkeypatch.setattr(ui, 'ocr', lambda *args: 'Confirm on Phone')
    assert ui.check(reuse_title=True)['reason'] == 'phone_confirmation_pending'
    with pytest.raises(sender.GuardError, match='phone_confirmation_pending'):
        ui.guard()
    monkeypatch.setattr(ui, 'ocr', lambda *args: 'Unknown dialog')
    assert ui.check()['state'] == 'blocked'


def test_phone_confirmation_email_is_immediate_and_once_per_prompt(conn, config, monkeypatch):
    sent = []
    monkeypatch.setattr(wechat.notifications, 'send', lambda cfg, mail: sent.append(mail))
    # Even an already-notified generic outage must not suppress the phone action.
    heartbeat(config, 'blocked', 'client_unavailable')
    wechat.monitor(conn, config, NOW)
    wechat.monitor(conn, config, NOW + timedelta(minutes=2))
    for second in (121, 126, 150):
        wechat.write_private(
            wechat.outbox(config) / 'health.json',
            dict(
                state='blocked',
                reason='phone_confirmation_pending',
                checked_at=(NOW + timedelta(seconds=second)).timestamp(),
                login_request_id='prompt-1',
            ),
        )
        wechat.monitor(conn, config, NOW + timedelta(seconds=second))
    assert len(sent) == 2
    assert '请在手机微信确认机器人登录' in str(sent[-1]['Subject'])
    assert '微信分身' in sent[-1].get_content()
    wechat.write_private(
        wechat.outbox(config) / 'health.json',
        dict(
            state='blocked',
            reason='phone_confirmation_pending',
            checked_at=(NOW + timedelta(minutes=20)).timestamp(),
            login_request_id='prompt-2',
        ),
    )
    wechat.monitor(conn, config, NOW + timedelta(minutes=20))
    assert len(sent) == 3


def test_login_button_requires_small_window_exact_label_and_green_background(monkeypatch):
    from PIL import Image, ImageDraw

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Group')
    image = Image.new('RGB', (300, 400), 'white')
    ImageDraw.Draw(image).rounded_rectangle((80, 270, 220, 310), radius=8, fill=(7, 193, 96))

    def button_ocr(label, psm):
        # Rounded white corners must not become black punctuation around Log In.
        assert label.getpixel((0, 0)) == 255
        assert psm == 7
        return 'Log In'

    monkeypatch.setattr(ui, 'ocr', button_ocr)
    assert ui.login_button(image) == (150, 290)
    assert all(isinstance(v, int) for v in ui.login_button(image))
    monkeypatch.setattr(ui, 'ocr', lambda *args: 'Switch Account')
    assert ui.login_button(image) is None
    monkeypatch.setattr(ui, 'ocr', lambda *args: 'Log In')
    assert ui.login_button(Image.new('RGB', (300, 400), 'white')) is None
    assert ui.login_button(Image.new('RGB', (1000, 700))) is None
    ImageDraw.Draw(image).rectangle((80, 200, 220, 240), fill=(7, 193, 96))
    assert ui.login_button(image) is None


def test_sparse_ocr_can_miss_startup_button_without_missing_login(monkeypatch):
    from PIL import Image, ImageDraw

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Group')
    image = Image.new('RGB', (300, 400), 'white')
    ImageDraw.Draw(image).rectangle((80, 270, 220, 310), fill=(7, 193, 96))
    monkeypatch.setattr(ui, 'screen', lambda: image)
    monkeypatch.setattr(ui, 'ocr', lambda frame, psm: 'Switch Account' if psm == 11 else 'Log In')
    assert ui.check()['reason'] == 'logged_out'


def test_phone_prompt_identity_survives_sender_reload_and_changes_after_recovery(tmp_path):
    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    state = tmp_path / 'login-state.json'
    first = sender.Desktop('Group', state).health_result('phone_confirmation_pending')
    ui = sender.Desktop('Group', state)
    assert (
        ui.health_result('phone_confirmation_pending')['login_request_id']
        == first['login_request_id']
    )
    ui.health_result('')
    assert (
        ui.health_result('phone_confirmation_pending')['login_request_id']
        != first['login_request_id']
    )


def test_login_click_is_bounded_and_does_not_claim_phone_confirmation(monkeypatch):
    from PIL import Image

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Group')
    clicked = []
    monkeypatch.setattr(ui, 'screen', lambda: Image.new('RGB', (300, 400)))
    monkeypatch.setattr(sender, 'run', lambda *args, **kwargs: b'')
    monkeypatch.setattr(sender.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(ui, 'login_button', lambda *args: (150, 290))
    monkeypatch.setattr(ui, 'click', lambda *args: clicked.append(args))
    monkeypatch.setattr(ui, 'check', lambda **kwargs: ui.health_result('logged_out'))
    assert ui.request_phone_login()['reason'] == 'logged_out'
    assert ui.request_phone_login()['reason'] == 'logged_out'
    assert clicked == [(150, 290)]


def test_expired_phone_prompt_is_not_automatically_renewed(monkeypatch):
    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Group')
    ui.health_result('phone_confirmation_pending')
    ui.login_state['requested_at'] = 1
    monkeypatch.setattr(ui, 'screen', lambda: pytest.fail('Must not renew an expired prompt'))
    assert ui.request_phone_login()['reason'] == 'logged_out'
    assert ui.login_state['pending']


def test_post_login_group_restore_requires_unique_candidate():
    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('PKU Digger Bot测试')
    header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    row = '1\t1\t1\t1\t40\t60\t300\t40\t95\tPKU Digger Bot 测试\n'
    assert ui.group_in_sidebar(header + row) == (155, 110)
    assert ui.group_in_sidebar(header + row.replace('PKU Digger Bot 测试', 'PKU Digge.…')) == (
        155,
        110,
    )
    assert ui.group_in_sidebar(header + row.replace('PKU Digger Bot 测试', 'PKU…')) is None
    assert ui.group_in_sidebar(header + row.replace('测试', '正式群')) is None
    assert ui.group_in_sidebar(header + row.replace('95', '20')) is None
    assert ui.group_in_sidebar(header + row + row.replace('1\t1\t1\t1', '1\t2\t1\t1')) is None


def test_group_restore_does_not_change_chat_outside_login_recovery(monkeypatch):
    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Group')
    monkeypatch.setattr(ui, 'screen', lambda: pytest.fail('Normal chat changes must stay manual'))
    assert ui.restore_group_after_login()['reason'] == 'target_not_verified'


@pytest.mark.parametrize('header_matches', [True, False])
def test_login_restore_requires_full_header_check_and_does_not_repeat_click(
    monkeypatch, header_matches
):
    from PIL import Image

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    ui = sender.Desktop('Group')
    ui.health_result('phone_confirmation_pending')
    clicks = []
    monkeypatch.setattr(ui, 'screen', lambda: Image.new('RGB', (917, 667)))
    monkeypatch.setattr(sender, 'run', lambda *args, **kwargs: b'')
    monkeypatch.setattr(sender.time, 'sleep', lambda *args: None)
    monkeypatch.setattr(ui, 'group_in_sidebar', lambda *args: (155, 110))
    monkeypatch.setattr(ui, 'click', lambda *args: clicks.append(args))
    monkeypatch.setattr(
        ui, 'check', lambda: ui.health_result('' if header_matches else 'target_not_verified')
    )
    assert ui.restore_group_after_login()['state'] == ('ready' if header_matches else 'blocked')
    ui.restore_group_after_login()
    assert clicks == [(155, 110)]


def test_prepared_dispatch_cannot_bypass_launch_time(conn, config):
    prepare(conn)
    with conn:
        conn.execute("INSERT INTO settings VALUES ('launch_day','2026-09-28')")
    boundary = datetime(2026, 9, 28, 4, tzinfo=timezone.utc)
    heartbeat(config, now=boundary - timedelta(seconds=1))
    assert wechat.dispatch_next(conn, config, boundary - timedelta(seconds=1)) is None
    assert not list(wechat.outbox(config).glob('requests/*.json'))
    assert conn.execute('SELECT COUNT(*) FROM wechat_deliveries').fetchone()[0] == 0
    heartbeat(config, now=boundary)
    assert wechat.dispatch_next(conn, config, boundary)['state'] == 'queued'


def test_formal_group_fullwidth_punctuation_and_member_count():
    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    target = '今天你滚了吗（pku版）'
    assert sender.target_matches('今天你滚了吗(pku版) (208)', target)
    assert sender.target_matches('今天 你滚了吗（pku版）（208）', target)
    assert not sender.target_matches('今天你滚了吗（测试版）(208)', target)
    assert not sender.target_matches('今天你滚了吗（pku版）二群', target)


def test_verified_title_reference_uses_only_group_name_not_member_count(monkeypatch):
    from PIL import Image

    spec = importlib.util.spec_from_file_location('sender', 'deploy/wechat/sender.py')
    sender = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sender)
    frame = Image.new('RGB', (917, 667), 'white')
    frame.putpixel((340, 45), (0, 0, 0))
    bounds = [325, 25, 485, 82]
    reference = dict(
        group='今天你滚了吗（pku版）',
        bounds=bounds,
        sha256=hashlib.sha256(frame.crop(bounds).tobytes()).hexdigest(),
    )
    ui = sender.Desktop(reference['group'], title_reference=reference)
    monkeypatch.setattr(ui, 'ocr', lambda *args: pytest.fail('Do not inspect group member count'))
    assert ui.reference_matches(frame)
    frame.putpixel((500, 45), (0, 0, 0))  # Membership and other suffix pixels can change.
    assert ui.reference_matches(frame)
    frame.putpixel((340, 45), (255, 255, 255))
    assert not ui.reference_matches(frame)
    frame.putpixel((340, 45), (0, 0, 0))
    ui.group = '另一个群'
    assert not ui.reference_matches(frame)
