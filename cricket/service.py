"""Small, transactional activity rules; all stored timestamps are UTC."""

import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat()


def parse(value):
    return datetime.fromisoformat(value)


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def text(value, limit, required=False):
    value = html.unescape(value or '').strip()
    if (required and not value) or len(value) > limit:
        raise ValueError(f'请填写必填项，并将文字控制在 {limit} 字以内。')
    return value


def url(value, domains=None):
    value = (value or '').strip()
    if not value:
        return ''
    parts = urlsplit(value)
    if (
        len(value) > 2048
        or parts.scheme != 'https'
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError('链接请使用完整的 HTTPS 地址。')
    if domains and not any(
        parts.hostname == d or parts.hostname.endswith('.' + d) for d in domains
    ):
        raise ValueError('听歌链接的平台不匹配，请粘贴对应音乐平台的分享链接。')
    return value


def track(form, side, review=False):
    result = {
        'artist': text(form.get(f'{side}_artist'), 160, True),
        'title': text(form.get(f'{side}_title'), 200, True),
        'netease': url(form.get(f'{side}_netease'), ['music.163.com', '163cn.tv'])
        if review
        else '',
        'apple': url(form.get(f'{side}_apple'), ['music.apple.com']) if review else '',
    }
    if review:
        result.update(
            album=text(form.get(f'{side}_album'), 200),
            artist_id=text(form.get(f'{side}_artist_id'), 200),
            version=text(form.get(f'{side}_version'), 160),
            artwork=url(form.get(f'{side}_artwork')),
            artwork_source=url(form.get(f'{side}_artwork_source')),
            sources=[url(s) for s in form.get(f'{side}_sources', '').splitlines() if s.strip()],
        )
        if len(result['sources']) > 8:
            raise ValueError('每首歌最多保留 8 个核对来源。')
        if not result['sources']:
            raise ValueError('请为两首歌分别保存至少一个核对来源；单一来源须由管理员人工确认。')
        if result['artwork'] and not result['artwork_source']:
            raise ValueError('使用封面时请同时填写封面发行来源。')
        if not result['netease'] and not result['apple'] and not form.get('allow_missing'):
            raise ValueError('两个听歌链接均缺失；请补齐一个或明确勾选允许全部缺失。')
        result['checked_at'] = stamp(utcnow())
        result['checked_by'] = 'admin'
        if result['apple']:
            result['apple_region'] = urlsplit(result['apple']).path.split('/')[1].upper()
    return result


def unpack(row):
    item = dict(row)
    for key in ('a', 'b'):
        item[key] = json.loads(item[key])
    return item


def nominate(db, form, now=None):
    a, b = track(form, 'a'), track(form, 'b')
    name = text(form.get('nominator'), 80, True)
    notes = text(form.get('notes'), 600)
    submission = form.get('submission_id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', submission):
        raise ValueError('提交页面已失效，请刷新后重试。')
    with db:
        db.execute(
            'INSERT OR IGNORE INTO nominations (submission_id,nominator,original,a,b,notes,created_at) VALUES (?,?,?,?,?,?,?)',
            (
                submission,
                name,
                encode({'a': a, 'b': b}),
                encode(a),
                encode(b),
                notes,
                stamp(now or utcnow()),
            ),
        )
        db.execute(
            """INSERT OR IGNORE INTO enrichment_jobs (nomination_id,status,updated_at)
            SELECT id,'queued',? FROM nominations WHERE submission_id=? AND status='pending'""",
            (stamp(now or utcnow()), submission),
        )


def review(db, nomination_id, form):
    a, b = track(form, 'a', True), track(form, 'b', True)
    if not form.get('verified'):
        raise ValueError('请确认已核对拼写、录音版本与发行信息。')
    if (
        a['artist'].casefold() == b['artist'].casefold()
        and a['title'].casefold() == b['title'].casefold()
        and a['version'] == b['version']
    ):
        raise ValueError('两首似乎是同一录音，请核对后再发布。')
    with db:
        changed = db.execute(
            "UPDATE nominations SET a=?,b=?,status='ready' WHERE id=? AND status IN ('pending','ready')",
            (encode(a), encode(b), nomination_id),
        ).rowcount
        if not changed:
            raise ValueError('该提名已排期或已跳过，不能修改历史投票。')
        db.execute(
            "UPDATE enrichment_jobs SET status='superseded',updated_at=? WHERE nomination_id=?",
            (stamp(utcnow()), nomination_id),
        )


def settings(db):
    return dict(db.execute('SELECT key,value FROM settings').fetchall())


def launch_pending(cfg, now):
    day = cfg.get('launch_day', '')
    if not day:
        return False
    starts = datetime.strptime(f'{day} {cfg["switch_time"]}', '%Y-%m-%d %H:%M').replace(
        tzinfo=SHANGHAI
    )
    return now < starts


def create_round(db, day, now=None, demo_window=None):
    """Consume only the contiguous reviewed queue prefix; never silently skip."""
    date = datetime.strptime(day, '%Y-%m-%d').date()
    now = now or utcnow()
    with db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id FROM rounds WHERE day=?', (day,)).fetchone()
        if existing:
            return existing['id']
        cfg = settings(db)
        if day < cfg.get('launch_day', ''):
            raise ValueError('该日期早于正式运行起始日。')
        time = datetime.strptime(cfg['switch_time'], '%H:%M').time()
        start = datetime.combine(date, time, SHANGHAI)
        cutoff = datetime.strptime(cfg['cutoff_time'], '%H:%M').time()
        end = datetime.combine(date + timedelta(days=1), cutoff, SHANGHAI)
        if demo_window:
            start, end = demo_window
        if now >= end:
            raise ValueError('该日期的投票时段已经结束，不能新建历史投票。')
        override = db.execute('SELECT count FROM overrides WHERE day=?', (day,)).fetchone()
        count = override['count'] if override else 1
        if count == 0:
            raise ValueError('这一天已暂停活动。')
        queue = db.execute(
            "SELECT * FROM nominations WHERE status IN ('pending','ready') ORDER BY created_at,id LIMIT ?",
            (count,),
        ).fetchall()
        selected = []
        for row in queue:
            if row['status'] != 'ready':
                break
            selected.append(row)
        if not selected:
            raise ValueError('队列为空，或队首仍待核对。请先审核或明确跳过。')
        cursor = db.execute(
            'INSERT INTO rounds (day,starts_at,ends_at) VALUES (?,?,?)',
            (day, stamp(start), stamp(end)),
        )
        round_id = cursor.lastrowid
        for position, row in enumerate(selected, 1):
            db.execute(
                'INSERT INTO matches (round_id,nomination_id,position,nominator,a,b) VALUES (?,?,?,?,?,?)',
                (round_id, row['id'], position, row['nominator'], row['a'], row['b']),
            )
            db.execute("UPDATE nominations SET status='scheduled' WHERE id=?", (row['id'],))
    return round_id


def cast_vote(db, match_id, voter, choice, now=None):
    now = now or utcnow()
    if choice not in ('a', 'b', 'clear'):
        raise ValueError('请选择一首歌。')
    with db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute(
            'SELECT r.* FROM rounds r JOIN matches m ON m.round_id=r.id WHERE m.id=?', (match_id,)
        ).fetchone()
        if not row or row['snapshot'] or not parse(row['starts_at']) <= now < parse(row['ends_at']):
            raise ValueError('本轮尚未开始或已经截止，不能修改投票。')
        if choice == 'clear':
            db.execute('DELETE FROM votes WHERE match_id=? AND voter=?', (match_id, voter))
        else:
            db.execute(
                'INSERT INTO votes VALUES (?,?,?,?) ON CONFLICT(match_id,voter) DO UPDATE SET choice=excluded.choice,updated_at=excluded.updated_at',
                (match_id, voter, choice, stamp(now)),
            )


def tally(db, round_id):
    matches = [
        unpack(r)
        for r in db.execute('SELECT * FROM matches WHERE round_id=? ORDER BY position', (round_id,))
    ]
    for m in matches:
        counts = dict(
            db.execute(
                'SELECT choice,COUNT(*) FROM votes WHERE match_id=? GROUP BY choice', (m['id'],)
            )
        )
        m['votes_a'], m['votes_b'] = counts.get('a', 0), counts.get('b', 0)
        total = m['votes_a'] + m['votes_b']
        m['outcome'] = (
            'zero'
            if total == 0
            else 'tie'
            if m['votes_a'] == m['votes_b']
            else 'a'
            if m['votes_a'] > m['votes_b']
            else 'b'
        )
    return matches


def close_due(db, now=None):
    now = now or utcnow()
    # Most page reads have nothing to close: avoid reserving SQLite's writer lock.
    if not db.execute(
        'SELECT 1 FROM rounds WHERE ends_at<=? AND snapshot IS NULL LIMIT 1', (stamp(now),)
    ).fetchone():
        return 0
    with db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute(
            'SELECT * FROM rounds WHERE ends_at<=? AND snapshot IS NULL', (stamp(now),)
        ).fetchall()
        for row in rows:
            db.execute(
                'UPDATE rounds SET snapshot=?,closed_at=? WHERE id=?',
                (encode(tally(db, row['id'])), stamp(now), row['id']),
            )
    return len(rows)


def round_data(db, day, voter=None, now=None, admin=False):
    now = now or utcnow()
    close_due(db, now)
    row = db.execute('SELECT * FROM rounds WHERE day=?', (day,)).fetchone()
    if not row or (now < parse(row['starts_at']) and not admin):
        return None
    result = dict(row)
    result['open'] = not row['snapshot'] and parse(row['starts_at']) <= now < parse(row['ends_at'])
    result['future'] = now < parse(row['starts_at'])
    if row['snapshot']:
        result['matches'] = json.loads(row['snapshot'])
    elif admin:
        result['matches'] = tally(db, row['id'])
    else:
        # No live tally reaches public HTML before the deadline.
        result['matches'] = [
            unpack(m)
            for m in db.execute(
                'SELECT * FROM matches WHERE round_id=? ORDER BY position', (row['id'],)
            )
        ]
    for match in result['matches']:
        vote = db.execute(
            'SELECT choice FROM votes WHERE match_id=? AND voter=?', (match['id'], voter)
        ).fetchone()
        match['choice'] = vote['choice'] if vote else None
    return result


def active_rounds(db, now=None):
    now = now or utcnow()
    close_due(db, now)
    days = db.execute(
        'SELECT day FROM rounds WHERE snapshot IS NULL AND starts_at<=? AND ends_at>? ORDER BY starts_at',
        (stamp(now), stamp(now)),
    ).fetchall()
    return [round_data(db, row['day'], now=now, admin=True) for row in days]


def winner_label(match):
    winner = match[match['outcome']]
    a, b = match['a'], match['b']
    aid, bid = a.get('artist_id', ''), b.get('artist_id', '')
    same_catalogue = aid and bid and aid.split(':')[0] == bid.split(':')[0]
    same_artist = aid == bid if same_catalogue else a['artist'].casefold() == b['artist'].casefold()
    if not same_artist:
        return winner['artist']
    if a.get('album') and b.get('album') and a['album'].casefold() != b['album'].casefold():
        return winner['album']
    return winner['title']


def congratulations(matches):
    winners = [winner_label(m) for m in matches if m['outcome'] in ('a', 'b')]
    lines = ['让我们恭喜' + '和'.join(winners) + '👏'] if winners else []
    for m in matches:
        if m['outcome'] == 'tie':
            lines.append(f'第 {m["position"]} 组平局，双方都很能打👏')
        elif m['outcome'] == 'zero':
            lines.append(f'第 {m["position"]} 组暂无有效投票。')
    return '\n'.join(lines)


def nomination_message(round_, base_url):
    rows = [
        f'{m["a"]["artist"]} - {m["a"]["title"]} vs {m["b"]["artist"]} - {m["b"]["title"]} 来自 {m["nominator"]}'
        for m in round_['matches']
    ]
    return (
        '今天的曲目：'
        + ' /\n'.join(rows)
        + f'\n投票链接：{base_url.rstrip("/")}/rounds/{round_["day"]}'
    )


def prepare_dispatch(db, day, base_url, now=None):
    now = now or utcnow()
    cfg = settings(db)
    if day < cfg.get('launch_day', '') or launch_pending(cfg, now):
        return []
    existing = db.execute('SELECT payload FROM dispatches WHERE day=?', (day,)).fetchone()
    current = round_data(db, day, now=now)
    if current and not current['open']:
        current = None
    if existing:
        messages = json.loads(existing['payload'])
        if current and not any(m.get('text', '').startswith('今天的曲目：') for m in messages):
            # Results can go out even when today's nominations are still unresolved.
            # Append the later ready round without rewriting already-sent steps.
            messages.append({'kind': 'text', 'text': nomination_message(current, base_url)})
            with db:
                db.execute(
                    "UPDATE dispatches SET payload=?,status='prepared' WHERE day=? AND payload=?",
                    (encode(messages), day, existing['payload']),
                )
            return json.loads(
                db.execute('SELECT payload FROM dispatches WHERE day=?', (day,)).fetchone()[0]
            )
        return messages
    yesterday = (datetime.strptime(day, '%Y-%m-%d').date() - timedelta(days=1)).isoformat()
    previous_row = db.execute(
        'SELECT day FROM rounds WHERE starts_at>=? AND starts_at<? ORDER BY starts_at DESC LIMIT 1',
        (
            stamp(
                datetime.combine(
                    datetime.strptime(yesterday, '%Y-%m-%d').date(), datetime.min.time(), SHANGHAI
                )
            ),
            stamp(
                datetime.combine(
                    datetime.strptime(day, '%Y-%m-%d').date(), datetime.min.time(), SHANGHAI
                )
            ),
        ),
    ).fetchone()
    previous = round_data(db, previous_row['day'], now=now) if previous_row else None
    messages = []
    if previous and previous['snapshot'] and yesterday >= cfg.get('launch_day', ''):
        for page in range((len(previous['matches']) + 3) // 4):
            messages.append(
                {
                    'kind': 'image',
                    'url': f'{base_url.rstrip("/")}/rounds/{previous["day"]}/result/{page + 1}.png',
                }
            )
        messages.append({'kind': 'text', 'text': congratulations(previous['matches'])})
    if current:
        messages.append({'kind': 'text', 'text': nomination_message(current, base_url)})
    # An empty or unresolved queue must not suppress yesterday's results.
    if messages:
        with db:
            db.execute(
                'INSERT OR IGNORE INTO dispatches VALUES (?,?,?,?)',
                (day, encode(messages), 'prepared', stamp(now)),
            )
    return messages


def tick(db, base_url, now=None):
    now = now or utcnow()
    closed = close_due(db, now)
    cfg = settings(db)
    local = now.astimezone(SHANGHAI)
    if (
        cfg['automatic'] != '1'
        or local.strftime('%H:%M') < cfg['switch_time']
        or launch_pending(cfg, now)
    ):
        return {
            'closed': closed,
            'prepared': False,
            'note': '自动排期未启用，或未到正式运行／每日切换时间。',
        }
    day = local.date().isoformat()
    note = ''
    try:
        create_round(db, day, now)
    except ValueError as error:
        note = str(error)
    messages = prepare_dispatch(db, day, base_url, now)
    return {
        'closed': closed,
        'prepared': bool(messages),
        'note': note,
        'messages': messages,
        'wechat_sent': bool(
            db.execute("SELECT 1 FROM dispatches WHERE day=? AND status='sent'", (day,)).fetchone()
        ),
    }
