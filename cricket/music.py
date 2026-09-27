"""Public catalogue candidates only. Never automatically approve a recording."""

import json
import threading
import time
from difflib import SequenceMatcher
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_mb_lock = threading.Lock()
_last_mb = 0.0


def fetch(endpoint, params):
    request = Request(
        endpoint + '?' + urlencode(params),
        headers={
            'User-Agent': 'PKU-Digger-Club-Bot/0.1 (noncommercial music metadata review)',
            'Accept': 'application/json',
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


@lru_cache(maxsize=128)
def candidates(provider, query, country='cn', artist=''):
    global _last_mb
    if provider == 'itunes':
        data = fetch(
            'https://itunes.apple.com/search',
            {
                'term': (artist + ' ' + query).strip(),
                'entity': 'song',
                'media': 'music',
                'country': country,
                'limit': 25,
            },
        )
        rows = [
            {
                'artist': t['artistName'],
                'title': t['trackName'],
                'album': t.get('collectionName', ''),
                'source': t.get('trackViewUrl', ''),
                'artist_id': 'apple:' + str(t.get('artistId', '')),
                'duration': round(t.get('trackTimeMillis', 0) / 1000),
                'date': t.get('releaseDate', '')[:10],
                'region': country.upper(),
            }
            for t in data.get('results', [])
            if t.get('trackName')
        ]
        if artist:
            rows.sort(
                key=lambda t: (
                    SequenceMatcher(None, artist.casefold(), t['artist'].casefold()).ratio()
                    + SequenceMatcher(None, query.casefold(), t['title'].casefold()).ratio()
                ),
                reverse=True,
            )
        return rows[:8]
    if provider == 'musicbrainz':
        # At most one MusicBrainz request per second in this process.
        with _mb_lock:
            time.sleep(max(0, 1.1 - (time.monotonic() - _last_mb)))
            try:

                def quoted(value):
                    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

                search = (
                    f'artist:{quoted(artist)} AND recording:{quoted(query)}' if artist else query
                )
                data = fetch(
                    'https://musicbrainz.org/ws/2/recording/',
                    {'query': search, 'fmt': 'json', 'limit': 8},
                )
            finally:
                _last_mb = time.monotonic()
        results = []
        for t in data.get('recordings', []):
            credits = t.get('artist-credit', [])
            releases = t.get('releases', [])
            results.append(
                {
                    'artist': ''.join(
                        c.get('name', c.get('artist', {}).get('name', '')) + c.get('joinphrase', '')
                        for c in credits
                    ),
                    'title': t['title'],
                    'album': releases[0]['title'] if releases else '',
                    'source': 'https://musicbrainz.org/recording/' + t['id'],
                    'artist_id': 'mb:'
                    + '+'.join(c['artist']['id'] for c in credits if c.get('artist')),
                    'duration': round(t.get('length', 0) / 1000),
                    'date': t.get('first-release-date', ''),
                    'region': 'MusicBrainz',
                }
            )
        return results
    raise ValueError('未知曲库。')
