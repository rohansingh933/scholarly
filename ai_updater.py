"""'Update scholarships': ask an LLM with live web search for scholarships we don't have yet.

Safety rules baked in:
  * Results are NEVER published directly. Every new record is saved with
    status='pending' and a source link, and an admin approves or rejects it.
  * Each record is validated and cleaned. Records without a source URL, with an
    expired deadline, or that duplicate something already in the database
    (including rejected ones) are dropped.
  * Only one run at a time, with a cool-down, so API credits can't be burned.

Providers (set AI_PROVIDER, or just set one key):
  gemini  - GEMINI_API_KEY, model GEMINI_MODEL (Google Search grounding)
  openai  - OPENAI_API_KEY, model OPENAI_MODEL (Responses API web_search tool)
  mock    - no network; returns canned records to test the pipeline
"""
import difflib
import json
import os
import re
import threading
from datetime import date, timedelta
from urllib.parse import urlparse

import requests

import db
import matching as m
import store

PROVIDERS = ("gemini", "openai", "mock")
MAX_RECORDS = 20
COOLDOWN = int(os.environ.get("UPDATE_COOLDOWN_SECONDS", "120"))
_lock = threading.Lock()

COURSE_SYNONYMS = {
    "engineering": ["engineer", "b.tech", "btech", "m.tech", "technology", "computer", "mechanical",
                    "civil", "electrical", "electronics", "technical"],
    "medical": ["medic", "mbbs", "nursing", "dental", "bds", "health", "paramedic", "ayush"],
    "pharmacy": ["pharm"],
    "commerce": ["commerce", "b.com", "bcom", "accounting", "finance", "chartered", "economics"],
    "management": ["management", "mba", "bba", "pgdm"],
    "science": ["science", "b.sc", "bsc", "m.sc", "msc", "research", "physics", "chemistry", "biology", "math"],
    "arts": ["arts", "humanities", "social", "journalism", "literature"],
    "law": ["law", "llb", "llm", "legal"],
    "architecture": ["architect", "design"],
    "agriculture": ["agricultur", "veterinar", "forestry", "fisheries"],
    "education": ["education", "b.ed", "teaching"],
}
# Order matters: 'postgraduate' must be tested before the looser 'graduat' in ug.
LEVEL_SYNONYMS = {"diploma": ["diploma", "polytechnic", "industrial training"],
                  "phd": ["phd", "doctor"],
                  "pg": ["postgrad", "post-grad", "master", "pg", "mba"],
                  "ug": ["undergrad", "bachelor", "graduat", "ug", "b.tech", "degree"]}


# ------------------------------------------------------------ configuration
def default_provider():
    p = os.environ.get("AI_PROVIDER", "").strip().lower()
    if p in PROVIDERS:
        return p
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "none"


def server_key(provider):
    """The site owner's own key for a provider (set as an environment variable), or ''."""
    name = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    return os.environ.get(name, "").strip() if name else ""


def essay_provider():
    """Which real provider has a server key (honours AI_PROVIDER), or None."""
    pref = os.environ.get("AI_PROVIDER", "").strip().lower()
    order = ([pref] if pref in ("gemini", "openai") else []) + [p for p in ("gemini", "openai") if p != pref]
    for p in order:
        if server_key(p):
            return p
    return None


def provider_status(provider=None):
    provider = provider or default_provider()
    if provider == "gemini":
        return {"name": "gemini", "ready": bool(os.environ.get("GEMINI_API_KEY")),
                "note": "Add GEMINI_API_KEY to the environment."}
    if provider == "openai":
        return {"name": "openai", "ready": bool(os.environ.get("OPENAI_API_KEY")),
                "note": "Add OPENAI_API_KEY to the environment."}
    if provider == "mock":
        return {"name": "mock", "ready": True, "note": "Test mode: no real search."}
    return {"name": "none", "ready": False,
            "note": "Set GEMINI_API_KEY or OPENAI_API_KEY (or AI_PROVIDER=mock to test)."}


def available_providers():
    return [p for p in PROVIDERS if provider_status(p)["ready"] and (p != "mock" or default_provider() == "mock")]


