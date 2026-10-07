PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS nominations (
 id INTEGER PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE,
 nominator TEXT NOT NULL, original TEXT NOT NULL,
 a TEXT NOT NULL, b TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','ready','skipped','scheduled')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES ('switch_time','12:00'),('cutoff_time','11:59'),('automatic','0');
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
CREATE TABLE IF NOT EXISTS email_notifications (
 nomination_id INTEGER PRIMARY KEY REFERENCES nominations(id),
 status TEXT NOT NULL CHECK(status IN ('sending','sent','failed')),
 attempts INTEGER NOT NULL, message_id TEXT NOT NULL,
 retry_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wechat_deliveries (
 key TEXT PRIMARY KEY, day TEXT NOT NULL REFERENCES dispatches(day), position INTEGER NOT NULL,
 target TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
 UNIQUE(day,position,target)
);
CREATE TABLE IF NOT EXISTS wechat_incidents (
 id INTEGER PRIMARY KEY, reason TEXT NOT NULL, started_at TEXT NOT NULL, recovered_at TEXT,
 recovery_started_at TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, message_id TEXT NOT NULL, retry_at TEXT NOT NULL, sent_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS wechat_one_open_incident
 ON wechat_incidents((1)) WHERE recovered_at IS NULL;
CREATE TABLE IF NOT EXISTS wechat_login_notifications (
 request_id TEXT PRIMARY KEY, sent_at TEXT, retry_at TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, message_id TEXT NOT NULL
);
