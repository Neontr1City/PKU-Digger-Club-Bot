from copy import deepcopy

import pytest
from PIL import Image

from cricket import enrichment as e
from cricket import music


def song(provider, id_, album, duration=293, **changes):
    row = dict(
        provider=provider,
        id=id_,
        artist='Example Artist',
        artist_id=provider + ':1',
        title='The Song',
        album=album,
        duration=duration,
        region='CN' if provider == 'itunes' else '网易云',
        date='2024-01-01',
        source=f'https://example.org/{provider}/{id_}',
        artwork='https://example.org/cover.png',
        artwork_source=f'https://example.org/album/{album}',
    )
    row.update(changes)
    return row


def recording(id_, album, date, duration=293, **changes):
    return song(
        'musicbrainz',
        id_,
        album,
        duration,
        releases=[
            dict(
                title=album,
                date=date,
                status='Official',
                type='Album',
                secondary=[],
                source=f'https://musicbrainz.org/release/{id_}',
            )
        ],
        **changes,
    )


@pytest.fixture
def catalogue(monkeypatch):
    rows = [
        song(
            'netease',
            'live',
            'Concert',
            534,
            artist='Example Artist & Guest',
            artist_id='netease:1+2',
            artist_credits=[dict(name='Example Artist'), dict(name='Guest')],
        ),
        song('netease', 'later', 'Later Recording', 411),
        song(
            'netease',
            'other-guest',
            'Benefit Concert',
            312,
            artist='Another Guest & Example Artist',
            artist_id='netease:3+1',
            artist_credits=[dict(name='Another Guest'), dict(name='Example Artist')],
        ),
        song('itunes', 'remaster', 'Original Album', title='The Song (2021 Remaster)'),
        song('netease', 'original', 'Original Album'),
        song('netease', 'hits', 'Hits'),
        recording('later', 'Later Recording', '2002', 411),
        recording('original', 'Original Album', '1970'),
    ]
    monkeypatch.setattr(
        music,
        'candidates',
        lambda provider, *a, **kw: deepcopy([r for r in rows if r['provider'] == provider]),
    )
    monkeypatch.setattr(music, 'detail', lambda row: row)
    monkeypatch.setattr(music, 'apple_lookup', lambda *a: [])
    monkeypatch.setattr(music, 'artist_names', lambda *a: None)
    monkeypatch.setattr(e, 'load_artwork', lambda *a: Image.new('RGB', (2, 2)))
    return rows


def resolve(title='The Song'):
    return e.resolve_track(dict(artist='Example Artist', title=title), None)


def test_original_album_precedes_unlabelled_collaboration_and_rerecording(catalogue):
    result = resolve()
    assert result['resolved']
    assert result['track']['album'] == 'Original Album'
    assert result['track']['title'] == 'The Song'
    assert result['track']['netease'].endswith('/original')
    assert result['track']['apple'].endswith('/remaster')
    assert result['recording_selection']['year'] == '1970'
    assert result['recording_selection']['excluded_candidates'] == 1
    assert len(result['recording_selection']['sources']) == 3
    catalogue.reverse()
    assert resolve()['track']['album'] == 'Original Album'


def test_solo_priority_does_not_require_musicbrainz(catalogue):
    catalogue[:] = [r for r in catalogue if r['provider'] != 'musicbrainz']
    result = resolve()
    assert result['resolved'] and result['track']['artist'] == 'Example Artist'
    assert 'recording_selection' not in result


def test_dated_release_does_not_override_different_same_name_artist(catalogue):
    catalogue.append(song('netease', 'impostor', 'Original Album', artist_id='netease:99'))
    assert not resolve()['resolved']


def test_explicit_guest_is_not_replaced_by_solo_original(catalogue):
    result = resolve('The Song (feat. Guest)')
    assert result['resolved']
    assert result['track']['album'] == 'Concert'
    assert not result['track']['apple']


def test_same_year_cannot_prove_one_recording_is_earlier(catalogue):
    catalogue.append(
        recording(
            'guest',
            'Concert',
            '1970-08',
            534,
            artist='Example Artist & Guest',
            artist_credits=[dict(name='Example Artist'), dict(name='Guest')],
        )
    )
    leaders = [r for r in catalogue if r['provider'] != 'musicbrainz']
    _, proof = e.prefer_album_recording(
        dict(artist='Example Artist', title='The Song'), leaders, catalogue
    )
    assert proof is None


def test_explicit_live_request_does_not_choose_studio_album(catalogue):
    catalogue.append(song('itunes', 'live', 'Live Album', title='The Song (Live)', duration=534))
    result = resolve('The Song (Live)')
    assert result['resolved'] and result['track']['album'] == 'Live Album'
    assert 'recording_selection' not in result
