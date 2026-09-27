import argparse
import json
import os
import secrets
import signal
import threading
from datetime import timedelta
from pathlib import Path

from . import create_app, db, enrichment, poster
from . import service as s


def seed_demo(app):
    if not app.config['DEMO_MODE']:
        raise SystemExit('示例数据仅允许写入 DEMO_MODE=1 的隔离数据库。')
    with db.connect(app.config['DATABASE']) as conn:
        if conn.execute('SELECT COUNT(*) FROM nominations').fetchone()[0]:
            raise SystemExit('演示数据库已有数据，不重复填充。')
        songs = json.loads(Path(__file__).with_name('demo_tracks.json').read_text(encoding='utf-8'))
        now = s.utcnow()
        for index in range(5):
            a, b = songs[(index % 2) * 2 : (index % 2) * 2 + 2]
            form = {
                'submission_id': secrets.token_hex(16),
                'nominator': ['示例听众 A', '示例听众 B'][index % 2],
                'notes': '本地演示提名；曲目链接与专辑封面来源见 demo_tracks.json。',
            }
            for side, song in [('a', a), ('b', b)]:
                form.update(
                    {f'{side}_{key}': song[key] for key in ('artist', 'title', 'netease', 'apple')}
                )
            s.nominate(conn, form, now + timedelta(microseconds=index))
            if index < 4:
                for side, song in [('a', a), ('b', b)]:
                    form.update(
                        {
                            f'{side}_{key}': song[key]
                            for key in (
                                'album',
                                'version',
                                'artist_id',
                                'artwork',
                                'artwork_source',
                            )
                        }
                    )
                    form[f'{side}_sources'] = '\n'.join(song['sources'])
                form.update(verified='1')
                s.review(conn, index + 1, form)
                # The public fixture also retains platform-specific release details.
                conn.execute(
                    'UPDATE nominations SET a=?,b=? WHERE id=?',
                    (s.encode(a), s.encode(b), index + 1),
                )
                conn.commit()
        day = now.astimezone(s.SHANGHAI).date()
        yesterday = day - timedelta(days=1)
        conn.execute('INSERT INTO overrides VALUES (?,2)', (yesterday.isoformat(),))
        conn.execute('INSERT INTO overrides VALUES (?,2)', (day.isoformat(),))
        conn.commit()
        start = now - timedelta(days=1)
        end = now - timedelta(hours=2)
        previous_id = s.create_round(
            conn, yesterday.isoformat(), now=start, demo_window=(start, end)
        )
        previous = conn.execute(
            'SELECT id FROM matches WHERE round_id=? ORDER BY position', (previous_id,)
        ).fetchall()
        for match, counts in zip(previous, [(28, 19), (23, 23)]):
            for side, count in zip(('a', 'b'), counts):
                for i in range(count):
                    s.cast_vote(
                        conn, match['id'], f'demo-{side}-{i}', side, start + timedelta(hours=1)
                    )
        s.close_due(conn, now)
        s.create_round(
            conn, day.isoformat(), now, (now - timedelta(hours=1), now + timedelta(hours=23))
        )
    print('已写入隔离演示数据。所有票数均为示例，未联系微信。')


def main():
    parser = argparse.ArgumentParser(description='每日斗蛐蛐')
    parser.add_argument(
        'command',
        choices=['init', 'serve', 'demo', 'tick', 'worker', 'resolve', 'backup', 'export'],
    )
    parser.add_argument('--port', type=int, default=5057)
    args = parser.parse_args()
    if args.command == 'init':
        path = Path('.env.local')
        if path.exists():
            print('已有 .env.local，保留现有配置。')
            return
        with path.open('x') as file:
            os.chmod(path, 0o600)
            file.write(
                f'SECRET_KEY={secrets.token_hex(32)}\nADMIN_PASSWORD={secrets.token_urlsafe(20)}\nDATABASE=data/cricket.sqlite3\nOUTPUT_DIR=output\nPUBLIC_BASE_URL=http://127.0.0.1:5057\nDEMO_MODE=0\n'
            )
        print('已生成 .env.local；管理密码保存在该文件中，不输出到日志。')
        return
    app = create_app()
    if args.command == 'serve':
        app.run(host='127.0.0.1', port=args.port, debug=False)
    elif args.command == 'demo':
        seed_demo(app)
    elif args.command == 'tick':
        with db.connect(app.config['DATABASE']) as conn:
            print(s.encode(s.tick(conn, app.config['PUBLIC_BASE_URL'])))
    elif args.command == 'resolve':
        with db.connect(app.config['DATABASE']) as conn:
            print(
                s.encode(
                    enrichment.process_next(conn, Path(app.config['OUTPUT_DIR']) / 'artwork')
                    or {'status': 'idle'}
                )
            )
    elif args.command == 'worker':
        # One optional minute loop; no scheduler service dependency.
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            conn = db.connect(app.config['DATABASE'])
            try:
                result = s.tick(conn, app.config['PUBLIC_BASE_URL'])
                print(s.encode({k: v for k, v in result.items() if k != 'messages'}), flush=True)
                processed = enrichment.process_next(
                    conn, Path(app.config['OUTPUT_DIR']) / 'artwork'
                )
                if processed:
                    print(s.encode(processed), flush=True)
            finally:
                conn.close()
            stop.wait(60)
    elif args.command == 'backup':
        path = Path(app.config['OUTPUT_DIR']) / 'backups'
        path.mkdir(parents=True, exist_ok=True)
        destination = path / (s.utcnow().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
        with db.connect(app.config['DATABASE']) as source, db.connect(destination) as target:
            source.backup(target)
        print(f'备份已写入 {destination}')
    elif args.command == 'export':
        path = Path(app.config['OUTPUT_DIR']) / (
            'export-' + s.utcnow().strftime('%Y%m%d-%H%M%S-%f')
        )
        path.mkdir(parents=True, exist_ok=True)
        with db.connect(app.config['DATABASE']) as conn:
            s.close_due(conn)
            nominations = []
            for row in conn.execute('SELECT * FROM nominations ORDER BY created_at,id'):
                item = s.unpack(row)
                item.pop('submission_id')
                item['original'] = json.loads(item['original'])
                item['enrichment'] = enrichment.job(conn, item['id'])
                nominations.append(item)
            (path / 'nominations.json').write_text(s.encode(nominations), encoding='utf-8')
            for row in conn.execute('SELECT day FROM rounds ORDER BY day').fetchall():
                round_ = s.round_data(conn, row['day'], admin=True)
                (path / (row['day'] + '.json')).write_text(s.encode(round_), encoding='utf-8')
                if round_['snapshot']:
                    for page in range(1, (len(round_['matches']) + 3) // 4 + 1):
                        (path / f'{row["day"]}-{page}.png').write_bytes(
                            poster.render(
                                round_,
                                page,
                                app.config['RESULT_FONT'],
                                Path(app.config['OUTPUT_DIR']) / 'artwork',
                            ).getvalue()
                        )
        print(f'提名、汇总票数和已结算结果图已导出到 {path}；不含浏览器投票标识。')


if __name__ == '__main__':
    main()
