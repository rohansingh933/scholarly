"""Daily limits for the AI features that run on the site's OWN key.

Students can use essay help and the scholarship search without a key of their own. That spends the
site owner's quota, so each student gets a small daily allowance and there is a cap for everyone
combined. Requests made with a student's own key are not counted.
Counts live in users.db (table `usage`).
"""
import os
from datetime import date


class QuotaError(Exception):
    """The daily allowance is used up. The message is safe to show to the student."""


LABEL = {"essay": "essay reviews", "search": "searches"}


def _int(name, default):
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def limits(kind):
    """(per student per day, for everyone per day). Read on every call so settings can change."""
    if kind == "essay":
        return _int("ESSAY_PER_USER_DAILY", 5), _int("ESSAY_GLOBAL_DAILY", 150)
    return _int("SEARCH_PER_USER_DAILY", 1), _int("SEARCH_GLOBAL_DAILY", 20)


def _today():
    return date.today().isoformat()


def _counts(udb, uid, kind):
    day = _today()
    mine = udb.execute("SELECT COUNT(*) FROM usage WHERE kind = ? AND used_on = ? AND user_id = ?",
                       (kind, day, uid)).fetchone()[0]
    total = udb.execute("SELECT COUNT(*) FROM usage WHERE kind = ? AND used_on = ?", (kind, day)).fetchone()[0]
    return mine, total


def remaining(udb, uid, kind):
    per_user, per_day = limits(kind)
    mine, total = _counts(udb, uid, kind)
    return {"user_left": max(0, per_user - mine), "user_limit": per_user,
            "global_left": max(0, per_day - total)}


def take(udb, uid, kind):
    """Reserve one use or raise QuotaError. Returns a usage id to pass to release() if the call fails."""
    per_user, per_day = limits(kind)
    mine, total = _counts(udb, uid, kind)
    word = LABEL[kind]
    if total >= per_day:
        raise QuotaError(f"The free {word} for today have run out for everyone. "
                         "Try again tomorrow, or use your own key.")
    if mine >= per_user:
        raise QuotaError(f"You've used your free {word} for today. They reset tomorrow, "
                         "or you can use your own key.")
    cur = udb.execute("INSERT INTO usage (user_id, kind, used_on) VALUES (?, ?, ?)", (uid, kind, _today()))
    udb.commit()
    return cur.lastrowid


def release(udb, usage_id):
    """Give the use back (the AI provider failed, so it shouldn't cost the student their allowance)."""
    if usage_id:
        udb.execute("DELETE FROM usage WHERE id = ?", (usage_id,))
        udb.commit()


def today_totals(udb):
    day = _today()
    rows = udb.execute("SELECT kind, COUNT(*) AS n FROM usage WHERE used_on = ? GROUP BY kind", (day,)).fetchall()
    out = {"essay": 0, "search": 0}
    out.update({r["kind"]: r["n"] for r in rows})
    return out
