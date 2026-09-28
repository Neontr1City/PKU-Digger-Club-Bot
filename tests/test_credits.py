from copy import deepcopy

import pytest

from cricket import enrichment, music
from cricket import matching as m


def song(artist='Primary Artist', title='The Song', **changes):
    row = dict(
        provider='itunes',
        id='11',
        artist_id='apple:1',
        artist=artist,
        title=title,
        duration=240,
        album='Studio Album',
        region='CN',
        date='2020-01-01',
        source='https://music.apple.com/cn/song/11',
        artwork='',
        artwork_source='',
    )
    row.update(changes)
    return row


def catalogue(monkeypatch, rows):
    monkeypatch.setattr(
        music,
        'candidates',
        lambda provider, *args, **kw: deepcopy([r for r in rows if r['provider'] == provider]),
    )
    monkeypatch.setattr(music, 'detail', lambda row: row)
    monkeypatch.setattr(music, 'artist_names', lambda name: None)
    monkeypatch.setattr(music, 'apple_lookup', lambda ids: [])


@pytest.mark.parametrize(
    'title',
    [
        'The Song (feat. Guest Artist)',
        'The Song [ft. Guest Artist]',
        'The Song featuring Guest Artist',
        'The Song - feat. Guest Artist',
        'The Song (feat. Guest Artist) (2020 Remaster)',
    ],
)
def test_omitted_feature_is_credit_not_title(monkeypatch, title):
    catalogue(monkeypatch, [song(title=title)])
    report = enrichment.resolve_track(dict(artist='Primary Artist', title='The Song'), None)
    assert report['resolved']
    track = report['track']
    assert track['title'] == 'The Song'
    assert track['artist'] == 'Primary Artist feat. Guest Artist'
    assert track['featured_artists'] == ['Guest Artist']
    assert track['platform_evidence'][0]['title'] == title


def test_feature_does_not_erase_versions_or_subtitles():
    original = dict(artist='Primary Artist', title='The Song')
    assert not m.plausible(original, song(title='The Song (Live) (feat. Guest Artist)'))
    assert m.display_title('The Song (Part 2) (feat. Guest Artist)') == 'The Song (Part 2)'
    assert m.display_title('The Song (Acoustic)') == 'The Song (Acoustic)'
    assert m.display_title('Featuring You') == 'Featuring You'
    assert m.plausible(original, song(title='The Song (feat. Live)'))


def test_explicit_wrong_guest_and_cover_are_not_accepted():
    assert not m.plausible(
        dict(artist='Primary Artist', title='The Song (feat. Guest One)'),
        song(title='The Song (feat. Guest Two)'),
    )
    assert not m.plausible(
        dict(artist='Primary Artist', title='The Song'),
        song(artist='Cover Artist', title='The Song (feat. Guest One)'),
    )


def test_unspecified_guests_choose_one_lineup(monkeypatch):
    catalogue(
        monkeypatch,
        [
            song(title='The Song (feat. Guest One)'),
            song(id='12', title='The Song (feat. Guest Two)'),
        ],
    )
    report = enrichment.resolve_track(dict(artist='Primary Artist', title='The Song'), None)
    assert report['resolved']
    assert len(report['track']['platform_evidence']) == 1


def test_structured_collaboration_accepts_one_artist_and_keeps_both_links(monkeypatch):
    credits = [
        dict(name='Primary Artist', id='netease:1'),
        dict(name='Guest Artist', id='netease:2'),
    ]
    rows = [
        song(artist='Primary Artist & Guest Artist'),
        song(
            artist='Primary Artist & Guest Artist',
            provider='netease',
            artist_id='netease:1+2',
            artist_credits=credits,
            source='https://music.163.com/song?id=11',
        ),
    ]
    catalogue(monkeypatch, rows)
    report = enrichment.resolve_track(dict(artist='Primary Artist', title='The Song'), None)
    assert report['resolved']
    track = report['track']
    assert track['artist'] == 'Primary Artist & Guest Artist'
    assert track['apple'] and track['netease']
    assert track['artist_credits'] == credits
    assert track['platform_evidence'][0]['artist_credit_source'] == rows[1]['source']
    assert 'artist_credits' not in rows[0]  # Cached source rows stay unchanged.


