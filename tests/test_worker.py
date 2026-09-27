import threading

from cricket import db, worker


def test_slow_lookup_does_not_block_minute_scheduler(tmp_path, monkeypatch):
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
            waits.append(seconds)
            assert started.wait(5)
            if len(ticks) == 2:
                release.set()

    monkeypatch.setattr(worker, 'resolve_one', resolve)
    monkeypatch.setattr(worker.s, 'tick', tick)
    monkeypatch.setattr(worker.time, 'time', lambda: 12.5)
    try:
        worker.run(dict(DATABASE=path, PUBLIC_BASE_URL='https://example.com'), Stop())
    finally:
        release.set()
    assert len(ticks) == 2 and len(lookups) == 1
    assert waits == [47.5, 47.5]
