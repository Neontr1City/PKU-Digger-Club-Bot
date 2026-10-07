from io import BytesIO
from unittest.mock import MagicMock

import pytest
from flask import render_template
from PIL import Image

from cricket import artwork, create_app, poster


def result(outcome, votes):
    return {
        'day': '2026-09-26',
        'open': False,
        'snapshot': True,
        'ends_at': '2026-09-27T12:00:00+00:00',
        'matches': [
            {
                'id': 1,
                'position': 1,
                'nominator': '示例听众',
                'choice': None,
                'a': {'artist': '艺人甲', 'title': '歌甲', 'album': '专辑甲'},
                'b': {'artist': '艺人乙', 'title': '歌乙', 'album': '专辑乙'},
                'votes_a': votes[0],
                'votes_b': votes[1],
                'outcome': outcome,
            }
        ],
    }


@pytest.mark.parametrize(
    'outcome,votes,label',
    [
        ('a', (28, 19), 'A 面胜出 · 领先 9 票'),
        ('b', (0, 28), 'B 面胜出 · 领先 28 票'),
        ('tie', (23, 23), '平局 · 不分高下'),
        ('zero', (0, 0), '本组暂无有效投票'),
    ],
)
def test_results_preserve_outcomes_in_page_and_poster(tmp_path, monkeypatch, outcome, votes, label):
    round_ = result(outcome, votes)
    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'test.sqlite3'),
            SECRET_KEY='test-only',
            ADMIN_PASSWORD='test-only',
        )
    )
    with app.test_request_context('/rounds/2026-09-26'):
        html = render_template('round.html', round_=round_, history=[])
    winner = outcome in ('a', 'b')
    assert html.count(' is-winner') == int(winner)
    if winner:
        expected = round_['matches'][0][outcome]
        assert f'<h3>{expected["artist"]} <span>— {expected["title"]}</span></h3>' in html
    assert html.count('class="result-meter"') == 2
    assert 'name="choice"' not in html
    assert 'nan' not in html.lower()

    drawn = []
    original = poster.Typography.text

    def capture(self, draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(self, draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(poster.Typography, 'text', capture)
    image = Image.open(poster.render(round_))
    assert image.width == poster.EXPORT_WIDTH
    assert label in drawn
    assert drawn.count('WINNER / 胜出') == int(winner)
    assert drawn.count('DRAW / 平局') == (2 if outcome == 'tie' else 0)
    assert f'共 {sum(votes)} 票' in drawn
    assert all(str(vote) in drawn for vote in votes)
    assert '封面暂缺' in drawn


def test_artwork_download_cache_and_failures(tmp_path, monkeypatch):
    cover = BytesIO()
    Image.new('RGB', (120, 100), '#123456').save(cover, format='PNG')
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.read.return_value = cover.getvalue()
    monkeypatch.setattr(artwork, 'build_opener', lambda *args: opener)
    url = 'https://is1-ssl.mzstatic.com/image/example.png'
    image = artwork.load_artwork(url, tmp_path)
    assert image.size == (600, 600)
    assert image.getpixel((0, 0)) == (18, 52, 86)
    assert artwork.load_artwork(url, tmp_path).size == (600, 600)
    assert opener.open.call_count == 1
    # Unsupported URLs and offline rendering never issue a request.
    for blocked in (
        'http://is1-ssl.mzstatic.com/image.png',
        'https://127.0.0.1/private',
        'https://is1-ssl.mzstatic.com.evil.test/x',
        'https://user:password@is1-ssl.mzstatic.com/x',
    ):
        assert artwork.load_artwork(blocked, tmp_path) is None
    assert artwork.load_artwork(url, None) is None
    assert opener.open.call_count == 1
    response.read.return_value = b'not an image'
    assert artwork.load_artwork(url + '?invalid', tmp_path) is None
    response.read.return_value = b'x' * (artwork.MAX_BYTES + 1)
    assert artwork.load_artwork(url + '?oversize', tmp_path) is None
    opener.open.side_effect = TimeoutError()
    assert artwork.load_artwork(url + '?timeout', tmp_path) is None
    assert (
        artwork.NoRedirects().redirect_request(None, None, 302, '', {}, 'http://localhost') is None
    )


def test_poster_includes_loaded_artwork(monkeypatch):
    cover = Image.new('RGB', (600, 600), '#123456')
    monkeypatch.setattr(poster, 'load_artwork', lambda *args: cover)
    image = Image.open(poster.render(result('a', (28, 19)))).convert('RGB')
    assert any(color == (18, 52, 86) for _, color in image.getcolors(image.width * image.height))


def test_web_cover_uses_shared_cache_and_rejects_unsigned_sources(tmp_path, monkeypatch):
    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'web.sqlite3'),
            OUTPUT_DIR=str(tmp_path / 'output'),
            SECRET_KEY='test',
            ADMIN_PASSWORD='test',
        )
    )
    source = 'https://is1-ssl.mzstatic.com/image/example.png'
    cache = artwork.cache_path(source, tmp_path / 'output' / 'artwork')
    cache.parent.mkdir(parents=True)
    Image.new('RGB', (600, 600), '#123456').save(cache)
    opener = MagicMock()
    opener.open.side_effect = TimeoutError()
    monkeypatch.setattr(artwork, 'build_opener', lambda *args: opener)
    with app.test_request_context():
        cover_url = app.jinja_env.filters['cover_url']
        url = cover_url(source)
        other = cover_url(source + '?missing')
        blocked = cover_url('https://localhost/private.png')
        round_ = result('a', (28, 19))
        round_['matches'][0]['a']['artwork'] = source
        html = render_template('round.html', round_=round_, history=[])
        assert 'src="/artwork/' in html and f'src="{source}"' not in html
    client = app.test_client()
    response = client.get(url)
    assert response.status_code == 200 and response.mimetype == 'image/webp'
    assert all(
        abs(a - b) <= 3
        for a, b in zip(Image.open(BytesIO(response.data)).getpixel((0, 0)), (18, 52, 86))
    )
    assert 'max-age=86400' in response.headers['Cache-Control']
    assert 'Set-Cookie' not in response.headers
    assert client.get(url, headers={'If-None-Match': response.headers['ETag']}).status_code == 304
    assert client.get('/artwork/unsigned.png').status_code == 404
    assert client.get(blocked).status_code == 404
    opener.open.assert_not_called()
    fallback = client.get(other)
    assert fallback.status_code == 200 and fallback.mimetype == 'image/svg+xml'
    assert '封面暂缺' in fallback.get_data(as_text=True)
    assert fallback.headers['Cache-Control'] == 'no-store'


