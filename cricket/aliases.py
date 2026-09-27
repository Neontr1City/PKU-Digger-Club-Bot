"""Source-backed names, scoped to one lookup; never guess a Japanese reading."""

import re

from . import matching as m


def has_cjk(value):
    return bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]', value))


def localizations(rows):
    groups = {}
    for row in rows:
        if row['provider'] == 'itunes' and row.get('id') and row.get('artist_id'):
            groups.setdefault((row['id'], row['artist_id']), []).append(row)
    evidence = []
    for (track_id, artist_id), group in groups.items():
        if len({r['region'] for r in group}) < 2:
            continue
        durations = [r.get('duration', 0) for r in group]
        if not min(durations) or max(durations) - min(durations) > max(4, min(durations) * 0.02):
            continue
        evidence.append(
            dict(
                kind='apple-localization',
                track_id=track_id,
                artist_id=artist_id,
                artist_names=list(dict.fromkeys(r['artist'] for r in group)),
                title_names=list(dict.fromkeys(r['title'] for r in group)),
                sources=[r['source'] for r in group],
                retrieved_at=max(r.get('retrieved_at', '') for r in group),
                duration=min(durations),
            )
        )
    return evidence


def apply(rows, evidence):
    for row in rows:
        row['verified_aliases'] = dict(artist=[], title=[])
        row['alias_evidence'] = []
        # A localized Apple credit can connect to a MusicBrainz reading through
        # the same kanji/roman credit. Retain both steps of that evidence chain.
        for _ in range(2):
            for proof in evidence:
                if proof in row['alias_evidence']:
                    continue
                if not {m.key(n) for n in m.names(row, 'artist')} & {
                    m.key(n) for n in proof['artist_names']
                }:
                    continue
                if proof['kind'] == 'apple-localization':
                    if m.key(row['title']) not in {m.key(n) for n in proof['title_names']}:
                        continue
                    duration = row.get('duration', 0)
                    if not duration or abs(duration - proof['duration']) > max(
                        4, min(duration, proof['duration']) * 0.02
                    ):
                        continue
                    if row['provider'] == 'itunes' and row['artist_id'] != proof['artist_id']:
                        continue
                    row['verified_aliases']['title'].extend(proof['title_names'])
                elif row['provider'] == 'musicbrainz' and row['artist_id'] != proof['artist_id']:
                    continue
                row['verified_aliases']['artist'].extend(proof['artist_names'])
                row['alias_evidence'].append(proof)
        for field in ('artist', 'title'):
            row['verified_aliases'][field] = list(dict.fromkeys(row['verified_aliases'][field]))
