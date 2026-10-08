import secrets
from copy import deepcopy
from datetime import timedelta

import pytest
from PIL import Image

from cricket import db, music
from cricket import enrichment as e
from cricket import matching as m
from cricket import service as s


@pytest.fixture(autouse=True)
def no_extra_network(monkeypatch):
    monkeypatch.setattr(music, 'artist_names', lambda name: None)
    monkeypatch.setattr(music, 'apple_lookup', lambda ids: [])


def candidate(provider='itunes', **changes):
    row = dict(
        provider=provider,
        id='123',
        artist='Mötley Crüe',
        title='Home Sweet Home',
        album='Theatre of Pain',
        artist_id=provider + ':1',
        duration=240,
        date='1985-01-01',
        region='CN' if provider == 'itunes' else '网易云',
        disambiguation='',
        source='https://music.apple.com/cn/song/123'
        if provider == 'itunes'
        else 'https://music.163.com/song?id=123',
        artwork='https://is1-ssl.mzstatic.com/cover.jpg',
        artwork_source='https://music.apple.com/cn/album/1',
    )
    row.update(changes)
    return row


@pytest.fixture
def catalogue(monkeypatch):
    rows = [candidate(), candidate('netease', title='Home Sweet Home (2011 Remastered Version)')]
    monkeypatch.setattr(
        music,
        'candidates',
        lambda provider, *args, **kwargs: deepcopy([r for r in rows if r['provider'] == provider]),
    )
    monkeypatch.setattr(music, 'detail', lambda row: row)
    monkeypatch.setattr(e, 'load_artwork', lambda *args: Image.new('RGB', (2, 2)))
    return rows


def resolve():
    return e.resolve_track(dict(artist='Motley Crue', title='Home Sweet Hmoe'), None)


@pytest.mark.parametrize(
    'title',
    [
        'Song (2011 Remastered Version)',
        'Song (2011 - Remaster)',
        'Song - Remastered 2011',
        'Song [Remaster]',
    ],
)
def test_remaster_display_only(title):
    assert m.display_title(title) == 'Song'
    assert m.display_title('Song (Live at Home)') == 'Song (Live at Home)'
    assert m.key('Mötley Crüe') == m.key('Motley Crue')
    assert m.clean('  The  Smiths&#x20;') == 'The Smiths'


def test_auto_correction_and_evidence(catalogue):
    report = resolve()
    assert report['resolved']
    assert 'reversed_search' not in report
    assert not any(q.get('search_mode') == 'reversed' for q in report['queries'])
    track = report['track']
    assert (track['artist'], track['title']) == ('Mötley Crüe', 'Home Sweet Home')
    assert track['apple'] and track['netease'] and track['artwork']
    assert track['checked_by'] == 'automatic'
    assert len(track['platform_evidence']) == 2
    assert len(report['corrections']) == 2
    assert report['input']['title'] == 'Home Sweet Hmoe'


def test_single_link_and_missing_cover_are_accepted(catalogue, monkeypatch):
    catalogue.pop()
    monkeypatch.setattr(e, 'load_artwork', lambda *args: None)
    report = resolve()
    assert report['resolved'] and report['track']['apple']
    assert report['track']['netease'] == report['track']['artwork'] == ''
    assert any('无需管理员处理' in warning for warning in report['warnings'])


@pytest.mark.parametrize(
    'change',
    [
        dict(artist='Other Band'),
        dict(title='Home Sweet Home (Live)'),
        dict(title='Home Sweet Home', disambiguation='demo recording'),
    ],
)
def test_wrong_artist_and_version_not_auto_selected(catalogue, change):
    catalogue[:] = [candidate(**change)]
    assert not resolve()['resolved']


def test_same_name_artist_identity_conflict(catalogue):
    catalogue[:] = [
        candidate(),
        candidate(id='456', artist_id='itunes:2', source='https://music.apple.com/cn/song/456'),
    ]
    report = resolve()
    assert not report['resolved']
    assert 'reversed_search' not in report