def test_cover_outage_coalesces_and_retries_after_cooldown(tmp_path, monkeypatch):
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Event(), threading.Event()
    opener = MagicMock()

    def offline(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        raise TimeoutError()

    opener.open.side_effect = offline
    monkeypatch.setattr(artwork, 'build_opener', lambda *args: opener)
    source = 'https://is1-ssl.mzstatic.com/outage.png'
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = pool.submit(artwork.load_artwork, source, tmp_path)
        assert entered.wait(3)
        try:
            assert all(
                image is None
                for image in pool.map(lambda _: artwork.load_artwork(source, tmp_path), range(15))
            )
        finally:
            release.set()
        assert pending.result() is None
    assert artwork.load_artwork(source, tmp_path) is None
    assert opener.open.call_count == 1
    failure = artwork.cache_path(source, tmp_path).with_suffix('.failed')
    os.utime(failure, (time.time() - 61, time.time() - 61))
    cover = BytesIO()
    Image.new('RGB', (100, 100), '#123456').save(cover, format='PNG')
    opener.open.side_effect = None
    opener.open.return_value.__enter__.return_value.read.return_value = cover.getvalue()
    assert artwork.load_artwork(source, tmp_path).size == (600, 600)
    assert opener.open.call_count == 2
    assert not failure.exists()


def test_cover_download_slots_leave_web_threads_available(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Barrier(3), threading.Event()

    def offline(*args, **kwargs):
        entered.wait(timeout=3)
        assert release.wait(3)
        raise TimeoutError()

    opener = MagicMock()
    opener.open.side_effect = offline
    monkeypatch.setattr(artwork, 'build_opener', lambda *args: opener)
    # Select different lock stripes so this tests the global download limit.
    sources, stripes = [], set()
    for i in range(100):
        url = f'https://is1-ssl.mzstatic.com/slots-{i}.png'
        stripe = int(artwork.cache_path(url, tmp_path).stem[:8], 16) % len(artwork._COVER_LOCKS)
        if stripe not in stripes:
            sources.append(url)
            stripes.add(stripe)
        if len(sources) == 3:
            break
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(artwork.load_artwork, url, tmp_path) for url in sources[:2]]
        try:
            entered.wait(timeout=3)
            assert artwork.load_artwork(sources[2], tmp_path) is None
            assert opener.open.call_count == 2
        finally:
            release.set()
        assert all(task.result() is None for task in pending)


def test_result_cache_shared_by_concurrent_reads_and_invalidated(tmp_path, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor

    round_ = result('a', (28, 19))
    round_['snapshot'] = json.dumps(round_['matches'])
    render = MagicMock(wraps=poster.render)
    monkeypatch.setattr(poster, 'render', render)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: poster.cached_path(round_, 1, '', tmp_path), range(8)))
    assert len(set(paths)) == 1 and render.call_count == 1
    with Image.open(paths[0]) as image:
        assert image.width == 864 and image.format == 'PNG'
    changed = result('b', (19, 28))
    changed['snapshot'] = json.dumps(changed['matches'])
    assert poster.cached_path(changed, 1, '', tmp_path) != paths[0]
    assert render.call_count == 2
    with pytest.raises(ValueError):
        poster.cached_path(round_, 2, '', tmp_path)


