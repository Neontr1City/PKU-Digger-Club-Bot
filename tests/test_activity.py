import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from cricket import create_app, db, poster
from cricket import service as s

NOW = datetime(2026, 9, 27, 11, tzinfo=timezone.utc)
DAY = '2026-09-27'


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'activity.sqlite3'
    db.initialize(path)
    connection = db.connect(path)
    yield connection
    connection.close()


def form(**changes):
    fields = dict(
        submission_id=secrets.token_hex(16),
        nominator='样本听众',
        a_artist='演出者 A',
        a_title='曲目 A',
        b_artist='演出者 B',
        b_title='曲目 B',
        a_album='专辑 A',
        b_album='专辑 B',
        a_sources='https://example.com/release/a',
        b_sources='https://example.com/release/b',
        verified='1',
        allow_missing='1',
    )
    fields.update(changes)
    return fields


def add(conn, ready=True, **changes):
    fields = form(**changes)
    s.nominate(conn, fields, NOW)
    id_ = conn.execute('SELECT MAX(id) FROM nominations').fetchone()[0]
    if ready:
        s.review(conn, id_, fields)
    return id_, fields


def start(conn, count=1, day=DAY, now=NOW):
    with conn:
        conn.execute('INSERT OR REPLACE INTO overrides VALUES (?,?)', (day, count))
    return s.create_round(conn, day, now)


def test_nomination_replay_and_original_evidence(conn):
    fields = form(a_artist='Mötley Crüe', nominator='示例听众&#x20;')
    s.nominate(conn, fields, NOW)
    s.nominate(conn, fields, NOW)
    assert conn.execute('SELECT COUNT(*) FROM nominations').fetchone()[0] == 1
    s.review(conn, 1, dict(fields, a_title='正式曲名'))
    row = conn.execute('SELECT * FROM nominations').fetchone()
    assert row['nominator'] == '示例听众'
    assert json.loads(row['original'])['a']['title'] == '曲目 A'
    assert json.loads(row['a'])['title'] == '正式曲名'
    assert json.loads(row['a'])['sources'] == ['https://example.com/release/a']


def test_fifo_blocks_unreviewed_head_and_explicit_skip(conn):
    add(conn, ready=False)
    add(conn)
    with pytest.raises(ValueError, match='队首'):
        start(conn, 2)
    with conn:
        conn.execute("UPDATE nominations SET status='skipped' WHERE id=1")
    id_ = start(conn, 2)
    assert (
        conn.execute('SELECT nomination_id FROM matches WHERE round_id=?', (id_,)).fetchone()[0]
        == 2
    )
    assert s.create_round(conn, DAY, NOW) == id_
    assert conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 1


def test_ready_prefix_stops_before_pending_and_snapshot_immutable(conn):
    _, fields = add(conn)
    add(conn, ready=False)
    add(conn)
    start(conn, 3)
    assert conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 1
    with pytest.raises(ValueError, match='不能修改'):
        s.review(conn, 1, dict(fields, a_title='不应修改'))
    assert s.round_data(conn, DAY, now=NOW)['matches'][0]['a']['title'] == '曲目 A'


def test_vote_change_clear_multiple_groups_and_deadline(conn):
    add(conn)
    add(conn)
    id_ = start(conn, 2)
    s.cast_vote(conn, 1, 'one', 'a', NOW)
    s.cast_vote(conn, 1, 'one', 'a', NOW)
    s.cast_vote(conn, 1, 'one', 'b', NOW)
    s.cast_vote(conn, 2, 'one', 'a', NOW)
    assert [(m['votes_a'], m['votes_b']) for m in s.tally(conn, id_)] == [(0, 1), (1, 0)]
    public = s.round_data(conn, DAY, 'one', NOW)
    assert 'votes_a' not in public['matches'][0]
    assert public['matches'][0]['choice'] == 'b'
    s.cast_vote(conn, 1, 'one', 'clear', NOW)
    end = s.parse(public['ends_at'])
    for time in (
        end,
        end + timedelta(seconds=1),
        s.parse(public['starts_at']) - timedelta(seconds=1),
    ):
        with pytest.raises(ValueError):
            s.cast_vote(conn, 1, 'one', 'a', time)
    assert s.close_due(conn, end) == 1
    assert s.close_due(conn, end) == 0
    closed = s.round_data(conn, DAY, now=end)
    assert [m['outcome'] for m in closed['matches']] == ['zero', 'a']
    assert closed['matches'][1]['votes_a'] == 1


