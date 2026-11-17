"""Database layer: two separate SQLite files.

  data/scholarships.db  - the scholarship catalogue (+ AI update run history)
  data/users.db         - student registrations, profiles, saved scholarships
"""
import os
import sqlite3

from flask import g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

SCHOLARSHIPS_DB = os.path.join(DATA_DIR, "scholarships.db")
USERS_DB = os.path.join(DATA_DIR, "users.db")

SCHOLARSHIPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS scholarships (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    provider         TEXT NOT NULL,
    provider_type    TEXT NOT NULL CHECK (provider_type IN ('government', 'private')),
    description      TEXT,
    amount_text      TEXT,
    amount_per_year  INTEGER,            -- INR, used for sorting
    -- eligibility (comma-separated lowercase lists; 'all' = no restriction)
    courses          TEXT NOT NULL DEFAULT 'all',
    levels           TEXT NOT NULL DEFAULT 'all',
    years            TEXT NOT NULL DEFAULT 'all',
    min_age          INTEGER,
    max_age          INTEGER,
    gender           TEXT NOT NULL DEFAULT 'any',
    categories       TEXT NOT NULL DEFAULT 'all',
    states           TEXT NOT NULL DEFAULT 'all',
    max_income       INTEGER,            -- annual family income cap in INR
    income_rules     TEXT,               -- per-category caps, e.g. 'sc:450000,obc:200000'
    min_percentage   REAL,
    disability_only  INTEGER NOT NULL DEFAULT 0,
    needs_check      TEXT,               -- condition a profile can't capture, e.g. 'top-20 entrance rank'
    keywords         TEXT,
    -- what the student must prepare
    documents        TEXT,               -- newline separated
    essay_required   INTEGER NOT NULL DEFAULT 0,
    essay_details    TEXT,
    other_requirements TEXT,             -- newline separated
    selection_process  TEXT,
    -- dates + links
    deadline         TEXT,               -- ISO date, NULL = rolling / unknown
    deadline_note    TEXT,
    apply_url        TEXT,
    -- bookkeeping
    source           TEXT NOT NULL DEFAULT 'seed',   -- seed | ai | manual
    source_url       TEXT,
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'pending', 'rejected')),
    verified_on      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    name_key         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sch_status   ON scholarships(status);
CREATE INDEX IF NOT EXISTS idx_sch_deadline ON scholarships(deadline);
CREATE INDEX IF NOT EXISTS idx_sch_namekey  ON scholarships(name_key);

CREATE TABLE IF NOT EXISTS update_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,
    provider     TEXT,
    focus        TEXT,
    triggered_by TEXT NOT NULL DEFAULT 'admin',      -- 'admin' or 'user:<id>'
    status       TEXT NOT NULL DEFAULT 'running',    -- running | done | failed
    found        INTEGER NOT NULL DEFAULT 0,
    added        INTEGER NOT NULL DEFAULT 0,
    message      TEXT
);
"""

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    age           INTEGER,
    gender        TEXT,
    course        TEXT,
    level         TEXT,
    year_of_study INTEGER,
    percentage    REAL,
    category      TEXT,
    minority      INTEGER NOT NULL DEFAULT 0,
    disability    INTEGER NOT NULL DEFAULT 0,
    family_income INTEGER,
    state         TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,              -- 'essay' | 'search' (uses of the site's own AI key)
    used_on    TEXT NOT NULL,              -- ISO date
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(kind, used_on);

CREATE TABLE IF NOT EXISTS saved (
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scholarship_id INTEGER NOT NULL,
    saved_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, scholarship_id)
);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_scholarships():
    """Stand-alone connection (for background threads / CLI)."""
    return connect(SCHOLARSHIPS_DB)


def open_users():
    return connect(USERS_DB)


def get_sdb():
    if "sdb" not in g:
        g.sdb = open_scholarships()
    return g.sdb


def get_udb():
    if "udb" not in g:
        g.udb = open_users()
    return g.udb


def close_dbs(_exc=None):
    for key in ("sdb", "udb"):
        conn = g.pop(key, None)
        if conn is not None:
            conn.close()


def init_db():
    for path, schema in ((SCHOLARSHIPS_DB, SCHOLARSHIPS_SCHEMA), (USERS_DB, USERS_SCHEMA)):
        conn = connect(path)
        try:
            conn.executescript(schema)
            if path == SCHOLARSHIPS_DB:   # upgrade databases created before a column existed
                have = {r["name"] for r in conn.execute("PRAGMA table_info(scholarships)")}
                for col in ("needs_check", "income_rules"):
                    if col not in have:
                        conn.execute(f"ALTER TABLE scholarships ADD COLUMN {col} TEXT")
                have_runs = {r["name"] for r in conn.execute("PRAGMA table_info(update_runs)")}
                if "triggered_by" not in have_runs:
                    conn.execute("ALTER TABLE update_runs ADD COLUMN triggered_by TEXT NOT NULL DEFAULT 'admin'")
            conn.commit()
        finally:
            conn.close()
