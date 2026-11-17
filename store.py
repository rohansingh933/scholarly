"""Helpers to write scholarship rows (used by seed, admin forms and the AI updater)."""
import re

FIELDS = [
    "name", "provider", "provider_type", "description", "amount_text", "amount_per_year",
    "courses", "levels", "years", "min_age", "max_age", "gender", "categories", "states",
    "max_income", "income_rules", "min_percentage", "disability_only", "needs_check", "keywords",
    "documents", "essay_required", "essay_details", "other_requirements",
    "selection_process", "deadline", "deadline_note", "apply_url",
    "source", "source_url", "status", "verified_on", "name_key",
]
DEFAULTS = {
    "provider_type": "private", "courses": "all", "levels": "all", "years": "all",
    "gender": "any", "categories": "all", "states": "all", "disability_only": 0,
    "essay_required": 0, "source": "manual", "status": "active",
}
COMMA_LISTS = ("courses", "levels", "years", "categories", "states")
LINE_LISTS = ("documents", "other_requirements")
_STOP = {"the", "of", "for", "and", "in", "to", "a", "an", "scholarship", "scholarships",
         "scheme", "programme", "program", "award", "awards", "by"}


def name_key(name):
    """Normalised name used to spot duplicates ('Kotak Kanya Scholarship 2026-27' == 'Kotak Kanya')."""
    s = (name or "").lower()
    s = re.sub(r"\b20\d\d(\s*[-–/]\s*(20)?\d{2})?\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(w for w in s.split() if w not in _STOP)


def _prepare(rec):
    out = {}
    for f in FIELDS:
        v = rec.get(f, DEFAULTS.get(f))
        if f in COMMA_LISTS:
            items = v if isinstance(v, (list, tuple)) else str(v or "").split(",")
            items = [str(i).strip().lower() for i in items if str(i).strip()]
            v = ",".join(items) or ("any" if f == "gender" else "all")
        elif f in LINE_LISTS:
            items = v if isinstance(v, (list, tuple)) else str(v or "").splitlines()
            v = "\n".join(str(i).strip() for i in items if str(i).strip()) or None
        elif f == "keywords":
            items = v if isinstance(v, (list, tuple)) else str(v or "").split(",")
            v = ", ".join(str(i).strip() for i in items if str(i).strip()) or None
        elif f in ("disability_only", "essay_required"):
            v = 1 if v else 0
        elif v == "":
            v = None
        out[f] = v
    out["name_key"] = name_key(out["name"])
    return out


def insert_scholarship(conn, rec):
    data = _prepare(rec)
    cols = ", ".join(data)
    marks = ", ".join(f":{k}" for k in data)
    cur = conn.execute(f"INSERT INTO scholarships ({cols}) VALUES ({marks})", data)
    return cur.lastrowid


def update_scholarship(conn, sid, rec):
    data = _prepare(rec)
    sets = ", ".join(f"{k} = :{k}" for k in data)
    data["_id"] = sid
    conn.execute(f"UPDATE scholarships SET {sets} WHERE id = :_id", data)