def test_band_names_are_not_split_on_ampersands():
    row = song(
        artist='Belle & Sebastian', artist_credits=[dict(name='Belle & Sebastian', id='band')]
    )
    assert not m.plausible(dict(artist='Belle', title='The Song'), row)
    assert not m.plausible(dict(artist='Sebastian', title='The Song'), row)
    assert m.plausible(dict(artist='Belle & Sebastian', title='The Song'), row)


def test_credit_sharing_requires_matching_recording():
    original = song(
        artist='Primary Artist & Guest Artist',
        provider='netease',
        artist_credits=[dict(name='Primary Artist'), dict(name='Guest Artist')],
    )
    for changes in [dict(duration=500), dict(title='Another Song'), dict(artist='Other Artist')]:
        row = song(artist=original['artist'])
        row.update(changes)
        m.share_artist_credits([original, row])
        assert 'artist_credits' not in row


def test_missing_platform_feature_can_share_recording_but_conflicts_cannot():
    a = song(title='The Song (feat. Guest Artist)')
    b = song(provider='netease', artist_id='netease:8')
    assert m.same_recording(a, b)
    assert not m.same_recording(a, dict(b, title='The Song (feat. Other Guest)'))
    assert not m.same_recording(a, dict(b, duration=500))


def test_solo_credit_has_priority_over_two_collaborations(monkeypatch):
    solo = song()
    rows = [solo]
    for i, guest in enumerate(['Guest One', 'Guest Two'], 2):
        rows.append(
            song(
                id=str(i),
                artist=f'Primary Artist & {guest}',
                artist_id=f'apple:1+{i}',
                artist_credits=[dict(name='Primary Artist'), dict(name=guest)],
            )
        )
    catalogue(monkeypatch, rows)
    report = enrichment.resolve_track(dict(artist='Primary Artist', title='The Song'), None)
    assert report['resolved']
    assert report['track']['artist'] == 'Primary Artist'


def test_structured_provider_members_keep_their_ids():
    row = music.netease_row(
        dict(
            id=11,
            name='The Song',
            artists=[dict(id=1, name='Belle & Sebastian'), dict(id=2, name='Guest Artist')],
        )
    )
    assert row['artist_credits'] == [
        dict(name='Belle & Sebastian', id='netease:1'),
        dict(name='Guest Artist', id='netease:2'),
    ]
    assert m.identity_conflict(row, dict(row, artist_id='netease:99+2'))


@pytest.mark.parametrize(
    'artist',
    [
        'Primary Artist / Guest Artist',
        'Guest Artist & Primary Artist',
        'Primary Artist、Guest Artist',
        'Guest Artist, Primary Artist',
        'Primary Artist feat. Guest Artist',
        'Primary Artits & Guest Artist',
    ],
)
def test_explicit_multiple_artists_selects_collaboration(monkeypatch, artist):
    joint = song(
        artist='Primary Artist & Guest Artist',
        id='12',
        artist_id='apple:1+2',
        artist_credits=[dict(name='Primary Artist'), dict(name='Guest Artist')],
    )
    catalogue(monkeypatch, [song(), joint])
    report = enrichment.resolve_track(dict(artist=artist, title='The Song'), None)
    assert report['resolved']
    assert report['track']['artist'] == 'Primary Artist & Guest Artist'
    assert report['track']['apple'] == joint['source']


def test_explicit_unknown_collaborator_does_not_fall_back_to_solo(monkeypatch):
    catalogue(monkeypatch, [song()])
    assert not enrichment.resolve_track(dict(artist='Primary Artist / X', title='The Song'), None)[
        'resolved'
    ]


def test_slash_is_not_assumed_to_split_a_band(monkeypatch):
    catalogue(monkeypatch, [song(artist='AC/DC', artist_credits=[dict(name='AC/DC')])])
    assert enrichment.resolve_track(dict(artist='AC/DC', title='The Song'), None)['resolved']


@pytest.mark.parametrize('provider', ['netease', 'itunes', 'musicbrainz'])
def test_multiple_artist_query_searches_each_name(monkeypatch, provider):
    seen = []
    monkeypatch.setattr(
        music, 'fetch', lambda endpoint, params: seen.append(params) or {'code': 200}
    )
    music._candidates(provider, 'The Song', 'cn', 'Guest Artist / Primary Artist', False, False, -1)
    query = seen[0].get('query') or seen[0].get('term') or seen[0].get('s')
    assert 'Guest Artist' in query and 'Primary Artist' in query
    if provider == 'musicbrainz':
        assert 'artist:"Guest Artist" AND artist:"Primary Artist"' in query
    else:
        assert '/' not in query
