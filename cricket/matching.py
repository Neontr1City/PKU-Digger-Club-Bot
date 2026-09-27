"""Deterministic music matching; comparison keys never become display names."""

import html
import re
import unicodedata
from difflib import SequenceMatcher

_REMASTER = (
    r'(?:\d{4}\s*(?:[-–—]\s*)?)?(?:digital(?:ly)?\s+)?remaster(?:ed)?(?:\s+(?:version|\d{4}))*'
)
_VARIANTS = r'\b(?:live|remix|mix|demo|acoustic|instrumental|karaoke|re-?record(?:ed|ing)?|take\s+\d+|radio\s+edit|mono|stereo)\b|现场|混音|重录|伴奏'
_FEATURE = r'(?:feat\.?|ft\.?|featuring)\s+'


def clean(value):
    return ' '.join(unicodedata.normalize('NFC', html.unescape(value or '')).split())


def remaster_title(value):
    value = clean(value)
    value = re.sub(r'[\(\[]\s*' + _REMASTER + r'\s*[\)\]]', '', value, flags=re.I)
    value = re.sub(r'\s+[-–—]\s*' + _REMASTER + r'\s*$', '', value, flags=re.I)
    return clean(value)


def credit_parts(value):
    """Extract explicit credit annotations, never arbitrary parenthesized subtitles."""
    guests = []

    def extract(found):
        guests.append(clean(found.group(1)))
        return ''

    value = re.sub(
        r'[\(\[]\s*' + _FEATURE + r'([^()\[\]]+)[\)\]]', extract, clean(value), flags=re.I
    )
    value = re.sub(r'\s+(?:[-–—]\s*)?' + _FEATURE + r'([^()\[\]]+)$', extract, value, flags=re.I)
    return clean(value), guests


def display_title(value):
    return remaster_title(credit_parts(value)[0])


def key(value):
    value = unicodedata.normalize('NFKD', remaster_title(value).casefold())
    # Keep Japanese voicing marks (は/ば/ぱ differ), while ignoring Latin accents.
    value = ''.join(c for c in value if not unicodedata.combining(c) or c in '\u3099\u309a')
    value = unicodedata.normalize('NFC', value)
    value = ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in value)
    return ''.join(c for c in value if c.isalnum())


def similarity(a, b):
    a, b = key(a), key(b)
    if not a or not b:
        return 0
    ratio = SequenceMatcher(None, a, b).ratio()
    if min(len(a), len(b)) >= 4:
        if len(a) == len(b):
            differences = [i for i in range(len(a)) if a[i] != b[i]]
            adjacent_swap = (
                len(differences) == 2
                and differences[1] == differences[0] + 1
                and a[differences[0]] == b[differences[1]]
                and a[differences[1]] == b[differences[0]]
            )
            if len(differences) == 1 or adjacent_swap:
                ratio = max(ratio, 0.94)
        elif abs(len(a) - len(b)) == 1:
            short, long = sorted((a, b), key=len)
            offset = next((i for i, (x, y) in enumerate(zip(short, long)) if x != y), len(short))
            if short == long[:offset] + long[offset + 1 :]:
                ratio = max(ratio, 0.94)
    return ratio


def variants(value):
    return set(re.findall(_VARIANTS, display_title(value).casefold()))


def compatible(requested, candidate):
    # Remasters are interchangeable; live/remix/demo and unknown title qualifiers aren't.
    wanted = variants(requested['title'])
    found = [
        variants(title + ' ' + candidate.get('disambiguation', ''))
        for title in names(candidate, 'title')
    ]
    album_variants = variants(candidate.get('album', ''))
    return wanted in found and (bool(wanted) or not album_variants)


def names(row, field):
    values = [row[field], *row.get('verified_aliases', {}).get(field, [])]
    return [display_title(v) for v in values] if field == 'title' else values


def feature_names(row):
    return {key(n) for field in ('artist', 'title') for n in credit_parts(row[field])[1]}


def artist_options(row):
    # Only structured provider credits may split a joint artist name. In particular,
    # an '&' inside a band's name is not proof of two separate artists.
    return [credit_parts(n)[0] for n in names(row, 'artist')] + [
        c['name'] for c in row.get('artist_credits', [])
    ]


def credited_names(row):
    credits = row.get('artist_credits')
    return (
        {key(c['name']) for c in credits} | feature_names(row)
        if credits
        else {key(credit_parts(row['artist'])[0]), *feature_names(row)}
    )


