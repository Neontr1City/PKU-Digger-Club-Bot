import threading

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