# ----------------------------------------------------------------- prompt
def build_prompt(known_names, focus, today):
    focus_line = f"Extra focus for this search: {focus}\n" if focus else ""
    known = "\n".join(f"- {n}" for n in known_names[:300]) or "(none yet)"
    return f"""You are a research assistant for an Indian scholarship portal for college students (diploma, UG, PG).
Today is {today.isoformat()}. Search the web for scholarships that are open now or open soon (deadline on or after today),
from the Government of India, state governments, and private organisations (company CSR, foundations, trusts).
{focus_line}
Do NOT repeat any scholarship already in our database:
{known}

Return up to {MAX_RECORDS} NEW scholarships as ONLY a JSON array (no markdown fences, no commentary).
Each item must have exactly these keys:
  "name": string, "provider": string, "provider_type": "government" or "private",
  "description": string (1-2 sentences), "amount_text": string or null, "amount_per_year": integer INR or null,
  "courses": list from [engineering, medical, pharmacy, commerce, management, science, arts, law, architecture, agriculture, education, other] or ["all"],
  "levels": list from [diploma, ug, pg, phd] or ["all"],
  "years": list of study years as strings like ["1","2"] or ["all"],
  "min_age": integer or null, "max_age": integer or null,
  "gender": "any", "female" or "male",
  "categories": list from [general, obc, sc, st, ews, minority] or ["all"],
  "states": list of Indian state names or ["all"],
  "max_income": integer INR annual family income cap or null,
  "min_percentage": number or null, "disability_only": true/false,
  "keywords": list of short tags,
  "documents": list of documents the student must submit (income certificate, caste certificate, ITR, marksheets...),
  "essay_required": true/false, "essay_details": string or null,
  "other_requirements": list of strings (tests, interviews, institute restrictions),
  "selection_process": string or null,
  "deadline": "YYYY-MM-DD" for the CURRENT cycle only, else null, "deadline_note": string or null,
  "apply_url": official application URL, "source_url": the exact web page where you found these details.
Rules: only include scholarships you actually found on a real web page. Never guess: use null for unknown values.
Prefer official sources (government portals, the provider's own site)."""


# -------------------------------------------------------------- providers
def _http_error(resp):
    snippet = re.sub(r"\s+", " ", resp.text or "")[:200]
    return RuntimeError(f"API returned HTTP {resp.status_code}: {snippet}")


GEMINI_FALLBACK_MODEL = "gemini-3.8-flash"


def _gemini_request(prompt, key, model):
    return requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]},
        timeout=240)


def call_gemini(prompt, key=None):
    """`key` is the caller's own key; falls back to the server's GEMINI_API_KEY.

    gemini-2.5-flash has a free Google Search allowance but Google limits new access to 2.5
    models, so if the key can't use it we retry once with a current model."""
    key = key or os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    resp = _gemini_request(prompt, key, model)
    if resp.status_code in (403, 404) and model != GEMINI_FALLBACK_MODEL:
        resp = _gemini_request(prompt, key, GEMINI_FALLBACK_MODEL)
    if resp.status_code != 200:
        raise _http_error(resp)
    data = resp.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def call_openai(prompt, key=None):
    key = key or os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1")
    resp = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "tools": [{"type": "web_search"}], "input": prompt},
        timeout=300)
    if resp.status_code != 200:
        raise _http_error(resp)
    data = resp.json()
    if data.get("output_text"):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    chunks.append(c.get("text", ""))
    return "".join(chunks)


