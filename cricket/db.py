import sqlite3
from pathlib import Path


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript(Path(__file__).with_name('schema.sql').read_text())
        db.execute('BEGIN IMMEDIATE')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(wechat_incidents)')}
        if 'recovery_started_at' not in columns:
            db.execute('ALTER TABLE wechat_incidents ADD COLUMN recovery_started_at TEXT')
