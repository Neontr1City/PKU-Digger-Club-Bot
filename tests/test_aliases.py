from copy import deepcopy

import pytest

from cricket import aliases, enrichment, music
from cricket import matching as m


def apple(region, **changes):
    row = dict(
        provider='itunes',
        id='720743504',
        artist_id='apple:131261349',
        artist='青葉市子' if region == 'JP' else 'Ichiko Aoba',
        title='いきのこり●ぼくら' if region == 'JP' else 'Ikinokori●Bokura',
        album='0',
        duration=406,
        region=region,
        date='2013-10-23',
        source=f'https://music.apple.com/{region.lower()}/song/720743504',
        artwork='',
        artwork_source='',
        retrieved_at='2026-09-27T00:00:00+00:00',
    )
    row.update(changes)
    return row


def test_localized_title_requires_same_catalogue_identity_and_duration():
    jp, us = apple('JP'), apple('US')
    assert not m.same_recording(jp, us)
    for changed in (dict(id='another'), dict(artist_id='apple:someone-else'), dict(duration=600)):
        assert aliases.localizations([jp, dict(us, **changed)]) == []
    proofs = aliases.localizations([jp, us])
    aliases.apply([jp, us], proofs)
    assert m.same_recording(jp, us)
    impostor = apple('US', artist_id='apple:someone-else')
    aliases.apply([impostor], proofs)
    assert not impostor['alias_evidence']
    live = apple('JP', title='いきのこり●ぼくら (Live)', duration=450)
    aliases.apply([live], proofs)
    assert not m.same_recording(us, live)


def test_kana_normalization_preserves_voicing():
    assert m.key('あおば いちこ') == m.key('アオバイチコ') == m.key('ｱｵﾊﾞｲﾁｺ')
    assert len({m.key(n) for n in ('は', 'ば', 'ぱ')}) == 3
    assert m.key('Mötley Crüe') == m.key('Motley Crue')
    assert m.key('青葉市子') != m.key('あおばいちこ')  # No guessed kanji readings.


def test_artist_alias_adapter_keeps_reading_and_rejects_ambiguous_names(monkeypatch):
    data = {
        'artists': [
            dict(
                id='verified-id',
                name='青葉市子',
                **{'sort-name': 'Aoba, Ichiko'},
                aliases=[
                    dict(name='青葉市子', **{'sort-name': 'あおば いちこ'}),
                    dict(name='Ichiko Aoba'),
                ],
            )
        ]
    }
    monkeypatch.setattr(music, 'fetch', lambda *args: data)
    music.artist_names.cache_clear()
    result = music.artist_names('青葉市子')
    assert result['source'].endswith('/verified-id/aliases')
    assert 'あおば いちこ' in result['artist_names']
    data['artists'].append(dict(data['artists'][0], id='different-person'))
    music.artist_names.cache_clear()
    assert music.artist_names('青葉市子') is None
    music.artist_names.cache_clear()


@pytest.mark.parametrize(
    'requested_artist', ['青葉市子', 'あおばいちこ', 'アオバイチコ', 'Aoba Ichiko']
)
def test_alias_resolution_prefers_verified_china_link(monkeypatch, requested_artist):
    rows = [apple('JP'), apple('US')]

    def search(provider, query, country='cn', *args, **kwargs):
        return [r for r in rows if provider == 'itunes' and r['region'].lower() == country]

    monkeypatch.setattr(music, 'candidates', search)
    monkeypatch.setattr(music, 'apple_lookup', lambda ids: [apple('CN', artist='青叶市子')])
    monkeypatch.setattr(
        music,
        'artist_names',
        lambda name: dict(
            artist_id='mb:verified',
            artist_names=['青葉市子', 'Ichiko Aoba', 'Aoba Ichiko', 'あおば いちこ'],
            source='https://musicbrainz.org/artist/verified/aliases',
            retrieved_at='2026-09-27',
        ),
    )
    report = enrichment.resolve_track(
        dict(artist=requested_artist, title='いきのこり●ぼくら'), None
    )
    assert report['resolved']
    track = report['track']
    assert track['apple_region'] == 'CN' and '/cn/' in track['apple']
    assert track['alias_evidence'] and report['input']['artist'] == requested_artist
    assert all('verified_aliases' not in r for r in rows)  # Do not mutate cached search rows.


def test_artist_reading_without_evidence_does_not_match(monkeypatch):
    monkeypatch.setattr(
        music,
        'candidates',
        lambda provider, *args, **kwargs: [apple('JP')] if provider == 'itunes' else [],
    )
    monkeypatch.setattr(music, 'artist_names', lambda name: None)
    report = enrichment.resolve_track(dict(artist='あおばいちこ', title='いきのこり●ぼくら'), None)
    assert not report['resolved']


def test_mainland_lookup_never_rewrites_foreign_urls(monkeypatch):
    data = dict(
        results=[
            dict(
                trackId=720743504,
                artistId=131261349,
                artistName='Ichiko Aoba',
                trackName='Ikinokori●Bokura',
                trackViewUrl='https://music.apple.com/us/song/720743504',
            )
        ]
    )
    monkeypatch.setattr(music, 'fetch', lambda *args: deepcopy(data))
    assert music.apple_lookup(['720743504']) == []
    data['results'][0]['trackViewUrl'] = 'https://music.apple.com/cn/song/720743504'
    result = music.apple_lookup(['720743504'])
    assert result[0]['region'] == 'CN'
    assert result[0]['source'] == data['results'][0]['trackViewUrl']
    assert music.apple_lookup(['not-returned']) == []


def test_cn_link_keeps_studio_cover_when_cn_release_is_compilation(monkeypatch):
    rows = [apple('JP', artwork='https://is1-ssl.mzstatic.com/studio.jpg'), apple('US')]
    monkeypatch.setattr(
        music,
        'candidates',
        lambda provider, query, country='cn', *args, **kwargs: [
            r for r in rows if provider == 'itunes' and r['region'].lower() == country
        ],
    )
    monkeypatch.setattr(
        music,
        'apple_lookup',
        lambda ids: [
            apple(
                'CN',
                artist='青叶市子',
                album='Best of Collection',
                date='2020-01-01',
                artwork='https://is1-ssl.mzstatic.com/compilation.jpg',
            )
        ],
    )
    monkeypatch.setattr(enrichment, 'load_artwork', lambda *args: object())
    report = enrichment.resolve_track(dict(artist='青葉市子', title='いきのこり●ぼくら'), None)
    assert report['resolved']
    track = report['track']
    assert track['apple_region'] == 'CN'
    assert track['album'] == '0' and track['artwork'].endswith('/studio.jpg')
    assert track['artwork_evidence']['region'] == 'JP'