def test_duration_conflict_does_not_join_different_recordings(catalogue):
    catalogue[1]['duration'] = 460
    report = resolve()
    assert report['resolved']
    assert bool(report['track']['apple']) != bool(report['track']['netease'])
    assert any('时长' in note for note in report['warnings'])


def test_album_consensus_beats_unverified_collection(catalogue):
    catalogue.insert(
        0,
        candidate('netease', id='99', album='The Works', source='https://music.163.com/song?id=99'),
    )
    report = resolve()
    assert report['track']['album'] == 'Theatre of Pain'
    assert report['track']['netease'].endswith('123')


def test_provider_outage_uses_remaining_source(catalogue, monkeypatch):
    def search(provider, *args, **kwargs):
        if provider != 'itunes':
            raise TimeoutError()
        return [candidate()]

    monkeypatch.setattr(music, 'candidates', search)
    assert resolve()['resolved']


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / 'nomination.sqlite3'
    db.initialize(path)
    with db.connect(path) as connection:
        yield connection


def nominate(conn):
    form = dict(
        submission_id=secrets.token_hex(16),
        nominator='示例听众',
        a_artist='Motley Crue',
        a_title='Home Sweet Hmoe',
        b_artist='The Smiths',
        b_title='There Is a Light That Never Goes Out',
    )
    s.nominate(conn, form)
    s.nominate(conn, form)
    return conn.execute('SELECT id FROM nominations').fetchone()[0]


def resolved_track(original, *args):
    title = m.display_title(original['title'])
    track = dict(
        artist=original['artist'],
        title=title,
        album='样例专辑',
        version='',
        artist_id='',
        apple='https://music.apple.com/cn/song/123',
        netease='',
        artwork='',
        artwork_source='',
        sources=['https://music.apple.com/cn/song/123'],
        checked_by='automatic',
    )
    return dict(
        resolved=True,
        track=track,
        reasons=[],
        warnings=[],
        corrections=[],
        queries=[],
        candidates=[],
    )


def test_queue_auto_ready_preserves_original_and_is_idempotent(conn, monkeypatch):
    id_ = nominate(conn)
    assert conn.execute('SELECT COUNT(*) FROM enrichment_jobs').fetchone()[0] == 1
    original = conn.execute('SELECT original FROM nominations').fetchone()[0]
    monkeypatch.setattr(e, 'resolve_track', resolved_track)
    assert e.process_next(conn, None)['status'] == 'complete'
    item = s.unpack(conn.execute('SELECT * FROM nominations').fetchone())
    assert item['status'] == 'ready' and item['a']['netease'] == ''
    assert item['original'] == original
    assert e.job(conn, id_)['report']['rule_version'] == e.RULE_VERSION
    assert e.process_next(conn, None) is None
    with pytest.raises(ValueError):
        e.enqueue(conn, id_)


def test_no_song_stays_pending_and_can_retry(conn, monkeypatch):
    id_ = nominate(conn)
    monkeypatch.setattr(
        e, 'resolve_track', lambda *args: dict(resolved=False, track=None, reasons=['未找到'])
    )
    assert e.process_next(conn, None)['status'] == 'review'
    assert conn.execute('SELECT status FROM nominations').fetchone()[0] == 'pending'
    e.enqueue(conn, id_)
    assert e.job(conn, id_)['status'] == 'queued'


def test_manual_change_while_processing_wins(conn, monkeypatch):
    id_ = nominate(conn)

    def changed(original, *args):
        with conn:
            conn.execute("UPDATE nominations SET status='skipped' WHERE id=?", (id_,))
        return resolved_track(original)

    monkeypatch.setattr(e, 'resolve_track', changed)
    assert e.process_next(conn, None)['status'] == 'superseded'
    assert conn.execute('SELECT status FROM nominations').fetchone()[0] == 'skipped'