def call_mock(_prompt, _key=None):
    soon = (date.today() + timedelta(days=40)).isoformat()
    old = (date.today() - timedelta(days=10)).isoformat()
    return json.dumps([
        {"name": "Demo Foundation Merit Scholarship 2026-27", "provider": "Demo Foundation",
         "provider_type": "private", "description": "Sample record from the mock provider.",
         "amount_text": "₹30,000 per year", "amount_per_year": 30000, "courses": ["engineering", "science"],
         "levels": ["ug"], "years": ["1", "2"], "gender": "any", "categories": ["all"], "states": ["all"],
         "max_income": 600000, "min_percentage": 70, "keywords": ["demo", "merit"],
         "documents": ["Income certificate", "Last marksheet"], "essay_required": True,
         "essay_details": "300-word essay on career goals", "deadline": soon,
         "apply_url": "https://example.org/demo-scholarship", "source_url": "https://example.org/demo-scholarship"},
        {"name": "Sample State Girls Scholarship", "provider": "Sample State Government",
         "provider_type": "government", "description": "Sample state scheme without a fixed date.",
         "gender": "female", "courses": ["all"], "levels": ["ug", "pg"], "states": ["Delhi"],
         "max_income": 300000, "documents": ["Domicile certificate", "Income certificate"],
         "deadline": None, "deadline_note": "Opens each autumn",
         "source_url": "https://example.org/state-girls"},
        {"name": "ONGC Merit Scholarship (2026-27)", "provider": "ONGC Foundation",
         "provider_type": "private", "source_url": "https://example.org/ongc-copy"},   # duplicate
        {"name": "Expired Example Award", "provider": "Old Trust", "provider_type": "private",
         "deadline": old, "source_url": "https://example.org/old"},                      # expired
        {"name": "No Source Scholarship", "provider": "Mystery Org", "provider_type": "private"},  # no source
    ])


# ------------------------------------------------------------ validation
def _clean(v, n):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:n] or None


def _url(v):
    v = str(v or "").strip()
    p = urlparse(v)
    return v[:500] if p.scheme in ("http", "https") and p.netloc else None


def _num(v, lo=0, hi=10**9, as_float=False):
    if v is None or isinstance(v, bool):
        return None
    cleaned = re.sub(r"[^\d.]", "", str(v))
    if not cleaned or cleaned == ".":
        return None
    try:
        n = float(cleaned)
    except ValueError:
        return None
    if not lo <= n <= hi:
        return None
    return n if as_float else int(n)


def _items(v, n=200, limit=15):
    if v is None:
        return []
    if isinstance(v, str):
        v = re.split(r"[,\n;]", v)
    if not isinstance(v, (list, tuple)):
        return []
    out = [_clean(i, n) for i in v]
    return [i for i in out if i][:limit]


def _map(items, synonyms):
    """Map free-text labels to our fixed vocabulary. Each label goes to the FIRST
    matching key (so dict order is priority); 'A and B' / 'A/B' are handled as two labels."""
    keys = set()
    for raw in items:
        for part in re.split(r"\s+and\s+|/|&|;", raw):
            low = part.strip().lower()
            if not low:
                continue
            if low in ("all", "any", "all courses", "all streams"):
                return ["all"]
            if low in synonyms:
                keys.add(low)
                continue
            for key, words in synonyms.items():
                if any(w in low for w in words):
                    keys.add(key)
                    break
    return sorted(keys) or ["all"]


