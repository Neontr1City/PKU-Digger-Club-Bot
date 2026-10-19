import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from cricket import db, worker


@pytest.mark.parametrize('slow_task', ['resolve_one', 'notify_one', 'deliver_one'])
def test_slow_external_task_does_not_block_minute_scheduler(tmp_path, monkeypatch, slow_task):
    path = tmp_path / 'worker.sqlite3'
    db.initialize(path)
    started, release = threading.Event(), threading.Event()
    ticks, lookups, waits = [], [], []

    def resolve(config):
        lookups.append(True)
        started.set()
        assert release.wait(5)

    def tick(conn, base_url):
        ticks.append(True)
        return {'closed': 0, 'prepared': False}

    class Stop:
        def set(self):
            pass

        def is_set(self):
            return len(ticks) == 2

        def wait(self, seconds):
            if seconds == 5:
                return
            waits.append(seconds)
            assert started.wait(5)
            if len(ticks) == 2:
                release.set()

    monkeypatch.setattr(worker, 'resolve_one', lambda config: None)
    monkeypatch.setattr(worker, 'notify_one', lambda config: None)
    monkeypatch.setattr(worker, 'deliver_one', lambda config: None)
    monkeypatch.setattr(worker, slow_task, resolve)
    monkeypatch.setattr(worker.s, 'tick', tick)
    monkeypatch.setattr(worker.time, 'time', lambda: 12.5)
    try:
        worker.run(
            dict(
                DATABASE=path,
                PUBLIC_BASE_URL='https://example.com',
                ADMIN_EMAIL_ENABLED=True,
                WECHAT_SEND_ENABLED=True,
            ),
            Stop(),
        )
    finally:
        release.set()
    assert len(ticks) == 2 and len(lookups) == 1
    assert waits == [47.5, 47.5]


@pytest.mark.parametrize('failed_task', ['resolve_one', 'notify_one', 'deliver_one', 'tick'])
def test_task_failure_does_not_stop_scheduler_or_other_tasks(
    tmp_path, monkeypatch, capsys, failed_task
):
    path = tmp_path / 'worker.sqlite3'
    db.initialize(path)
    failed, completed, retried, stopped = (threading.Event() for _ in range(4))
    ticks, attempts, cycles, escaped = [], [], [], []

    def fail_once(*args):
        attempts.append(True)
        if len(attempts) == 1:
            failed.set()
            raise sqlite3.OperationalError('database is locked; private mail content')
        retried.set()

    class ObservedPool(ThreadPoolExecutor):
        def submit(self, fn, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            future.add_done_callback(lambda result: completed.set() if result.exception() else None)
            return future

    def tick(*args):
        ticks.append(True)
        if failed_task == 'tick':
            fail_once()
        return {'closed': 0, 'prepared': False}

    class Stop:
        set = stopped.set
        is_set = stopped.is_set

        def wait(self, seconds):
            if seconds == 5:
                return stopped.wait(0.005)
            cycles.append(True)
            if len(cycles) == 1:
                assert (failed if failed_task == 'tick' else completed).wait(2)
            else:
                assert retried.wait(2)
            if len(cycles) == 3:
                stopped.set()

    for task in ('resolve_one', 'notify_one', 'deliver_one'):
        monkeypatch.setattr(worker, task, fail_once if task == failed_task else lambda config: None)
    monkeypatch.setattr(worker.s, 'tick', tick)
    monkeypatch.setattr(worker.time, 'time', lambda: 12.5)
    monkeypatch.setattr(worker, 'ThreadPoolExecutor', ObservedPool)

    def run():
        try:
            worker.run(
                dict(
                    DATABASE=path,
                    PUBLIC_BASE_URL='https://example.com',
                    ADMIN_EMAIL_ENABLED=True,
                    WECHAT_SEND_ENABLED=True,
                ),
                Stop(),
            )
        except BaseException as error:
            escaped.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        thread.join(3)
        assert not thread.is_alive(), 'scheduler became stuck waiting for its delivery loop'
        assert not escaped
        assert len(ticks) == 3
        assert len(attempts) >= 2
    finally:
        stopped.set()
        thread.join(3)
    output = capsys.readouterr().out
    assert 'OperationalError' in output
    assert 'private mail content' not in output
