"""A minute scheduler with one separate nomination lookup at a time."""

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from . import db, enrichment, notifications, wechat
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


def deliver_one(config):
    with closing(db.connect(config['DATABASE'])) as conn:
        try:
            result = wechat.dispatch_next(conn, config)
        except Exception:
            # Keep website scheduling and offline monitoring alive; no private error dumps.
            result = {'state': 'error'}
        try:
            alert = wechat.monitor(conn, config)
        except Exception:
            alert = {'state': 'error'}
    if result or alert:
        print(s.encode({'wechat': result, 'alert': alert}), flush=True)


def delivery_loop(config, stop):
    while not stop.is_set():
        deliver_one(config)
        stop.wait(5)


def run(config, stop):
    # Each thread owns its connection. Slow external searches cannot delay the next tick.
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = mail_pending = None
        delivery_pending = (
            pool.submit(delivery_loop, config, stop) if wechat.enabled(config) else None
        )
        while not stop.is_set():
            if delivery_pending and delivery_pending.done():
                delivery_pending.result()
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