@pytest.mark.parametrize(
    'album_a,album_b,expected',
    [('第一张', '第二张', '第一张'), ('相同', '相同', '曲目 A'), ('', '第二张', '曲目 A')],
)
def test_same_artist_winner_name(album_a, album_b, expected):
    match = dict(
        a=dict(artist='同名', title='曲目 A', album=album_a),
        b=dict(artist='同名', title='曲目 B', album=album_b),
        outcome='a',
    )
    assert s.winner_label(match) == expected
    match['a']['artist_id'], match['b']['artist_id'] = 'mb:1', 'mb:2'
    assert s.winner_label(match) == '同名'  # distinct artists sharing display name


def test_tie_zero_and_multiple_winners(conn):
    for _ in range(4):
        add(conn)
    id_ = start(conn, 4)
    for match_id in (1, 2, 3):
        s.cast_vote(conn, match_id, 'one', 'a', NOW)
    s.cast_vote(conn, 3, 'two', 'b', NOW)
    text = s.congratulations(s.tally(conn, id_))
    assert text.startswith('让我们恭喜演出者 A和演出者 A👏🏻')
    assert '第 3 组平局' in text and '第 4 组暂无有效投票' in text


def test_daily_bundle_order_and_repeat_does_not_consume_queue(conn):
    for _ in range(3):
        add(conn)
    start(conn, day='2026-09-26', now=NOW - timedelta(days=1))
    assert not s.tick(conn, 'https://example.com', NOW)['prepared']
    with conn:
        conn.execute("UPDATE settings SET value='1' WHERE key='automatic'")
    result = s.tick(conn, 'https://example.com', NOW)
    assert [m['kind'] for m in result['messages']] == ['image', 'text', 'text']
    assert '2026-09-26/result/1.png' in result['messages'][0]['url']
    assert '投票链接：https://example.com/rounds/2026-09-27' in result['messages'][2]['text']
    assert result['wechat_sent'] is False
    assert s.tick(conn, 'https://example.com', NOW)['messages'] == result['messages']
    assert conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 2
    assert conn.execute('SELECT COUNT(*) FROM dispatches').fetchone()[0] == 1


def test_pause_empty_and_future(conn):
    with pytest.raises(ValueError, match='队列为空'):
        start(conn)
    add(conn)
    with pytest.raises(ValueError, match='暂停'):
        start(conn, 0)
    start(conn, day='2026-09-28')
    assert s.round_data(conn, '2026-09-28', now=NOW) is None
    assert s.round_data(conn, '2026-09-28', now=NOW, admin=True)['future']


def test_release_verification_and_link_validation(conn):
    id_, fields = add(conn, ready=False)
    for changes in (
        {'a_sources': ''},
        {'a_apple': 'https://evil.test/song'},
        {'verified': ''},
        {'allow_missing': ''},
        {'a_artwork': 'https://example.com/image.png'},
        {'a_sources': 'javascript:alert(1)'},
    ):
        with pytest.raises(ValueError):
            s.review(conn, id_, dict(fields, **changes))


def test_result_png_pagination_and_long_chinese_titles(conn):
    for _ in range(5):
        add(conn, a_title='长' * 200, b_title='曲' * 200, a_artist='甲' * 160, b_artist='乙' * 160)
    start(conn, 5)
    round_ = s.round_data(conn, DAY, now=NOW + timedelta(days=1))
    first, second = Image.open(poster.render(round_, 1)), Image.open(poster.render(round_, 2))
    assert first.width == second.width == 1080
    assert first.height > second.height
    assert first.getpixel((0, first.height - 1)) == (245, 243, 233)
    with pytest.raises(ValueError):
        poster.render(round_, 0)
    with pytest.raises(ValueError):
        poster.render(round_, 3)


