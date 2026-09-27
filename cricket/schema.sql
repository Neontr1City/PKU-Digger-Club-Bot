PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS nominations (
 id INTEGER PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE,
 nominator TEXT NOT NULL, original TEXT NOT NULL,
 a TEXT NOT NULL, b TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','ready','skipped','scheduled')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES ('switch_time','18:00'),('automatic','0');
CREATE TABLE IF NOT EXISTS overrides (day TEXT PRIMARY KEY, count INTEGER NOT NULL CHECK(count BETWEEN 0 AND 20));
CREATE TABLE IF NOT EXISTS rounds (
 id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE, starts_at TEXT NOT NULL,
 ends_at TEXT NOT NULL, snapshot TEXT, closed_at TEXT
);
CREATE TABLE IF NOT EXISTS matches (
 id INTEGER PRIMARY KEY, round_id INTEGER NOT NULL REFERENCES rounds(id),
 nomination_id INTEGER NOT NULL UNIQUE REFERENCES nominations(id),
 position INTEGER NOT NULL, nominator TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
 match_id INTEGER NOT NULL REFERENCES matches(id), voter TEXT NOT NULL,
 choice TEXT NOT NULL CHECK(choice IN ('a','b')), updated_at TEXT NOT NULL,
 PRIMARY KEY (match_id,voter)
);
CREATE TABLE IF NOT EXISTS dispatches (
 day TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'prepared', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enrichment_jobs (
 nomination_id INTEGER PRIMARY KEY REFERENCES nominations(id),
 status TEXT NOT NULL DEFAULT 'queued', token TEXT NOT NULL DEFAULT '',
 report TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
