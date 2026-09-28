"""Read-only catalogue adapters. NetEase's web endpoints are not a supported public API."""

import json
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import matching as match

_locks = {name: threading.Lock() for name in ('itunes', 'musicbrainz', 'netease')}
_last = dict.fromkeys(_locks, 0.0)
_INTERVAL = {'itunes': 3.1, 'musicbrainz': 1.1, 'netease': 1.1}


def fetch(endpoint, params):
    provider = (
        'musicbrainz'
        if 'musicbrainz.org' in endpoint
        else 'netease'
        if 'music.163.com' in endpoint
        else 'itunes'
    )
    with _locks[provider]:
        time.sleep(max(0, _INTERVAL[provider] - (time.monotonic() - _last[provider])))
        try:
            request = Request(
                endpoint + '?' + urlencode(params),
                headers={
                    'User-Agent': 'PKU-Digger-Club-Bot/0.1 (https://github.com/Neontr1City/PKU-Digger-Club-Bot)',
                    'Accept': 'application/json',
                    'Referer': 'https://music.163.com/',
                },
            )
            with urlopen(request, timeout=8) as response:
                return json.load(response)
        finally:
            _last[provider] = time.monotonic()


def netease_row(t):
    album = t.get('album') or t.get('al') or {}
    artists = t.get('artists') or t.get('ar') or []
    source = 'https://music.163.com/song?id=' + str(t['id'])
    return {
        'provider': 'netease',
        'id': str(t['id']),
        'artist': ' & '.join(a['name'] for a in artists),
        'title': t['name'],
        'album': album.get('name', ''),
        'source': source,
        'artist_id': 'netease:' + '+'.join(str(a['id']) for a in artists),
        'artist_credits': [dict(name=a['name'], id='netease:' + str(a['id'])) for a in artists],
        'duration': round((t.get('duration') or t.get('dt') or 0) / 1000),
        'region': '网易云',
        'date': '',
        'artwork': (album.get('picUrl') or '').replace('http://', 'https://', 1),
        'artwork_source': 'https://music.163.com/album?id=' + str(album.get('id', '')),
        'disambiguation': ' '.join(t.get('alias') or t.get('alia') or []),
    }


def apple_rows(data, country):
    return [
        {
            'provider': 'itunes',
            'id': str(t.get('trackId', '')),
            'artist': t['artistName'],
            'title': t['trackName'],
            'album': t.get('collectionName', ''),
            'source': t.get('trackViewUrl', ''),
            'artist_id': 'apple:' + str(t.get('artistId', '')),
            'duration': round(t.get('trackTimeMillis', 0) / 1000),
            'date': t.get('releaseDate', '')[:10],
            'region': country.upper(),
            'artwork': t.get('artworkUrl100', '').replace('100x100bb', '600x600bb'),
            'artwork_source': t.get('collectionViewUrl', ''),
        }
        for t in data.get('results', [])
        if t.get('trackName')
    ]


