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