def share_artist_credits(rows):
    """Attach structured credits only to a corroborated copy of that recording."""
    sources = [r for r in rows if r.get('artist_credits') and not r.get('artist_credit_source')]
    for row in rows:
        if row.get('artist_credits'):
            continue
        proofs = [
            r
            for r in sources
            if key(r['artist']) == key(row['artist'])
            and key(display_title(r['title'])) == key(display_title(row['title']))
            and duration_matches(r, row)
            and not (
                feature_names(r) and feature_names(row) and feature_names(r) != feature_names(row)
            )
        ]
        if proofs and all(credited_names(p) == credited_names(proofs[0]) for p in proofs):
            row['artist_credits'] = [dict(c) for c in proofs[0]['artist_credits']]
            row['artist_credit_source'] = proofs[0]['source']


def field_score(a, b, field):
    if field == 'artist':
        return max(similarity(x, y) for x in artist_options(a) for y in artist_options(b))
    return max(similarity(x, y) for x in names(a, field) for y in names(b, field))


def same_names(a, b):
    if not ({key(n) for n in names(a, 'title')} & {key(n) for n in names(b, 'title')}):
        return False
    fa, fb = feature_names(a), feature_names(b)
    if fa and fb and fa != fb:
        return False
    ca, cb = credited_names(a), credited_names(b)
    if (a.get('artist_credits') or fa) and (b.get('artist_credits') or fb):
        if not (ca <= cb or cb <= ca):
            # Localized credits can still be connected by catalogue aliases below.
            if not (a.get('alias_evidence') or b.get('alias_evidence')):
                return False
    return bool(
        {key(n) for n in names(a, 'artist')} & {key(n) for n in names(b, 'artist')}
        or ca <= cb
        or cb <= ca
    )


def identity_conflict(a, b):
    if a['provider'] != b['provider'] or not a.get('artist_id') or not b.get('artist_id'):
        return False
    ia, ib = (set(r['artist_id'].split(':')[-1].split('+')) for r in (a, b))
    return not (ia <= ib or ib <= ia)


def display_artist(row):
    artist = clean(row['artist'])
    known = {key(c['name']) for c in row.get('artist_credits', [])}
    known |= feature_names(dict(row, title=''))
    extra = [n for n in credit_parts(row['title'])[1] if key(n) not in known]
    return artist + (' feat. ' + ' & '.join(extra) if extra else '')


def rank(requested, candidate):
    return round(
        (field_score(requested, candidate, 'artist') + field_score(requested, candidate, 'title'))
        / 2,
        4,
    )


def plausible(requested, candidate):
    a, t = (
        field_score(requested, candidate, 'artist'),
        field_score(requested, candidate, 'title'),
    )
    guests = feature_names(requested)
    return (
        compatible(requested, candidate)
        and (not guests or guests <= credited_names(candidate))
        and a >= 0.84
        and t >= 0.84
        and (a + t) / 2 >= 0.91
    )


def album_key(value):
    value = re.sub(
        r'[\(\[].*?(?:deluxe|bonus tracks|expanded|anniversary|remaster).*?[\)\]]',
        '',
        clean(value),
        flags=re.I,
    )
    return key(value)


def same_recording(a, b):
    if not same_names(a, b):
        return False
    if not compatible(a, b):
        return False
    return not identity_conflict(a, b) and duration_matches(a, b)


def duration_matches(a, b):
    da, db = a.get('duration', 0), b.get('duration', 0)
    return bool(da and db and abs(da - db) <= max(4, min(da, db) * 0.02))


def release_rank(candidate, albums=()):
    album = candidate.get('album', '')
    known = [r for r in albums if album_key(r['title']) == album_key(album)]
    official = any(
        r.get('status') == 'Official'
        and r.get('type') in ('Album', 'EP')
        and not r.get('secondary')
        for r in known
    )
    compilation = bool(
        re.search(r'greatest|best of|collection|compilation|soundtrack|精选|合辑', album, re.I)
    )
    # Prefer a verified studio album/EP, then ordinary releases; dates are only a tie breaker.
    return (
        not official,
        compilation,
        candidate.get('region') not in ('CN', '网易云'),
        candidate.get('date') or '9999',
        candidate.get('source', ''),
    )
