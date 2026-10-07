"""Bounded HTTP check on disposable data; never accepts a production URL/database.

Run from the repo: uv run python deploy/check_small_group.py --report output/check.json
Uses the production Gunicorn worker/thread counts, synthetic cached covers and no worker,
SMTP or WeChat process. Cloud runs should additionally limit the temporary container.
"""

import argparse
import http.cookiejar
import json
import math
import os
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPHandler,
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from cricket import artwork, db  # noqa: E402
from cricket import service as s  # noqa: E402


def seed(directory):
    database = directory / 'isolated.sqlite3'
    db.initialize(database)
    cache = directory / 'output' / 'artwork'
    cache.mkdir(parents=True)
    now = s.utcnow()
    today = now.astimezone(s.SHANGHAI).date()
    with db.connect(database) as conn:
        for offset in (-1, 0):
            form = dict(
                submission_id=secrets.token_hex(16),
                nominator='合成样本',
                a_artist='测试艺人 A',
                a_title='测试歌曲 A',
                b_artist='测试艺人 B',
                b_title='测试歌曲 B',
            )
            s.nominate(conn, form)
            for side, color in [('a', '#dc3652'), ('b', '#3562a2')]:
                source = f'https://is1-ssl.mzstatic.com/synthetic-{side}.png'
                Image.new('RGB', (600, 600), color).save(artwork.cache_path(source, cache))
                form.update(
                    {
                        f'{side}_artwork': source,
                        f'{side}_artwork_source': 'https://example.com/synthetic',
                        f'{side}_sources': 'https://example.com/synthetic',
                        f'{side}_album': '测试专辑',
                    }
                )
            s.review(conn, offset + 2, dict(form, verified='1', allow_missing='1'))
            start = now + timedelta(days=offset, minutes=-1)
            end = now + timedelta(minutes=30) if offset == 0 else now - timedelta(minutes=1)
            s.create_round(
                conn,
                (today + timedelta(days=offset)).isoformat(),
                now=start,
                demo_window=(start, end),
            )
        s.close_due(conn)
    return database, (today - timedelta(days=1)).isoformat()


