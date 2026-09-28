"""Nomination enrichment and its small SQLite-backed work queue."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from itertools import combinations

from . import aliases, music
from . import matching as match
from . import service as s
from .artwork import load_artwork

RULE_VERSION = '2026-09-28.1'


def prefer_album_recording(original, leaders, possible):
    """Resolve editions against dated, corroborated studio releases before credits."""
    if match.variants(original['title']) or not all(
        {match.key(n) for n in match.names(a, 'title')}
        & {match.key(n) for n in match.names(b, 'title')}
        for a, b in combinations(leaders, 2)
    ):
        return leaders, None
    # Release evidence must not hide two unrelated artists with the same name.
    if not match.shared_artist_identity(leaders):
        return leaders, None
    proofs = []
    for row in leaders:
        for recording in possible:
            if recording['provider'] != 'musicbrainz' or not match.same_recording(row, recording):
                continue
            for release in recording.get('releases', []):
                date = release.get('date', '')
                if (
                    release.get('status') == 'Official'
                    and release.get('type') in ('Album', 'EP')
                    and not release.get('secondary')
                    and match.album_key(release['title']) == match.album_key(row['album'])
                    and len(date) >= 4
                    and date[:4].isdigit()
                    and release.get('source')
                ):
                    proofs.append((date[:4], row, recording, release))
    if not proofs:
        return leaders, None
    earliest = min(p[0] for p in proofs)
    first = [p for p in proofs if p[0] == earliest]
    # Partial dates cannot decide between different recordings in the same year.
    anchors = list({(p[1]['provider'], p[1]['source']): p[1] for p in first}.values())
    if not all(match.same_recording(a, b) for a, b in combinations(anchors, 2)):
        return leaders, None
    selected = [r for r in leaders if all(match.same_recording(r, a) for a in anchors)]
    if not selected:
        return leaders, None
    proof = first[0]
    return selected, dict(
        reason='优先采用曲库交叉确认的较早正式专辑／EP录音；其他录音不参与该版本的链接选择。',
        album=proof[3]['title'],
        year=earliest,
        sources=[proof[1]['source'], proof[2]['source'], proof[3]['source']],
        excluded_candidates=len(leaders) - len(selected),
    )


def resolve_track(original, artwork_dir):
    queries, warnings, rows = [], [], []

    def search(provider, artist, title, country='cn', fuzzy=False):
        record = dict(provider=provider, artist=artist, title=title, country=country, fuzzy=fuzzy)
        try:
            found = music.candidates(
                provider,
                title,
                country,
                artist,
                studio=not match.variants(original['title']),
                fuzzy=fuzzy,
            )
            record['count'] = len(found)
        except (OSError, ValueError, KeyError, TypeError):
            found = []
            record['error'] = '来源暂时不可用'
        return found, record

    def collect(result):
        found, record = result
        queries.append(record)
        known = {(r['provider'], r['source']) for r in rows}
        rows.extend(deepcopy(r) for r in found if (r['provider'], r['source']) not in known)
        match.share_artist_credits(rows)

    artist, title = match.clean(original['artist']), match.display_title(original['title'])
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(
            lambda provider: search(provider, artist, title), ('netease', 'itunes', 'musicbrainz')
        ):
            collect(result)
    possible = [r for r in rows if match.plausible(original, r)]
    if not possible:
        collect(search('musicbrainz', artist, title, fuzzy=True))
        possible = [r for r in rows if match.plausible(original, r)]
    corrected = max(possible, key=lambda r: match.rank(original, r), default=original)
    artist, title = corrected['artist'], match.display_title(corrected['title'])
    if not any(r['provider'] == 'itunes' for r in possible):
        collect(search('itunes', artist, title, 'us'))

    # Apple storefronts sometimes localize both artist and song names. Same catalogue
    # IDs provide an explicit bridge without machine translation or guessed readings.
    alias_proofs = []
    if (
        not any(r['provider'] != 'musicbrainz' and match.plausible(original, r) for r in rows)
        or aliases.has_cjk(original['artist'] + original['title'])
        or any(
            aliases.has_cjk(r['artist'] + r['title'])
            for r in rows
            if r['provider'] == 'netease'
            and match.similarity(original['title'], r['title']) >= 0.91
        )
    ):
        collect(search('itunes', artist, title, 'jp'))
        alias_proofs = aliases.localizations(rows)
        aliases.apply(rows, alias_proofs)
        possible = [r for r in rows if match.plausible(original, r)]
        if not possible:
            # A kana query can return a kanji credit. Verify that reading in the
            # artist's alias/sort-name record; query relevance is not identity proof.
            names = list(
                dict.fromkeys(
                    r['artist']
                    for r in sorted(
                        rows, key=lambda r: match.field_score(original, r, 'title'), reverse=True
                    )
                    if match.field_score(original, r, 'title') >= 0.91
                )
            )[:2]
            for name in names:
                record = dict(
                    provider='musicbrainz-alias', artist=name, title='艺人别名', country='', count=0
                )
                try:
                    proof = music.artist_names(name)
                    if proof and match.key(original['artist']) in {
                        match.key(n) for n in proof['artist_names']
                    }:
                        proof = dict(proof, kind='artist-alias')
                        alias_proofs.append(proof)
                        record['count'] = len(proof['artist_names'])
                        aliases.apply(rows, alias_proofs)
                        break
                except (OSError, ValueError, KeyError, TypeError):
                    record['error'] = '来源暂时不可用'
                finally:
                    queries.append(record)
        possible = [r for r in rows if match.plausible(original, r)]
    if not any(r['provider'] == 'netease' for r in possible):
        best = max(possible, key=lambda r: match.rank(original, r), default=original)
        japanese_artist = next((n for n in match.names(best, 'artist') if aliases.has_cjk(n)), '')
        japanese_title = next((n for n in match.names(best, 'title') if aliases.has_cjk(n)), title)
        collect(search('netease', japanese_artist, japanese_title))
    if not any(r['provider'] == 'musicbrainz' for r in possible) and (artist, title) != (
        original['artist'],
        original['title'],
    ):
        collect(search('musicbrainz', artist, title))

    aliases.apply(rows, alias_proofs)
    possible = [r for r in rows if match.plausible(original, r)]
    if not any(r['provider'] == 'itunes' and r['region'] == 'CN' for r in possible):
        ids = list(
            dict.fromkeys(
                r['id']
                for r in sorted(possible, key=match.release_rank)
                if r['provider'] == 'itunes'
            )
        )[:3]
        if ids:
            record = dict(
                provider='itunes-lookup', artist=artist, title=title, country='cn', ids=ids
            )
            try:
                found = music.apple_lookup(ids)
                record['count'] = len(found)
                collect((found, record))
            except (OSError, ValueError, KeyError, TypeError):
                record['error'] = '来源暂时不可用'
                queries.append(record)
            alias_proofs = [
                p for p in alias_proofs if p['kind'] != 'apple-localization'
            ] + aliases.localizations(rows)
            aliases.apply(rows, alias_proofs)

    possible = [r for r in rows if match.plausible(original, r)]
    platforms = [r for r in possible if r['provider'] != 'musicbrainz']
    report = dict(
        input=original,
        queries=queries,
        warnings=warnings,
        candidates=sorted(rows, key=lambda r: match.rank(original, r), reverse=True)[:12],
        resolved=False,
        track=None,
        reasons=[],
        corrections=[],
    )
    if not platforms:
        report['reasons'] = ['未找到可确定身份和版本的歌曲链接。']
        return report
    priority = min(match.credit_priority(original, r) for r in platforms)
    platforms = [r for r in platforms if match.credit_priority(original, r) == priority]
    best_score = max(match.rank(original, r) for r in platforms)
    leaders = [r for r in platforms if match.rank(original, r) >= best_score - 0.035]
    leaders, selection = prefer_album_recording(original, leaders, possible)
    if selection:
        report['recording_selection'] = selection
    if not all(
        {match.key(n) for n in match.names(a, 'title')}
        & {match.key(n) for n in match.names(b, 'title')}
        for a, b in combinations(leaders, 2)
    ):
        report['reasons'] = ['存在多个相近的曲名，无法确定提名指向。']
        return report
    # A same-name artist is not interchangeable just because strings match.
    if not match.shared_artist_identity(leaders):
        report['reasons'] = ['同名艺人对应不同身份，无法确定提名指向。']
        return report
    base = leaders[0]
    evidence = [
        r for r in possible if r['provider'] == 'musicbrainz' and match.same_recording(base, r)
    ]
    releases = [release for r in evidence for release in r.get('releases', [])]

    def release_order(candidate):
        rank = match.release_rank(candidate, releases)
        support = {
            r['provider']
            for r in leaders
            if match.album_key(r['album']) == match.album_key(candidate['album'])
            and match.same_recording(candidate, r)
        }
        return (rank[:2], -len(support), candidate['provider'] != 'itunes', rank[2:])

    leaders.sort(key=release_order)
    # Choose one guest lineup rather than blocking or mixing different collaborations.
    leaders = [r for r in leaders if match.same_names(leaders[0], r)]
    chosen = {}
    for provider in ('itunes', 'netease'):
        choices = [r for r in leaders if r['provider'] == provider]
        if choices:
            # Mainland links take precedence even when another storefront supplies
            # the preferred cover or the spelling used to identify the recording.
            chosen[provider] = min(choices, key=lambda r: (r['region'] != 'CN', release_order(r)))
    if len(chosen) == 2 and not match.same_recording(chosen['itunes'], chosen['netease']):
        # Never join links for conflicting recordings; one credible link is sufficient.
        preferred = leaders[0]['provider']
        chosen = {preferred: chosen[preferred]}
        warnings.append('两个平台的录音时长或版本不一致，仅保留优先发行的链接。')
    if 'netease' in chosen:
        try:
            detail = music.detail(chosen['netease'])
            aliases.apply([detail], alias_proofs)
            if not match.same_recording(chosen['netease'], detail):
                chosen.pop('netease')
                warnings.append('网易云搜索与详情不一致，未采用该链接。')
            else:
                chosen['netease'] = detail
        except (OSError, ValueError, KeyError, TypeError):
            chosen.pop('netease')
            warnings.append('网易云详情暂不可核对，未采用该链接。')
    if not chosen:
        report['reasons'] = ['搜索候选存在，但歌曲详情无法确认；可稍后重试。']
        return report
    selected = sorted(chosen.values(), key=release_order)
    canonical = chosen.get('itunes') or selected[0]
    # Prefer the canonical recording spelling when a corroborating release is available.
    spelling = canonical
    cover_source = None
    # Link storefront and cover release are separate choices. A CN compilation
    # link must not displace a verified studio-album cover for the same recording.
    cover_candidates = {
        (r['provider'], r['source']): r
        for r in [*leaders, *selected]
        if (r['provider'] == 'itunes' or r in selected)
        and (
            (r['provider'], r['id']) == (canonical['provider'], canonical['id'])
            or match.same_recording(canonical, r)
        )
    }
    for candidate in sorted(cover_candidates.values(), key=release_order):
        if candidate.get('artwork') and load_artwork(candidate['artwork'], artwork_dir) is not None:
            cover_source = candidate
            break
    album_source = cover_source or selected[0]
    known_release = next(
        (
            r
            for r in releases
            if match.album_key(r['title']) == match.album_key(album_source['album'])
            and r['status'] == 'Official'
            and r['type'] in ('Album', 'EP')
            and not r['secondary']
        ),
        None,
    )
    album = known_release['title'] if known_release else match.display_title(album_source['album'])
    if not known_release:
        warnings.append('采用平台收录的发行与封面；尚未交叉证实最早正式专辑。')
    if cover_source is None:
        warnings.append('封面暂缺，使用缺失占位，不阻止入队。')
    sources = list(dict.fromkeys(r['source'] for r in selected + evidence[:1]))
    if selection:
        sources.extend(selection['sources'])
    if known_release and known_release['source']:
        sources.append(known_release['source'])
    if cover_source:
        sources.extend([cover_source['source'], cover_source['artwork_source']])
    used_aliases = []
    for row in selected + ([cover_source] if cover_source else []):
        for proof in row.get('alias_evidence', []):
            if proof not in used_aliases:
                used_aliases.append(proof)
    for proof in used_aliases:
        sources.extend(proof.get('sources', [proof.get('source', '')]))
    sources = list(dict.fromkeys(source for source in sources if source))
    track = dict(
        artist=match.display_artist(spelling),
        title=match.display_title(spelling['title']),
        artist_credits=spelling.get('artist_credits', []),
        featured_artists=match.credit_parts(spelling['title'])[1],
        album=album,
        version='',
        artist_id=(evidence[0] if evidence else spelling)['artist_id'],
        apple=chosen.get('itunes', {}).get('source', ''),
        apple_region=chosen.get('itunes', {}).get('region', ''),
        netease=chosen.get('netease', {}).get('source', ''),
        artwork=cover_source['artwork'] if cover_source else '',
        artwork_source=cover_source['artwork_source'] if cover_source else '',
        artwork_evidence=cover_source,
        sources=sources[:8],
        checked_at=s.stamp(s.utcnow()),
        checked_by='automatic',
        platform_evidence=selected,
        alias_evidence=used_aliases,
        rule_version=RULE_VERSION,
        recording_selection=selection,
    )
    for key in ('apple', 'netease'):
        if not track[key]:
            warnings.append(
                ('Apple Music' if key == 'apple' else '网易云')
                + '链接缺失：已接受，无需管理员处理。'
            )
    if track['apple_region'] and track['apple_region'] != 'CN':
        warnings.append('Apple Music 使用已查到的海外区链接，国区查询未找到可采用条目。')
    report.update(
        resolved=True,
        track=track,
        reasons=['艺人和曲名匹配，未发现身份冲突；版本按提名保留，重制标签省略。'],
        corrections=[
            dict(field=k, before=original[k], after=track[k])
            for k in ('artist', 'title')
            if original[k] != track[k]
        ],
    )
    if selection:
        report['reasons'].append(selection['reason'])
    return report


def enqueue(conn, nomination_id):
    now = s.stamp(s.utcnow())
    with conn:
        row = conn.execute('SELECT status FROM nominations WHERE id=?', (nomination_id,)).fetchone()
        if not row or row['status'] != 'pending':
            raise ValueError('仅处理待确认提名；已就绪或已排期的内容不会被自动改写。')
        conn.execute(
            """INSERT INTO enrichment_jobs (nomination_id,status,updated_at)
            VALUES (?,'queued',?) ON CONFLICT(nomination_id) DO UPDATE SET
            status='queued',token='refresh',updated_at=excluded.updated_at
            WHERE enrichment_jobs.status!='running'""",
            (nomination_id, now),
        )


def job(conn, nomination_id):
    row = conn.execute(
        'SELECT * FROM enrichment_jobs WHERE nomination_id=?', (nomination_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result.pop('token', None)
    result['report'] = json.loads(result['report']) if result['report'] else None
    return result


def process_next(conn, artwork_dir):
    token, now = secrets.token_hex(16), s.utcnow()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            """SELECT n.*,j.status AS job_status,j.report AS previous_report,j.token AS previous_token
            FROM nominations n JOIN enrichment_jobs j ON j.nomination_id=n.id
            WHERE n.status='pending' AND (j.status='queued' OR (j.status='running' AND j.updated_at<?)
            OR (j.status='error' AND j.updated_at<? AND json_extract(j.report,'$.attempt')<3))
            ORDER BY n.created_at,n.id LIMIT 1""",
            (s.stamp(now - timedelta(minutes=15)), s.stamp(now - timedelta(minutes=15))),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE enrichment_jobs SET status='running',token=?,updated_at=? WHERE nomination_id=?",
            (token, s.stamp(now), row['id']),
        )
    if row['previous_token'] == 'refresh':
        music.candidates.cache_clear()
    item = s.unpack(row)
    previous = json.loads(row['previous_report']) if row['previous_report'] else {}
    attempt = 1 if row['job_status'] == 'queued' else previous.get('attempt', 0) + 1
    report = dict(rule_version=RULE_VERSION, checked_at=s.stamp(now), attempt=attempt, sides={})
    try:
        original = json.loads(item['original'])
        for side in ('a', 'b'):
            report['sides'][side] = resolve_track(original[side], artwork_dir)
        resolved = all(r['resolved'] for r in report['sides'].values())
        tracks = {side: report['sides'][side]['track'] for side in ('a', 'b')}
        if (
            resolved
            and match.key(tracks['a']['artist']) == match.key(tracks['b']['artist'])
            and match.key(tracks['a']['title']) == match.key(tracks['b']['title'])
        ):
            resolved = False
            report['error'] = '两侧指向同一曲目，不能自动创建对决。'
        if match.variants(item['notes']) - set().union(
            *(match.variants(original[side]['title']) for side in ('a', 'b'))
        ):
            resolved = False
            report['error'] = '备注中包含未在曲名中指定的版本要求，无法确定对应录音。'
        if resolved:
            # Share validation with manual review before changing the queue.
            form = {'verified': '1', 'allow_missing': '1'}
            for side in ('a', 'b'):
                track = tracks[side]
                form.update({f'{side}_{k}': v for k, v in track.items() if isinstance(v, str)})
                form[f'{side}_sources'] = '\n'.join(track['sources'])
                validated = s.track(form, side, review=True)
                track.update(validated, checked_by='automatic')
        state = 'complete' if resolved else 'review'
        if not resolved and any(
            query.get('error')
            for result in report['sides'].values()
            if not result['resolved']
            for query in result.get('queries', [])
        ):
            state = 'error'
            report['error'] = (
                '部分来源暂不可用，15 分钟后自动重试。'
                if attempt < 3
                else '已尝试 3 次仍未完成，可在来源恢复后重新查询。'
            )
    except Exception:
        # Keep the queue alive after provider/schema failures without leaking raw payloads.
        state, resolved = 'error', False
        report['error'] = '处理未完成，可重新查询；原始提名已保留。'
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT * FROM nominations WHERE id=?', (item['id'],)).fetchone()
        current_job = conn.execute(
            'SELECT token FROM enrichment_jobs WHERE nomination_id=?', (item['id'],)
        ).fetchone()
        if not current_job or current_job['token'] != token:
            return {'id': item['id'], 'status': 'superseded'}
        if (
            not current
            or current['status'] != 'pending'
            or any(current[k] != row[k] for k in ('a', 'b', 'original'))
        ):
            state, resolved = 'superseded', False
        if resolved:
            conn.execute(
                "UPDATE nominations SET a=?,b=?,status='ready' WHERE id=?",
                (s.encode(tracks['a']), s.encode(tracks['b']), item['id']),
            )
        conn.execute(
            'UPDATE enrichment_jobs SET status=?,report=?,updated_at=? WHERE nomination_id=?',
            (state, s.encode(report), s.stamp(s.utcnow()), item['id']),
        )
    return {'id': item['id'], 'status': state}