def test_cached_web_cover_does_not_decode_again(tmp_path, monkeypatch):
    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'db.sqlite3'),
            OUTPUT_DIR=str(tmp_path / 'output'),
            SECRET_KEY='test',
            ADMIN_PASSWORD='test',
        )
    )
    source = 'https://is1-ssl.mzstatic.com/cached.png'
    path = artwork.cache_path(source, tmp_path / 'output' / 'artwork')
    path.parent.mkdir(parents=True)
    Image.new('RGB', (600, 600), 'red').save(path)
    with app.test_request_context():
        url = app.jinja_env.filters['cover_url'](source)
    artwork.web_cover_path(path)
    decode = MagicMock(side_effect=AssertionError('Hot cover should not be decoded'))
    monkeypatch.setattr(artwork, 'load_artwork', decode)
    assert app.test_client().get(url).status_code == 200
    decode.assert_not_called()


def test_frozen_result_http_cache_and_no_session_cookie(tmp_path):
    import json

    from cricket import db
    from cricket import service as s

    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'db.sqlite3'),
            OUTPUT_DIR=str(tmp_path / 'output'),
            SECRET_KEY='test',
            ADMIN_PASSWORD='test',
        )
    )
    round_ = result('a', (28, 19))
    with db.connect(app.config['DATABASE']) as conn, conn:
        conn.execute(
            'INSERT INTO rounds(day,starts_at,ends_at,snapshot,closed_at) VALUES(?,?,?,?,?)',
            (
                round_['day'],
                '2026-09-26T04:00:00+00:00',
                round_['ends_at'],
                json.dumps(round_['matches']),
                s.stamp(s.utcnow()),
            ),
        )
    client = app.test_client()
    url = '/rounds/2026-09-26/result/1.png'
    response = client.get(url)
    assert response.status_code == 200
    assert 'Set-Cookie' not in response.headers
    assert 'max-age=86400' in response.headers['Cache-Control']
    assert client.get(url, headers={'If-None-Match': response.headers['ETag']}).status_code == 304
    assert client.get('/rounds/2026-09-26/result/2.png').status_code == 404


def test_web_derivative_is_small_and_refreshes_without_changing_original(tmp_path):
    import os

    source = artwork.cache_path('https://is1-ssl.mzstatic.com/derivative.png', tmp_path)
    Image.new('RGB', (600, 600), 'red').save(source)
    original = source.read_bytes()
    thumbnail = artwork.web_cover_path(source)
    assert thumbnail.suffix == '.webp'
    assert len(thumbnail.read_bytes()) < len(original)
    assert source.read_bytes() == original
    with Image.open(thumbnail) as image:
        assert image.size == (480, 480)
    Image.new('RGB', (600, 600), 'blue').save(source)
    os.utime(thumbnail, (1, 1))
    assert artwork.web_cover_path(source) == thumbnail
    with Image.open(thumbnail) as image:
        red, green, blue = image.convert('RGB').getpixel((0, 0))
        assert blue > 240 and red < 10 and green < 10
