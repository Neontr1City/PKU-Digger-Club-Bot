"""Deterministic music matching; comparison keys never become display names."""

import html
import re
import unicodedata
from difflib import SequenceMatcher

_REMASTER = (
    r'(?:\d{4}\s*(?:[-–—]\s*)?)?(?:digital(?:ly)?\s+)?remaster(?:ed)?(?:\s+(?:version|\d{4}))*'
)
_VARIANTS = r'\b(?:live|remix|mix|demo|acoustic|instrumental|karaoke|re-?record(?:ed|ing)?|take\s+\d+|radio\s+edit|mono|stereo)\b|现场|混音|重录|伴奏'


def clean(value):
    return ' '.join(unicodedata.normalize('NFC', html.unescape(value or '')).split())


def display_title(value):
    value = clean(value)
    value = re.sub(r'[\(\[]\s*' + _REMASTER + r'\s*[\)\]]', '', value, flags=re.I)
    value = re.sub(r'\s+[-–—]\s*' + _REMASTER + r'\s*$', '', value, flags=re.I)
    return clean(value)


def key(value):
    value = unicodedata.normalize('NFKD', display_title(value).casefold())
    return ''.join(c for c in value if c.isalnum() and not unicodedata.combining(c))


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
    found = variants(candidate['title'] + ' ' + candidate.get('disambiguation', ''))
    album_variants = variants(candidate.get('album', ''))
    return wanted == found and (bool(wanted) or not album_variants)


def rank(requested, candidate):
    return round(
        (
            similarity(requested['artist'], candidate['artist'])
            + similarity(requested['title'], candidate['title'])
        )
        / 2,
        4,
    )


def plausible(requested, candidate):
    a, t = (
        similarity(requested['artist'], candidate['artist']),
        similarity(requested['title'], candidate['title']),
    )
    return compatible(requested, candidate) and a >= 0.84 and t >= 0.84 and (a + t) / 2 >= 0.91


def album_key(value):
    value = re.sub(
        r'[\(\[].*?(?:deluxe|bonus tracks|expanded|anniversary|remaster).*?[\)\]]',
        '',
        clean(value),
        flags=re.I,
    )
    return key(value)


def same_recording(a, b):
    if key(a['artist']) != key(b['artist']) or key(a['title']) != key(b['title']):
        return False
    if not compatible(a, b):
        return False
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
