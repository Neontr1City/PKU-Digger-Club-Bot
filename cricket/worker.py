"""A minute scheduler with one separate nomination lookup at a time."""

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from . import db, enrichment, notifications
from . import service as s


def resolve_one(config):
    with closing(db.connect(config['DATABASE'])) as conn:
        result = enrichment.process_next(conn, Path(config['OUTPUT_DIR']) / 'artwork')
    if result:
        print(s.encode(result), flush=True)


def notify_one(config):
    with closing(db.connect(config['DATABASE'])) as conn:
        result = notifications.process_next(conn, config)
    if result:
        print(s.encode(result), flush=True)


def run(config, stop):
    # Each thread owns its connection. Slow external searches cannot delay the next tick.
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = mail_pending = None
        while not stop.is_set():
            with closing(db.connect(config['DATABASE'])) as conn:
                result = s.tick(conn, config['PUBLIC_BASE_URL'])
            print(s.encode({k: v for k, v in result.items() if k != 'messages'}), flush=True)
            if pending is None or pending.done():
                if pending:
                    pending.result()
                pending = pool.submit(resolve_one, config)
            if notifications.enabled(config) and (mail_pending is None or mail_pending.done()):
                if mail_pending:
                    mail_pending.result()
                mail_pending = pool.submit(notify_one, config)
            # Align to wall-clock minutes instead of adding a minute after each lookup.
            stop.wait(60 - time.time() % 60)
