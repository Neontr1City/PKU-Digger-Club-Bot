"""Private file outbox, durable delivery progress and QQ email incident alerts."""

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from . import notifications, poster
from . import service as s

REASONS = {
    'heartbeat_missing': '云端发送程序没有更新状态，可能已经停止。',
    'client_unavailable': '暂时无法检查微信界面；这不代表已确认账号退出。',
    'check_timeout': '微信界面检查超时，推送已暂停；这不代表已确认账号退出。',
    'logged_out': '微信已掉线，需要在云端桌面重新登录并在手机上确认。',
    'phone_confirmation_pending': '云端正在等待手机确认，请打开机器人账号所在的微信分身，确认登录。',
    'qr_login_required': '微信需要重新扫码，请打开云端微信，用机器人账号所在的微信分身扫码登录。',
    'target_not_verified': '当前窗口无法确认是指定群聊；请打开正确的群聊。',
    'draft_present': '输入框有未发送的草稿，请先处理草稿。',
    'send_button_not_ready': '微信发送按钮尚未就绪，已停止发送。',
    'text_verification_failed': '输入内容校验未通过，已停止发送。',
    'send_not_confirmed': '点击发送后未能确认，请先检查群消息，避免重复发送。',
    'bubble_not_verified': '发送后的消息未能确认，请先检查群消息，避免重复发送。',
    'interrupted_send': '发送过程中程序中断，请先检查群消息，避免重复发送。',
    'image_preview_not_verified': '结果图粘贴后校验未通过，已停止发送。',
    'image_send_not_confirmed': '结果图发送后未能确认，请先检查群消息。',
    'desktop_error': '界面操作未完成，需要检查云端微信。',
    'invalid_target_or_expired': '发送目标不符或消息已过期，已停止发送。',
}


def enabled(config):
    return bool(config.get('WECHAT_SEND_ENABLED')) and not config.get('DEMO_MODE', False)


def outbox(config):
    return Path(config['WECHAT_OUTBOX'])


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as file:
            file.write(s.encode(data))
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        # The production app is root; the desktop is an unprivileged UID.
        if os.geteuid() == 0:
            os.chown(path.parent, 10001, 10001)
            os.chown(temporary, 10001, 10001)
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def health(config, now=None):
    now = now or s.utcnow()
    value = read_json(outbox(config) / 'health.json')
    if not value or not 0 <= now.timestamp() - value.get('checked_at', 0) <= 180:
        return dict(state='blocked', reason='heartbeat_missing', checked_at=None)
    return value


def materialize(conn, config, message):
    if message['kind'] == 'text':
        text = message['text']
        if not text.strip() or len(text) > 6000:
            raise ValueError('Unsupported message length')
        return dict(kind='text', text=text)
    url = urlsplit(message['url'])
    base = urlsplit(config['PUBLIC_BASE_URL'])
    match = re.fullmatch(
        r'/rounds/(\d{4}-\d{2}-\d{2}(?:-test-\d{4})?)/result/([1-9]\d*)\.png', url.path
    )
    if (url.scheme, url.netloc) != (base.scheme, base.netloc) or not match or url.query:
        raise ValueError('Only local frozen result images are allowed')
    round_ = s.round_data(conn, match[1])
    if not round_ or not round_['snapshot']:
        raise ValueError('A frozen result is required')
    image = poster.cached_path(
        round_, int(match[2]), config.get('RESULT_FONT', ''), Path(config['OUTPUT_DIR'])
    ).read_bytes()
    return dict(kind='image', png=base64.b64encode(image).decode())