def test_invalid_metadata_never_approves(conn, monkeypatch):
    nominate(conn)

    def invalid(original, *args):
        report = resolved_track(original)
        report['track']['apple'] = 'https://wrong.example/song'
        return report

    monkeypatch.setattr(e, 'resolve_track', invalid)
    assert e.process_next(conn, None)['status'] == 'error'
    assert conn.execute('SELECT status FROM nominations').fetchone()[0] == 'pending'


def test_stale_claim_is_recovered(conn, monkeypatch):
    id_ = nominate(conn)
    with conn:
        conn.execute(
            "UPDATE enrichment_jobs SET status='running',updated_at=? WHERE nomination_id=?",
            (s.stamp(s.utcnow() - timedelta(minutes=16)), id_),
        )
    monkeypatch.setattr(e, 'resolve_track', resolved_track)
    assert e.process_next(conn, None)['status'] == 'complete'


def test_version_in_notes_is_not_ignored(conn, monkeypatch):
    nominate(conn)
    with conn:
        conn.execute("UPDATE nominations SET notes='请使用现场版本'")
    monkeypatch.setattr(e, 'resolve_track', resolved_track)
    assert e.process_next(conn, None)['status'] == 'review'
    assert '版本要求' in e.job(conn, 1)['report']['error']


def test_short_transposition_is_corrected_without_erasing_version():
    assert m.plausible(
        {'artist': 'Deep Purpel', 'title': 'Aprli'}, candidate(artist='Deep Purple', title='April')
    )
    assert not m.plausible(
        {'artist': 'Deep Purple', 'title': 'April'},
        candidate(artist='Deep Purple', title='April (Live)'),
    )


def test_bounded_retry_after_provider_failure(conn, monkeypatch):
    id_ = nominate(conn)

    def failed(*args):
        raise TimeoutError()

    monkeypatch.setattr(e, 'resolve_track', failed)
    for attempt in range(1, 4):
        assert e.process_next(conn, None)['status'] == 'error'
        assert e.job(conn, id_)['report']['attempt'] == attempt
        assert e.process_next(conn, None) is None
        with conn:
            conn.execute(
                'UPDATE enrichment_jobs SET updated_at=?',
                (s.stamp(s.utcnow() - timedelta(minutes=16)),),
            )
    assert e.process_next(conn, None) is None
    e.enqueue(conn, id_)
    monkeypatch.setattr(e, 'resolve_track', resolved_track)
    assert e.process_next(conn, None)['status'] == 'complete'
    assert e.job(conn, id_)['report']['attempt'] == 1


def test_admin_processing_endpoints_are_private(tmp_path):
    from cricket import create_app

    app = create_app(
        dict(
            TESTING=True,
            DATABASE=str(tmp_path / 'web.sqlite3'),
            SECRET_KEY='test-only',
            ADMIN_PASSWORD='test-only',
        )
    )
    client = app.test_client()
    with db.connect(app.config['DATABASE']) as connection:
        id_ = nominate(connection)
    assert client.get(f'/admin/nomination/{id_}').status_code == 302
    client.get('/admin/login')
    with client.session_transaction() as session:
        csrf = session['csrf']
    assert client.post(f'/admin/nomination/{id_}/resolve', data={'csrf': csrf}).status_code == 403
    assert (
        client.post('/admin/login', data={'csrf': csrf, 'password': 'test-only'}).status_code == 303
    )
    assert client.get(f'/admin/nomination/{id_}').status_code == 200
    assert client.post(f'/admin/nomination/{id_}/resolve').status_code == 400
    with client.session_transaction() as session:
        csrf = session['csrf']
    assert client.post(f'/admin/nomination/{id_}/resolve', data={'csrf': csrf}).status_code == 303


