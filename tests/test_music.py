from cricket import music


def test_musicbrainz_uses_artist_and_title_and_keeps_release_source(monkeypatch):
    seen = []

    def fetch(endpoint, params):
        seen.append(params)
        return {
            'recordings': [
                {
                    'id': 'recording-1',
                    'title': 'April',
                    'artist-credit': [{'name': 'Deep Purple', 'artist': {'id': 'artist-1'}}],
                    'releases': [{'title': 'Deep Purple'}],
                    'length': 724000,
                    'first-release-date': '1969-06-21',
                }
            ]
        }

    monkeypatch.setattr(music, 'fetch', fetch)
    music.candidates.cache_clear()
    result = music.candidates('musicbrainz', 'April', 'cn', 'Deep Purple')
    assert seen[0]['query'] == 'artist:"Deep Purple" AND recording:"April"'
    assert result[0]['artist_id'] == 'mb:artist-1'
    assert result[0]['source'] == 'https://musicbrainz.org/recording/recording-1'
    assert result[0]['duration'] == 724


def test_apple_keeps_storefront_and_ranks_matching_recording(monkeypatch):
    seen = []

    def fetch(endpoint, params):
        seen.append(params)
        return {
            'results': [
                dict(
                    artistName='Other artist',
                    trackName='April cover',
                    trackViewUrl='https://music.apple.com/cn/song/1',
                ),
                dict(
                    artistName='Deep Purple',
                    trackName='April',
                    trackViewUrl='https://music.apple.com/cn/song/2',
                ),
            ]
        }

    monkeypatch.setattr(music, 'fetch', fetch)
    music.candidates.cache_clear()
    rows = music.candidates('itunes', 'April', 'cn', 'Deep Purple')
    assert seen[0]['country'] == 'cn'
    assert seen[0]['term'] == 'Deep Purple April'
    assert rows[0]['title'] == 'April'
    assert rows[0]['region'] == 'CN'
    # Ranking is just candidate order; no writes or automatic confirmation.
    assert len(rows) == 2


def test_musicbrainz_fuzzy_query_escapes_user_syntax(monkeypatch):
    seen = []

    def fetch(endpoint, params):
        seen.append(params['query'])
        return {'recordings': []}

    monkeypatch.setattr(music, 'fetch', fetch)
    music.candidates.cache_clear()
    music.candidates('musicbrainz', 'Aprli" OR *:*', 'cn', 'Deep Purpel', studio=True, fuzzy=True)
    assert 'artist:(deep~1 AND purpel~1)' in seen[0]
    assert '*:*' not in seen[0]
    assert 'recording:(aprli~1 AND or)' in seen[0]


def test_netease_detail_retains_actual_id_and_cover(monkeypatch):
    def fetch(endpoint, params):
        return {
            'songs': [
                {
                    'id': 123,
                    'name': 'April (2000 Remaster)',
                    'artists': [{'id': 7, 'name': 'Deep Purple'}],
                    'album': {
                        'id': 9,
                        'name': 'Deep Purple',
                        'picUrl': 'http://p1.music.126.net/cover.jpg',
                    },
                    'duration': 724000,
                }
            ]
        }

    monkeypatch.setattr(music, 'fetch', fetch)
    row = music.detail({'provider': 'netease', 'id': '123'})
    assert row['source'] == 'https://music.163.com/song?id=123'
    assert row['artwork'] == 'https://p1.music.126.net/cover.jpg'
    assert row['artwork_source'] == 'https://music.163.com/album?id=9'
    assert row['duration'] == 724