def dispatch_next(conn, config, now=None):
    if not enabled(config):
        return None
    now = now or s.utcnow()
    if s.launch_pending(s.settings(conn), now):
        return None
    day = now.astimezone(s.SHANGHAI).date().isoformat()
    group = config.get('WECHAT_GROUP', '').strip()
    if not group:
        raise ValueError('A verified WeChat group is required')
    # Never catch up old "today" messages after a long outage.
    dispatch = conn.execute('SELECT * FROM dispatches WHERE day=?', (day,)).fetchone()
    if not dispatch or dispatch['status'] == 'sent':
        return None
    messages = json.loads(dispatch['payload'])
    for position, message in enumerate(messages):
        key = hashlib.sha256(f'{day}:{position}:{group}'.encode()).hexdigest()
        row = conn.execute('SELECT * FROM wechat_deliveries WHERE key=?', (key,)).fetchone()
        if row:
            if row['state'] in ('confirmed', 'skipped'):
                continue
            receipt = read_json(outbox(config) / 'receipts' / (key + '.json'))
            if receipt:
                if (
                    receipt.get('key') != key
                    or receipt.get('digest') != row['digest']
                    or receipt.get('group') != group
                ):
                    return {'state': 'blocked', 'reason': 'receipt_mismatch'}
                state = receipt.get('state')
                if state not in ('confirmed', 'blocked', 'uncertain'):
                    return None
                with conn:
                    conn.execute(
                        'UPDATE wechat_deliveries SET state=?,reason=?,updated_at=? WHERE key=? AND state!=?',
                        (state, receipt.get('reason', ''), s.stamp(now), key, state),
                    )
                if state == 'confirmed':
                    continue
                return {'state': state, 'reason': receipt.get('reason', '')}
            return {'state': row['state']}
        if health(config, now)['state'] != 'ready':
            return None
        payload = materialize(conn, config, message)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        expiry = (
            now.astimezone(s.SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        ).timestamp()
        request = dict(key=key, digest=digest, group=group, payload=payload, expires_at=expiry)
        # A transaction prevents two workers creating different requests for the same step.
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM wechat_deliveries WHERE key=?', (key,)).fetchone():
                return None
            write_private(outbox(config) / 'requests' / (key + '.json'), request)
            conn.execute(
                'INSERT INTO wechat_deliveries VALUES (?,?,?,?,?,?,?,?)',
                (key, day, position, group, digest, 'queued', '', s.stamp(now)),
            )
            conn.execute("UPDATE dispatches SET status='sending' WHERE day=?", (day,))
        return {'state': 'queued', 'position': position}
    with conn:
        conn.execute(
            "UPDATE dispatches SET status='sent' WHERE day=? AND payload=?",
            (day, dispatch['payload']),
        )
    return {'state': 'sent', 'day': day}


def notify_phone_login(conn, config, current, now):
    request_id = current.get('login_request_id')
    if not request_id or not notifications.enabled(config):
        return None
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            'INSERT OR IGNORE INTO wechat_login_notifications (request_id,retry_at,message_id) VALUES (?,?,?)',
            (request_id, s.stamp(now), notifications.make_msgid()),
        )
        row = conn.execute(
            'SELECT * FROM wechat_login_notifications WHERE request_id=?', (request_id,)
        ).fetchone()
        if row['sent_at'] or row['attempts'] >= 3 or s.parse(row['retry_at']) > now:
            return None
        conn.execute(
            'UPDATE wechat_login_notifications SET attempts=attempts+1,retry_at=? WHERE request_id=?',
            (s.stamp(now + timedelta(seconds=30)), request_id),
        )
    body = (
        '云端微信正在等待手机确认登录。\n\n'
        '请打开华为手机上的微信分身（机器人账号），在登录确认提示中点击“登录”／“确认登录”即可。\n'
        '不需要切换主号，也不需要向机器人发送密码。\n\n'
        '如果提示已过期或手机没有出现提示，请从管理页打开云端微信查看当前状态：\n'
        + config['PUBLIC_BASE_URL'].rstrip('/')
        + '/admin\n\n'
        '这次手机确认只提醒一次。登录完成后自动恢复；已确认发送的群消息不会重复发送。'
    )
    try:
        notifications.send(
            config,
            notifications.message(config, '请在手机微信确认机器人登录', body, row['message_id']),
        )
    except Exception:
        return {'state': 'mail_failed', 'reason': 'phone_confirmation_pending'}
    with conn:
        conn.execute(
            'UPDATE wechat_login_notifications SET sent_at=? WHERE request_id=?',
            (s.stamp(now), request_id),
        )
    return {'state': 'mail_sent', 'reason': 'phone_confirmation_pending'}