def test_fuzzy_fallback_requeries_platform_with_corrected_name(catalogue, monkeypatch):
    seen = []

    def search(provider, title, country, artist, **kwargs):
        seen.append((provider, title, artist, kwargs.get('fuzzy')))
        if provider == 'musicbrainz' and kwargs.get('fuzzy'):
            return [candidate('musicbrainz', artist='Deep Purple', title='April')]
        if provider == 'itunes' and artist == 'Deep Purple' and title == 'April':
            return [candidate(artist='Deep Purple', title='April')]
        return []

    monkeypatch.setattr(music, 'candidates', search)
    result = e.resolve_track({'artist': 'Deep Purpel', 'title': 'Aprli'}, None)
    assert result['resolved']
    assert ('musicbrainz', 'Aprli', 'Deep Purpel', True) in seen
    assert ('itunes', 'April', 'Deep Purple', False) in seen


def test_reversed_input_candidates_require_manual_confirmation(monkeypatch, conn):
    original = dict(artist='A Lovers Prayer', title='Yellow Tricycle')
    reverse_row = candidate(
        artist='Yellow Tricycle',
        title='A Lovers Prayer',
        album='A Lovers Prayer',
    )
    wrong_row = candidate(
        artist='Yellow Tricycle',
        title='Yellow Tricycle',
        id='999',
        source='https://music.apple.com/cn/song/999',
    )
    calls = []

    def search(provider, title, country, artist, **kwargs):
        calls.append((provider, title, artist, kwargs))
        if provider == 'musicbrainz':
            raise TimeoutError()
        if provider != 'itunes':
            return []
        if artist == 'Motley Crue':
            return [candidate()]
        if artist == original['title'] and title == original['artist']:
            return [reverse_row, wrong_row]
        return [wrong_row, reverse_row]

    monkeypatch.setattr(music, 'candidates', search)
    monkeypatch.setattr(music, 'detail', lambda row: row)
    monkeypatch.setattr(e, 'load_artwork', lambda *args: None)
    s.nominate(
        conn,
        dict(
            submission_id=secrets.token_hex(16),
            nominator='示例听众',
            a_artist='Motley Crue',
            a_title='Home Sweet Home',
            b_artist=original['artist'],
            b_title=original['title'],
        ),
    )
    saved_original = conn.execute('SELECT original FROM nominations').fetchone()[0]
    result = e.process_next(conn, None)
    assert result['status'] == 'review'
    item = conn.execute('SELECT * FROM nominations').fetchone()
    assert item['status'] == 'pending'
    assert item['original'] == saved_original
    report = e.job(conn, item['id'])['report']['sides']['b']
    assert not report['resolved'] and report['track'] is None
    assert report['input'] == dict(original, netease='', apple='')
    assert report['reversed_search']['input'] == dict(
        artist='Yellow Tricycle', title='A Lovers Prayer'
    )
    assert report['reversed_search']['candidate_count'] == 1
    assert report['reversed_search']['has_listening_candidates']
    assert any('可能将艺人和曲名填反' in reason for reason in report['reasons'])
    reversed_choices = [c for c in report['candidates'] if c.get('search_mode') == 'reversed']
    assert len(reversed_choices) == 1
    assert sum(c['source'] == reverse_row['source'] for c in report['candidates']) == 1
    assert reversed_choices[0]['title'] == 'A Lovers Prayer'
    assert e.review_choices(report)[0]['draft']['artist'] == 'Yellow Tricycle'
    assert 'search_mode' not in reverse_row
    assert any(q.get('search_mode') == 'reversed' and q.get('error') for q in report['queries'])
    assert sum(q.get('search_mode') == 'reversed' for q in report['queries']) == 3


def test_reversed_search_with_no_matching_results_stays_unresolved(monkeypatch):
    monkeypatch.setattr(music, 'candidates', lambda *args, **kwargs: [candidate()])
    report = e.resolve_track(dict(artist='Unknown Artist', title='Unknown Song'), None)
    assert not report['resolved']
    assert report['reversed_search']['candidate_count'] == 0
    assert not report['reversed_search']['has_listening_candidates']
    assert not any(c.get('search_mode') == 'reversed' for c in report['candidates'])
    assert sum(q.get('search_mode') == 'reversed' for q in report['queries']) == 4