def test_http_nomination_admin_vote_and_results(tmp_path, monkeypatch):
    monkeypatch.setattr(s, 'utcnow', lambda: NOW)
    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'web.sqlite3'),
            SECRET_KEY='test-only',
            ADMIN_PASSWORD='test-only-password',
            PUBLIC_BASE_URL='http://localhost',
        )
    )
    client = app.test_client()
    assert client.get('/admin').status_code == 302
    assert client.post('/admin/settings').status_code == 400

    def post(url, fields):
        with client.session_transaction() as session:
            csrf = session['csrf']
        return client.post(url, data=dict(fields, csrf=csrf), follow_redirects=True)

    nomination_page = client.get('/nominate').get_data(as_text=True)
    for side in ('a', 'b'):
        for platform in ('netease', 'apple'):
            assert f'name="{side}_{platform}"' not in nomination_page
    fields = form(
        nominator='<script>alert(1)</script>', a_apple='https://music.apple.com/cn/song/695558807'
    )
    assert post('/nominate', fields).status_code == 200
    with db.connect(app.config['DATABASE']) as connection:
        row = connection.execute('SELECT a,original FROM nominations WHERE id=1').fetchone()
        assert json.loads(row['a'])['apple'] == ''
        assert json.loads(row['original'])['a']['apple'] == ''
    assert post('/admin/settings', {}).status_code == 403
    assert post('/admin/login', {'password': 'test-only-password'}).status_code == 200
    review_page = client.get('/admin/nomination/1').get_data(as_text=True)
    assert 'name="a_apple"' in review_page
    assert post('/admin/nomination/1', fields).status_code == 200
    with db.connect(app.config['DATABASE']) as connection:
        track = json.loads(
            connection.execute('SELECT a FROM nominations WHERE id=1').fetchone()['a']
        )
        assert track['apple'] == fields['a_apple']
    assert (
        post('/admin/schedule', {'day': DAY, 'count': '1', 'action': 'create'}).status_code == 200
    )
    assert client.get('/admin/round/' + DAY).status_code == 200
    page = post('/vote/1', {'choice': 'a'}).get_data(as_text=True)
    assert '已投给这首' in page and '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;' in page
    assert client.get(f'/rounds/{DAY}/result/1.png').status_code == 404
    monkeypatch.setattr(s, 'utcnow', lambda: NOW + timedelta(days=1))
    assert client.get(f'/rounds/{DAY}/result/1.png').mimetype == 'image/png'
    assert client.get('/admin/round/' + DAY).status_code == 200
    page = post('/vote/1', {'choice': 'b'}).get_data(as_text=True)
    assert '不能修改投票' in page


def test_live_votes_admin_only_and_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(s, 'utcnow', lambda: NOW)
    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'live.sqlite3'),
            SECRET_KEY='test-only',
            ADMIN_PASSWORD='test-only-password',
            PUBLIC_BASE_URL='http://localhost',
        )
    )
    with db.connect(app.config['DATABASE']) as conn:
        for _ in range(4):
            add(conn)
        start(conn, count=2)
        start(conn, day='2026-09-28')  # Future round must not appear in the live panel.
        s.create_round(
            conn, '2026-09-26', NOW, (NOW - timedelta(hours=2), NOW + timedelta(hours=1))
        )
        data = s.active_rounds(conn, NOW)
        assert {r['day'] for r in data} == {'2026-09-26', DAY}
        s.cast_vote(conn, 1, 'first', 'a', NOW)
        s.cast_vote(conn, 1, 'second', 'b', NOW)
        s.cast_vote(conn, 2, 'first', 'a', NOW)
    public = app.test_client()
    assert public.get('/admin/live-votes').status_code == 302
    assert 'live-count' not in public.get('/rounds/' + DAY).text
    client = app.test_client()
    client.get('/admin/login')
    with client.session_transaction() as session:
        csrf = session['csrf']
    assert (
        client.post(
            '/admin/login', data={'csrf': csrf, 'password': 'test-only-password'}
        ).status_code
        == 303
    )
    assert 'data-votes-url' in client.get('/admin').text
    page = client.get('/admin/live-votes')
    assert 'no-store' in page.headers['Cache-Control']
    assert '第 1 组 · 共 2 票' in page.text and '50.0%' in page.text
    assert '暂时持平' in page.text and '等待第一票' in page.text
    assert '2026-09-28' not in page.text
    with db.connect(app.config['DATABASE']) as conn:
        s.cast_vote(conn, 1, 'second', 'a', NOW)
        s.cast_vote(conn, 2, 'first', 'clear', NOW)
    page = client.get('/admin/live-votes').text
    assert 'A 暂时领先 2 票' in page and '100.0%' in page
    assert '第 2 组 · 共 0 票' in page
    monkeypatch.setattr(s, 'utcnow', lambda: NOW + timedelta(hours=1))
    assert '2026-09-26' not in client.get('/admin/live-votes').text
    monkeypatch.setattr(s, 'utcnow', lambda: NOW + timedelta(days=2))
    assert '当前没有正在进行的投票' in client.get('/admin/live-votes').text
    with client.session_transaction() as session:
        session['admin_until'] = 0
    assert client.get('/admin/live-votes').status_code == 302
