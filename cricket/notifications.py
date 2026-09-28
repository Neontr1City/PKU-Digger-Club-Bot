"""QQ SMTP notifications for actionable nominations; no public mail endpoint."""

import json
import smtplib
import ssl
from datetime import timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import service as s


def enabled(config):
    return bool(config.get('ADMIN_EMAIL_ENABLED')) and not config.get('DEMO_MODE', False)


def addresses(config):
    sender = config.get('QQ_SMTP_EMAIL', '').strip()
    recipient = config.get('ADMIN_EMAIL_TO', '').strip() or sender
    if not sender or not config.get('QQ_SMTP_AUTH_CODE'):
        raise ValueError('请配置 QQ 邮箱地址和 SMTP 授权码。')
    for value in (sender, recipient):
        address = Address(addr_spec=value)
        if not address.username or not address.domain:
            raise ValueError('请填写完整的邮箱地址。')
    return sender, recipient


def message(config, subject, body, message_id=None):
    sender, recipient = addresses(config)
    mail = EmailMessage()
    mail['From'] = Address('PKU Digger Club', addr_spec=sender)
    mail['To'] = recipient
    mail['Subject'] = '[PKU Digger Club] ' + subject
    mail['Date'] = formatdate(localtime=False)
    mail['Message-ID'] = message_id or make_msgid()
    mail.set_content(body)
    return mail


def send(config, mail):
    sender, recipient = addresses(config)
    client = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15, context=ssl.create_default_context())
    try:
        client.login(sender, config['QQ_SMTP_AUTH_CODE'])
        refused = client.send_message(mail, from_addr=sender, to_addrs=[recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
        # A QUIT failure after acceptance must not turn a successful send into a retry.
        try:
            client.quit()
        except (OSError, smtplib.SMTPException):
            pass
    finally:
        client.close()


def process_next(conn, config, now=None):
    if not enabled(config):
        return None
    now = now or s.utcnow()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            """SELECT n.id,n.original,j.report,e.attempts,e.message_id FROM nominations n
            JOIN enrichment_jobs j ON j.nomination_id=n.id
            LEFT JOIN email_notifications e ON e.nomination_id=n.id
            WHERE n.status='pending' AND
              (j.status='review' OR (j.status='error' AND json_extract(j.report,'$.attempt')>=3))
              AND (e.nomination_id IS NULL OR (e.status!='sent' AND e.retry_at<=?))
            ORDER BY n.created_at,n.id LIMIT 1""",
            (s.stamp(now),),
        ).fetchone()
        if not row:
            return None
        attempt = (row['attempts'] or 0) + 1
        message_id = row['message_id'] or make_msgid()
        retry_at = s.stamp(now + timedelta(minutes=min(60, 15 * 2 ** min(attempt - 1, 2))))
        conn.execute(
            """INSERT INTO email_notifications
            (nomination_id,status,attempts,message_id,retry_at,updated_at)
            VALUES (?,'sending',?,?,?,?) ON CONFLICT(nomination_id) DO UPDATE SET
            status='sending',attempts=excluded.attempts,retry_at=excluded.retry_at,
            updated_at=excluded.updated_at""",
            (row['id'], attempt, message_id, retry_at, s.stamp(now)),
        )
    try:
        original, report = json.loads(row['original']), json.loads(row['report'])
        lines = [f'提名 #{row["id"]} 需要你处理：', '']
        for side in ('a', 'b'):
            track = original[side]
            lines.append(f'{side.upper()}：{track["artist"]} — {track["title"]}')
        lines.extend(['', '原因：'])
        if report.get('error'):
            lines.append(report['error'])
        for side, result in report.get('sides', {}).items():
            if not result.get('resolved'):
                lines.extend(f'{side.upper()}：{reason}' for reason in result.get('reasons', []))
        lines.extend(
            [
                '',
                '此提名未就绪，排期到这一组时会暂停；可以核对、重新查找或明确跳过。',
                '处理入口（需要管理员登录）：',
                f'{config["PUBLIC_BASE_URL"].rstrip("/")}/admin/nomination/{row["id"]}',
                '',
                '同一提名仅通知一次。缺少一个平台链接或封面不会单独触发通知。',
            ]
        )
        mail = message(config, f'提名 #{row["id"]} 需要处理', '\n'.join(lines), message_id)
        send(config, mail)
    except Exception:
        # Provider exceptions may include addresses, credentials or message content.
        state = 'failed'
    else:
        state = 'sent'
    with conn:
        conn.execute(
            'UPDATE email_notifications SET status=?,updated_at=? WHERE nomination_id=? AND attempts=?',
            (state, s.stamp(s.utcnow()), row['id'], attempt),
        )
    return {'notification_id': row['id'], 'status': state}


def send_test(config):
    if not enabled(config):
        raise ValueError('邮件通知未启用，或当前为隔离演示环境。')
    send(
        config,
        message(
            config,
            '管理员通知测试',
            '这是一封连接测试邮件，不代表有待处理提名。\n'
            '以后只有需要管理员介入的提名才会触发通知。\n'
            + config['PUBLIC_BASE_URL'].rstrip('/')
            + '/admin',
        ),
    )