def normalize_record(raw, today):
    """Return (record, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "not an object"
    name, provider = _clean(raw.get("name"), 200), _clean(raw.get("provider"), 200)
    if not name or not provider:
        return None, "missing name or provider"
    source_url = _url(raw.get("source_url"))
    apply_url = _url(raw.get("apply_url")) or source_url
    if not source_url:
        return None, "no source URL"
    deadline = None
    d = m.parse_date(str(raw.get("deadline") or "")[:10])
    if d:
        if d < today:
            return None, "deadline already passed"
        if d <= today + timedelta(days=730):
            deadline = d.isoformat()
    ptype = str(raw.get("provider_type") or "").lower()
    if ptype not in ("government", "private"):
        ptype = "private"
    gender = str(raw.get("gender") or "any").lower()
    cats = [c.lower() for c in _items(raw.get("categories"))]
    cat_keys = ["all"] if (not cats or "all" in cats) else sorted({c for c in cats if c in m.CATEGORY_LABELS})
    states = [m.STATE_LOOKUP[s.lower()].lower() for s in _items(raw.get("states")) if s.lower() in m.STATE_LOOKUP]
    years = [str(y) for y in _items(raw.get("years")) if str(y) in "123456" or str(y).lower() == "all"]
    rec = {
        "name": name, "provider": provider, "provider_type": ptype,
        "description": _clean(raw.get("description"), 1200),
        "amount_text": _clean(raw.get("amount_text"), 200),
        "amount_per_year": _num(raw.get("amount_per_year")),
        "courses": _map(_items(raw.get("courses")), COURSE_SYNONYMS),
        "levels": _map(_items(raw.get("levels")), LEVEL_SYNONYMS),
        "years": ["all"] if (not years or "all" in years) else years,
        "min_age": _num(raw.get("min_age"), 10, 60), "max_age": _num(raw.get("max_age"), 10, 70),
        "gender": gender if gender in ("female", "male") else "any",
        "categories": cat_keys or ["all"],
        "states": states or ["all"],
        "max_income": _num(raw.get("max_income")),
        "min_percentage": _num(raw.get("min_percentage"), 0, 100, as_float=True),
        "disability_only": bool(raw.get("disability_only")) if isinstance(raw.get("disability_only"), bool) else False,
        "keywords": _items(raw.get("keywords"), 40, 12),
        "documents": _items(raw.get("documents"), 200, 15),
        "essay_required": bool(raw.get("essay_required")) if isinstance(raw.get("essay_required"), bool) else False,
        "essay_details": _clean(raw.get("essay_details"), 400),
        "other_requirements": _items(raw.get("other_requirements"), 250, 10),
        "selection_process": _clean(raw.get("selection_process"), 400),
        "deadline": deadline, "deadline_note": _clean(raw.get("deadline_note"), 200),
        "apply_url": apply_url, "source_url": source_url,
        "source": "ai", "status": "pending",
    }
    return rec, None


def _url_key(url):
    p = urlparse(url or "")
    path = p.path.rstrip("/")
    if not p.netloc or not path:
        return None          # portal home pages (e.g. NSP) are shared by many schemes
    return p.netloc.lower().removeprefix("www.") + path.lower()


def is_duplicate(rec, known):
    """`known` is a list of (name_key, url_key) for everything already stored."""
    key = store.name_key(rec["name"])
    ukey = _url_key(rec["apply_url"]) or _url_key(rec["source_url"])
    for k, u in known:
        if not k:
            continue
        if k == key or (ukey and u and ukey == u):
            return True
        if difflib.SequenceMatcher(None, k, key).ratio() >= 0.88:
            return True
    return False


def extract_json_array(text):
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("The model did not return a JSON list.")
    return json.loads(text[start:end + 1])


# ------------------------------------------------------------ orchestration
def _execute(run_id, provider, focus, api_key=None):
    """Runs one search. `api_key` lives only in this function's memory: it is never written
    to the database, a file or the log, and is scrubbed from any error text."""
    conn = db.open_scholarships()
    found = added = 0
    status, message = "done", ""
    try:
        today = date.today()
        existing = conn.execute("SELECT name, name_key, apply_url, source_url FROM scholarships").fetchall()
        known = [(r["name_key"], _url_key(r["apply_url"]) or _url_key(r["source_url"])) for r in existing]
        prompt = build_prompt([r["name"] for r in existing], focus, today)
        text = {"gemini": call_gemini, "openai": call_openai, "mock": call_mock}[provider](prompt, api_key)
        raw_items = extract_json_array(text)
        found = len(raw_items)
        skipped = {}
        for raw in raw_items[:MAX_RECORDS * 2]:
            rec, why = normalize_record(raw, today)
            if rec and is_duplicate(rec, known):
                rec, why = None, "already in database"
            if not rec:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            store.insert_scholarship(conn, rec)
            known.append((store.name_key(rec["name"]), _url_key(rec["apply_url"]) or _url_key(rec["source_url"])))
            added += 1
        conn.commit()
        message = f"{added} new for review."
        if skipped:
            message += " Skipped: " + ", ".join(f"{n} {w}" for w, n in skipped.items()) + "."
    except Exception as exc:  # noqa: BLE001 - surface any failure to the admin
        status, message = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
        if api_key:
            message = message.replace(api_key, "***")
    finally:
        conn.execute("UPDATE update_runs SET status=?, found=?, added=?, message=?, "
                     "finished_at=datetime('now') WHERE id=?", (status, found, added, message, run_id))
        conn.commit()
        conn.close()
    return status, added, message


USER_COOLDOWN = int(os.environ.get("UPDATE_USER_COOLDOWN_SECONDS", "600"))
KEY_RE = re.compile(r"[A-Za-z0-9_.\-]{20,300}")   # Google's newer keys contain a dot (e.g. "AQ.…")


def clean_key(raw):
    """Forgive common paste slips: surrounding quotes or spaces, a 'GEMINI_API_KEY=' or 'Bearer ' prefix,
    and line breaks or spaces inside the key."""
    k = (raw or "").strip()
    k = re.sub(r"^(?:export\s+|set\s+)?[A-Za-z_]*(?:api_?key|key)\s*=\s*", "", k, flags=re.I)
    k = re.sub(r"^bearer\s+", "", k, flags=re.I)
    k = k.strip("\"'`“”‘’ ")
    return re.sub(r"\s+", "", k)


def _create_run(provider, focus, by="admin"):
    """Insert a 'running' row unless another run is active or too recent."""
    with _lock:
        conn = db.open_scholarships()
        try:
            conn.execute("UPDATE update_runs SET status='failed', message='Timed out', "
                         "finished_at=datetime('now') WHERE status='running' "
                         "AND (julianday('now') - julianday(started_at)) * 86400 > 900")
            if conn.execute("SELECT 1 FROM update_runs WHERE status='running'").fetchone():
                conn.commit()
                return None, "An update is already running."
            recent = conn.execute(
                "SELECT (julianday('now') - julianday(finished_at)) * 86400 AS ago FROM update_runs "
                "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
            if recent and recent["ago"] is not None and recent["ago"] < COOLDOWN:
                wait = int(COOLDOWN - recent["ago"])
                conn.commit()
                return None, f"The last update just finished. Try again in {wait} seconds."
            if by != "admin":
                mine = conn.execute(
                    "SELECT (julianday('now') - julianday(started_at)) * 86400 AS ago FROM update_runs "
                    "WHERE triggered_by = ? ORDER BY id DESC LIMIT 1", (by,)).fetchone()
                if mine and mine["ago"] is not None and mine["ago"] < USER_COOLDOWN:
                    wait = int((USER_COOLDOWN - mine["ago"]) // 60) + 1
                    conn.commit()
                    return None, f"You searched a moment ago. Try again in about {wait} minute{'s' if wait != 1 else ''}."
            cur = conn.execute("INSERT INTO update_runs (provider, focus, triggered_by) VALUES (?, ?, ?)",
                               (provider, focus or None, by))
            conn.commit()
            return cur.lastrowid, ""
        finally:
            conn.close()


def start_update(provider=None, focus="", api_key=None, by="admin"):
    """Start a background run.

    api_key: the caller's own key (a student's, or one the admin pasted). When given it is used
    for this one search only. `by` is 'admin' or 'user:<id>' (users get a per-person cool-down)."""
    provider = provider or default_provider()
    api_key = clean_key(api_key) or None
    if api_key:
        if provider not in ("gemini", "openai"):
            return False, "Choose Gemini or OpenAI for your key."
        if not KEY_RE.fullmatch(api_key):
            return False, "That doesn't look like a valid API key. Copy it again from your provider's site."
    else:
        status = provider_status(provider)
        if not status["ready"]:
            return False, status["note"]
    focus = _clean(focus, 200) or ""
    run_id, why = _create_run(provider, focus, by)
    if run_id is None:
        return False, why
    threading.Thread(target=_execute, args=(run_id, provider, focus, api_key), daemon=True).start()
    return True, "Search started. New finds go to the review queue before anyone sees them."


def run_sync(provider=None, focus=""):
    """Blocking run (used by update_cli.py / cron)."""
    provider = provider or default_provider()
    status = provider_status(provider)
    if not status["ready"]:
        return False, status["note"]
    run_id, why = _create_run(provider, _clean(focus, 200) or "")
    if run_id is None:
        return False, why
    state, _added, message = _execute(run_id, provider, _clean(focus, 200) or "")
    return state == "done", message