def run(report_path):
    results, request_rows, lock = [], [], threading.Lock()
    with tempfile.TemporaryDirectory(prefix='pku-small-group-') as temp:
        directory = Path(temp)
        database, yesterday = seed(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = dict(
            os.environ,
            DATABASE=str(database),
            OUTPUT_DIR=str(directory / 'output'),
            SECRET_KEY=secrets.token_hex(32),
            ADMIN_PASSWORD=secrets.token_hex(24),
            PUBLIC_BASE_URL=base,
            DEMO_MODE='1',
            WECHAT_SEND_ENABLED='0',
            WECHAT_DESKTOP_ENABLED='0',
            ADMIN_EMAIL_ENABLED='0',
        )
        process = None
        log = (directory / 'gunicorn.log').open('w+')

        def stop_server(child):
            if child and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)

        def start_server():
            child = subprocess.Popen(
                [
                    sys.executable,
                    '-m',
                    'gunicorn',
                    '--bind',
                    f'127.0.0.1:{port}',
                    '--workers',
                    '1',
                    '--threads',
                    '4',
                    '--timeout',
                    '60',
                    'cricket:create_app()',
                ],
                env=env,
                start_new_session=True,
                stdout=log,
                stderr=log,
            )
            for _ in range(100):
                try:
                    with client().open(base + '/health', timeout=1) as response:
                        if response.status == 200:
                            return child
                except OSError:
                    pass
                if child.poll() is not None:
                    raise RuntimeError('Isolated server failed to start')
                time.sleep(0.1)
            stop_server(child)
            raise RuntimeError('Isolated server startup timeout')

        def client():
            # HTTP-only loopback: don't allocate a TLS trust store for every fake visitor.
            opener = OpenerDirector()
            for handler in (
                ProxyHandler({}),
                HTTPHandler(),
                HTTPDefaultErrorHandler(),
                HTTPRedirectHandler(),
                HTTPErrorProcessor(),
                HTTPCookieProcessor(http.cookiejar.CookieJar()),
            ):
                opener.add_handler(handler)
            return opener

        def request(opener, phase, path, data=None, expected=200):
            started = time.perf_counter()
            body = b''
            status = 0
            try:
                with opener.open(
                    Request(
                        base + path, data=urlencode(data).encode() if data is not None else None
                    ),
                    timeout=15,
                ) as response:
                    body, status = response.read(), response.status
            except HTTPError as error:
                status, body = error.code, error.read()
            except OSError:
                pass
            elapsed = time.perf_counter() - started
            with lock:
                request_rows.append(
                    dict(phase=phase, seconds=elapsed, status=status, expected=expected)
                )
            if status != expected:
                raise AssertionError(f'{phase}: expected {expected}, received {status}')
            return (
                body.decode() if path.endswith('.html') or path in ('/today', '/nominate') else body
            )

        def csrf(html):
            return re.search(r'name="csrf" value="([^"]+)"', html)[1]

        def vote_visitor(i):
            opener = client()
            html = request(opener, '200_visitors_20_concurrent', '/today')
            for path in re.findall(r'src="(/artwork/[^"]+)"', html):
                request(opener, 'cached_covers', path)
            request(opener, 'static_assets', '/static/style.css')
            request(
                opener,
                'vote_submit',
                '/vote/2',
                {'csrf': csrf(html), 'choice': 'a' if i % 2 else 'b'},
            )
            # Repeat identical submissions on 20 browsers: must not add votes.
            if i < 20:
                request(
                    opener,
                    'repeat_vote',
                    '/vote/2',
                    {'csrf': csrf(html), 'choice': 'a' if i % 2 else 'b'},
                )

        def nominate_visitor(i):
            opener = client()
            html = request(opener, 'nomination_form', '/nominate')
            form = dict(
                csrf=csrf(html),
                submission_id=re.search(r'name="submission_id" value="([^"]+)"', html)[1],
                nominator=f'合成样本 {i}',
                a_artist='A',
                a_title='A',
                b_artist='B',
                b_title='B',
            )
            request(opener, 'nomination_submit', '/nominate', form)
            request(opener, 'repeat_nomination', '/nominate', form)

        def phase(name, count, concurrency, action):
            # Do not continue if the shared small VM has less than 96 MiB available.
            memory = Path('/proc/meminfo')
            if memory.exists():
                available = int(re.search(r'MemAvailable:\s+(\d+)', memory.read_text())[1])
                if available < 96 * 1024:
                    raise RuntimeError('Shared host memory guard stopped the bounded check')
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                list(pool.map(action, range(count)))
            results.append(
                dict(
                    name=name,
                    operations=count,
                    concurrency=concurrency,
                    elapsed_s=round(time.perf_counter() - started, 3),
                )
            )
            print(json.dumps(results[-1]), flush=True)

        try:
            process = start_server()
            phase('visits_and_votes', 200, 20, vote_visitor)
            phase(
                'short_read_burst', 200, 50, lambda i: request(client(), 'read_burst_50', '/today')
            )
            phase('nominations_with_replays', 20, 10, nominate_visitor)
            phase(
                'result_images',
                12,
                4,
                lambda i: request(client(), 'result_images', f'/rounds/{yesterday}/result/1.png'),
            )
            with db.connect(database) as conn:
                counts = dict(
                    conn.execute(
                        'SELECT choice,count(*) FROM votes WHERE match_id=2 GROUP BY choice'
                    )
                )
                assert counts == {'a': 100, 'b': 100}, counts
                assert conn.execute('SELECT count(*) FROM nominations').fetchone()[0] == 22
                assert conn.execute('SELECT count(*) FROM enrichment_jobs').fetchone()[0] == 22
                assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                with sqlite3.connect(directory / 'backup.sqlite3') as backup:
                    conn.backup(backup)
                    assert backup.execute('SELECT count(*) FROM votes').fetchone()[0] == 200
                    assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            stop_server(process)
            process = start_server()
            request(client(), 'after_restart', '/today')
            opener = client()
            html = request(opener, 'deadline_page', '/today')
            with db.connect(database) as conn:
                with conn:
                    conn.execute(
                        'UPDATE rounds SET ends_at=? WHERE id=2',
                        (s.stamp(s.utcnow() - timedelta(seconds=1)),),
                    )
                s.close_due(conn)
                snapshot = conn.execute('SELECT snapshot FROM rounds WHERE id=2').fetchone()[0]
            request(opener, 'after_deadline', '/vote/2', {'csrf': csrf(html), 'choice': 'a'})
            with db.connect(database) as conn:
                assert (
                    conn.execute('SELECT count(*) FROM votes WHERE match_id=2').fetchone()[0] == 200
                )
                assert (
                    conn.execute('SELECT snapshot FROM rounds WHERE id=2').fetchone()[0] == snapshot
                )
            request(client(), 'invalid_csrf', '/vote/2', {'csrf': 'invalid', 'choice': 'b'}, 400)
            request(client(), 'oversize', '/nominate', {'notes': 'x' * 70000}, 413)
            log.flush()
            log.seek(0)
            errors = log.read()
            assert 'Traceback' not in errors and 'WORKER TIMEOUT' not in errors
            report = dict(
                passed=True,
                phases=results,
                requests=len(request_rows),
                checks={
                    'votes_exactly_200': True,
                    'repeat_votes_no_duplicates': True,
                    '20_nominations_no_duplicates': True,
                    'backup_restore_readable': True,
                    'app_restart_persistence': True,
                    'deadline_frozen': True,
                    'csrf_and_body_limit': True,
                },
                timings={},
            )
            for name in sorted({r['phase'] for r in request_rows}):
                rows = [r for r in request_rows if r['phase'] == name]
                values = sorted(r['seconds'] for r in rows)
                report['timings'][name] = dict(
                    requests=len(values),
                    p50_ms=round(values[math.ceil(len(values) * 0.5) - 1] * 1000),
                    p95_ms=round(values[math.ceil(len(values) * 0.95) - 1] * 1000),
                    max_ms=round(max(values) * 1000),
                    unexpected_statuses=sum(r['status'] != r['expected'] for r in rows),
                )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(report, ensure_ascii=False), flush=True)
        except Exception as error:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    dict(
                        passed=False, error=str(error), phases=results, requests=len(request_rows)
                    ),
                    indent=2,
                )
                + '\n'
            )
            raise
        finally:
            stop_server(process)
            log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    run(parser.parse_args().report)