@lru_cache(maxsize=128)
def _candidates(provider, query, country, artist, studio, fuzzy, hour):
    listed = match.listed_artists(artist)
    search_artist = ' '.join(listed) if len(listed) > 1 else artist
    if provider == 'itunes':
        data = fetch(
            'https://itunes.apple.com/search',
            {
                'term': (search_artist + ' ' + query).strip(),
                'entity': 'song',
                'media': 'music',
                'country': country,
                'lang': 'ja_jp' if country == 'jp' else 'en_us',
                'limit': 50,
            },
        )
        rows = apple_rows(data, country)
    elif provider == 'netease':
        data = fetch(
            'https://music.163.com/api/search/get',
            {
                's': (search_artist + ' ' + query).strip(),
                'type': 1,
                'limit': 30,
            },
        )
        if data.get('code') != 200:
            raise ValueError('网易云搜索暂时不可用。')
        rows = [netease_row(t) for t in data.get('result', {}).get('songs', [])]
    elif provider == 'musicbrainz':

        def quoted(value):
            return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

        search = f'artist:{quoted(artist)} AND recording:{quoted(query)}' if artist else query
        if len(listed) > 1:
            members = ' AND '.join(f'artist:{quoted(name)}' for name in listed)
            search = f'(artist:{quoted(artist)} OR ({members})) AND recording:{quoted(query)}'
        if fuzzy:

            def terms(value):
                return ' AND '.join(
                    word + ('~1' if len(word) >= 4 else '')
                    for word in re.findall(r'[^\W_]+', value.casefold())
                )

            artist_terms, title_terms = terms(artist), terms(query)
            if not artist_terms or not title_terms:
                return []
            search = f'artist:({artist_terms}) AND recording:({title_terms})'
        if studio:
            search += ' AND status:official AND NOT secondarytype:live'
        data = fetch(
            'https://musicbrainz.org/ws/2/recording/', {'query': search, 'fmt': 'json', 'limit': 30}
        )
        rows = []
        for t in data.get('recordings', []):
            credits, releases = t.get('artist-credit', []), t.get('releases', [])
            rows.append(
                {
                    'provider': 'musicbrainz',
                    'id': t['id'],
                    'artist': ''.join(
                        c.get('name', c.get('artist', {}).get('name', '')) + c.get('joinphrase', '')
                        for c in credits
                    ),
                    'title': t['title'],
                    'album': releases[0]['title'] if releases else '',
                    'source': 'https://musicbrainz.org/recording/' + t['id'],
                    'artist_id': 'mb:'
                    + '+'.join(c['artist']['id'] for c in credits if c.get('artist')),
                    'artist_credits': [
                        dict(
                            name=c.get('name') or c['artist']['name'], id='mb:' + c['artist']['id']
                        )
                        for c in credits
                        if c.get('artist')
                    ],
                    'duration': round(t.get('length', 0) / 1000),
                    'date': t.get('first-release-date', ''),
                    'region': 'MusicBrainz',
                    'disambiguation': t.get('disambiguation', ''),
                    'releases': [
                        {
                            'title': r.get('release-group', {}).get('title') or r['title'],
                            'source': 'https://musicbrainz.org/release/' + r['id']
                            if r.get('id')
                            else '',
                            'status': r.get('status', ''),
                            'date': r.get('date', ''),
                            'type': r.get('release-group', {}).get('primary-type', ''),
                            'secondary': r.get('release-group', {}).get('secondary-types', []),
                        }
                        for r in releases
                    ],
                }
            )
    else:
        raise ValueError('未知曲库。')
    for row in rows:
        row['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    rows.sort(key=lambda t: match.rank({'artist': artist, 'title': query}, t), reverse=True)
    return rows[:30]


def candidates(provider, query, country='cn', artist='', studio=False, fuzzy=False):
    return _candidates(provider, query, country, artist, studio, fuzzy, int(time.time() // 3600))


candidates.cache_clear = _candidates.cache_clear


@lru_cache(maxsize=128)
def _artist_names(name, hour):
    quoted = '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'
    data = fetch('https://musicbrainz.org/ws/2/artist/', dict(query=quoted, fmt='json', limit=10))
    identities = []
    for artist in data.get('artists', []):
        names = list(
            dict.fromkeys(
                [artist['name'], artist.get('sort-name', '')]
                + [
                    n
                    for a in artist.get('aliases', [])
                    for n in (a['name'], a.get('sort-name', ''))
                ]
            )
        )
        names = [n for n in names if n]
        if match.key(name) in {match.key(n) for n in names}:
            identities.append(
                dict(
                    artist_id='mb:' + artist['id'],
                    artist_names=names,
                    source='https://musicbrainz.org/artist/' + artist['id'] + '/aliases',
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                )
            )
    # The search rank alone does not disambiguate same-name artists.
    return identities[0] if len(identities) == 1 else None


def artist_names(name):
    return _artist_names(name, int(time.time() // 3600))


artist_names.cache_clear = _artist_names.cache_clear


def apple_lookup(ids, country='cn'):
    data = fetch('https://itunes.apple.com/lookup', dict(id=','.join(ids), country=country))
    rows = apple_rows(data, country)
    for row in rows:
        row['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    return [r for r in rows if r['id'] in ids and f'/{country}/' in r['source']]


def detail(candidate):
    if candidate['provider'] != 'netease':
        return candidate
    data = fetch(
        'https://music.163.com/api/song/detail/', {'ids': json.dumps([int(candidate['id'])])}
    )
    songs = data.get('songs', [])
    if not songs or str(songs[0]['id']) != candidate['id']:
        raise ValueError('网易云歌曲详情未返回对应曲目。')
    return netease_row(songs[0])