def monitor(conn, config, now=None, *, test=False):
    """One incident per outage; two-minute debounce and bounded SMTP backoff."""
    if not enabled(config):
        return None
    now = now or s.utcnow()
    current = health(config, now)
    if current.get('reason') == 'phone_confirmation_pending':
        with conn:
            conn.execute(
                'UPDATE wechat_incidents SET recovery_started_at=NULL WHERE recovered_at IS NULL'
            )
        return notify_phone_login(conn, config, current, now)
    # A send uncertainty requires intervention even if the client still looks online.
    problem = conn.execute(
        "SELECT reason FROM wechat_deliveries WHERE state IN ('blocked','uncertain') ORDER BY updated_at LIMIT 1"
    ).fetchone()
    reason = problem['reason'] if problem else current.get('reason', '')
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        incident = conn.execute(
            'SELECT * FROM wechat_incidents WHERE recovered_at IS NULL'
        ).fetchone()
        if not reason:
            if incident:
                if not incident['recovery_started_at']:
                    conn.execute(
                        'UPDATE wechat_incidents SET recovery_started_at=? WHERE id=?',
                        (s.stamp(now), incident['id']),
                    )
                elif now - s.parse(incident['recovery_started_at']) >= timedelta(minutes=2):
                    conn.execute(
                        'UPDATE wechat_incidents SET recovered_at=? WHERE id=?',
                        (s.stamp(now), incident['id']),
                    )
            return None
        if not incident:
            conn.execute(
                'INSERT INTO wechat_incidents (reason,started_at,retry_at,message_id) VALUES (?,?,?,?)',
                (
                    reason,
                    s.stamp(now),
                    s.stamp(now + timedelta(minutes=2)),
                    notifications.make_msgid(),
                ),
            )
            return {'state': 'observing', 'reason': reason}
        if incident['recovery_started_at']:
            conn.execute(
                'UPDATE wechat_incidents SET recovery_started_at=NULL WHERE id=?',
                (incident['id'],),
            )
        # Repeated brief recoveries are one resource problem, not fresh outages.
        category = ('client_unavailable', 'check_timeout', 'heartbeat_missing')
        reasons = category if reason in category else (reason,)
        last = conn.execute(
            'SELECT MAX(sent_at) FROM wechat_incidents WHERE reason IN ('
            + ','.join('?' for _ in reasons)
            + ')',
            reasons,
        ).fetchone()[0]
        if last and now - s.parse(last) < timedelta(minutes=30):
            return None
        if (
            incident['sent_at']
            or s.parse(incident['retry_at']) > now
            or not notifications.enabled(config)
        ):
            return None
        attempt = incident['attempts'] + 1
        conn.execute(
            'UPDATE wechat_incidents SET attempts=?,retry_at=? WHERE id=?',
            (
                attempt,
                s.stamp(now + timedelta(minutes=min(60, 15 * 2 ** min(attempt - 1, 2)))),
                incident['id'],
            ),
        )
    body = (
        REASONS.get(reason, '微信推送已暂停，需要检查云端微信。')
        + '\n\n检测时间（北京时间）：'
        + s.parse(incident['started_at']).astimezone(s.SHANGHAI).strftime('%Y-%m-%d %H:%M')
        + '\n目标群：'
        + config['WECHAT_GROUP']
        + '\n\n先查看后台当前状态。若已恢复在线，无需操作；确认登录失效时才需要重新登录。恢复后会继续当天尚未发送的消息，发送结果不确定的项仍需人工核对，不会自动重发。'
        + '\n短暂恢复后再次失败按同一故障处理；同类提醒最多每 30 分钟一次。'
        + '\n\n处理入口（管理员登录）：'
        + config['PUBLIC_BASE_URL'].rstrip('/')
        + '/admin'
    )
    if test:
        body = '这是一封掉线提醒演练邮件，当前微信并未掉线，无需重新登录。\n\n' + body
    try:
        notifications.send(
            config,
            notifications.message(
                config,
                '微信掉线提醒演练'
                if test
                else ('微信登录已失效' if reason == 'logged_out' else '微信推送检查异常'),
                body,
                incident['message_id'],
            ),
        )
    except Exception:
        return {'state': 'mail_failed'}
    with conn:
        conn.execute(
            'UPDATE wechat_incidents SET sent_at=? WHERE id=?', (s.stamp(now), incident['id'])
        )
    return {'state': 'mail_sent', 'reason': reason}


def status(conn, config):
    if not enabled(config):
        return None
    state = health(config)
    return dict(
        **state,
        group=config['WECHAT_GROUP'],
        description='在线，等待每日推送'
        if state['state'] == 'ready'
        else REASONS.get(state['reason'], '推送暂停'),
        deliveries=conn.execute(
            'SELECT * FROM wechat_deliveries ORDER BY updated_at DESC LIMIT 12'
        ).fetchall(),
    )


def resolve_delivery(conn, config, key, action, now=None):
    now = now or s.utcnow()
    row = conn.execute('SELECT * FROM wechat_deliveries WHERE key=?', (key,)).fetchone()
    if not enabled(config) or not row or row['state'] not in ('blocked', 'uncertain'):
        raise ValueError('此消息没有待处理的发送异常。')
    if now - s.parse(row['updated_at']) < timedelta(minutes=5):
        raise ValueError('请等待异常记录满五分钟，再核对处理。')
    if action not in ('confirm', 'retry', 'skip'):
        raise ValueError('请选择确认收到、重试或放弃过期发送。')
    if action == 'skip' and row['day'] >= now.astimezone(s.SHANGHAI).date().isoformat():
        raise ValueError('只有跨日过期的消息可以放弃补发。')
    receipt = outbox(config) / 'receipts' / (key + '.json')
    if action == 'retry':
        if row['day'] != now.astimezone(s.SHANGHAI).date().isoformat():
            raise ValueError('跨日消息不能自动重发，请单独核对旧活动。')
        receipt.unlink(missing_ok=True)
        state = 'queued'
    else:
        write_private(
            receipt,
            dict(
                key=key,
                digest=row['digest'],
                group=row['target'],
                state='skipped' if action == 'skip' else 'confirmed',
                evidence='admin_skipped_expired' if action == 'skip' else 'admin_confirmed',
            ),
        )
        state = 'skipped' if action == 'skip' else 'confirmed'
    with conn:
        if action == 'skip':
            conn.execute("UPDATE dispatches SET status='expired' WHERE day=?", (row['day'],))
        conn.execute(
            'UPDATE wechat_deliveries SET state=?,reason=?,updated_at=? WHERE key=?',
            (state, '', s.stamp(now), key),
        )
