"""Eligibility matching: the heart of the portal.

A student profile is compared with every active scholarship, criterion by
criterion. Each criterion ends up as one of:
    ok       - the student satisfies it
    bad      - the student fails it  -> scholarship is hidden
    unknown  - the scholarship has the restriction but the student left the
               field blank -> scholarship shown as "Maybe"
"""
import re
from datetime import date

COURSES = [
    ("engineering", "Engineering / Technology"),
    ("medical", "Medical / Nursing / Health"),
    ("pharmacy", "Pharmacy"),
    ("commerce", "Commerce / Accounting / Finance"),
    ("management", "Management (BBA / MBA)"),
    ("science", "Science (B.Sc / M.Sc)"),
    ("arts", "Arts / Humanities"),
    ("law", "Law"),
    ("architecture", "Architecture / Design"),
    ("agriculture", "Agriculture / Veterinary"),
    ("education", "Education"),
    ("other", "Other"),
]
LEVELS = [
    ("diploma", "Diploma"),
    ("ug", "Undergraduate (Bachelor's)"),
    ("pg", "Postgraduate (Master's)"),
    ("phd", "PhD / Research"),
]
CATEGORIES = [
    ("general", "General"),
    ("obc", "OBC"),
    ("sc", "SC"),
    ("st", "ST"),
    ("ews", "EWS"),
]
CATEGORY_LABELS = dict(CATEGORIES, minority="Minority community")
GENDERS = [("female", "Female"), ("male", "Male"), ("other", "Other / prefer not to say")]
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands",
    "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
COURSE_KEYS = [k for k, _ in COURSES]
LEVEL_KEYS = [k for k, _ in LEVELS]
CATEGORY_KEYS = [k for k, _ in CATEGORIES]
STATE_LOOKUP = {s.lower(): s for s in STATES}


# ---------------------------------------------------------------- helpers
def split_list(value):
    if value is None:
        return []
    return [x.strip().lower() for x in str(value).split(",") if x.strip()]


def is_all(items):
    return (not items) or "all" in items


def label(options, key):
    return dict(options).get(key, str(key).title())


def inr(value):
    """12345678 -> ₹1,23,45,678 (Indian digit grouping)."""
    if value is None:
        return ""
    n = int(value)
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


# ------------------------------------------------------------ profile in
def _int(value, lo=None, hi=None):
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if lo is not None and n < lo:
        return None
    if hi is not None and n > hi:
        return None
    return n


def parse_profile(src):
    """Build a clean profile dict from request.args / request.form / a DB row.

    Blank or invalid fields become None ("unknown")."""
    def choice(name, keys):
        v = str(src.get(name) or "").strip().lower()
        return v if v in keys else None

    def flag(name):
        return str(src.get(name) or "").strip().lower() in ("1", "on", "true", "yes")

    income_raw = re.sub(r"[^\d]", "", str(src.get("income") or src.get("family_income") or ""))
    pct = None
    try:
        raw = src.get("percentage")
        if raw not in (None, ""):
            pct = float(raw)
            if not 0 <= pct <= 100:
                pct = None
    except (TypeError, ValueError):
        pct = None

    state = STATE_LOOKUP.get(str(src.get("state") or "").strip().lower())
    return {
        "course": choice("course", COURSE_KEYS),
        "level": choice("level", LEVEL_KEYS),
        "year": _int(src.get("year") or src.get("year_of_study"), 1, 6),
        "age": _int(src.get("age"), 14, 60),
        "gender": choice("gender", [k for k, _ in GENDERS]),
        "category": choice("category", CATEGORY_KEYS),
        "state": state,
        "income": int(income_raw) if income_raw else None,
        "percentage": pct,
        "minority": flag("minority"),
        "disability": flag("disability"),
    }


def profile_active(p):
    """True if the student entered anything that can be used for matching."""
    if not p:
        return False
    return any(v not in (None, False) for v in p.values())


def parse_income_rules(text):
    """'sc:450000,obc:200000' -> {'sc': 450000, 'obc': 200000}"""
    rules = {}
    for part in str(text or "").split(","):
        if ":" in part:
            key, _, val = part.partition(":")
            key, val = key.strip().lower(), re.sub(r"[^\d]", "", val)
            if key and val:
                rules[key] = int(val)
    return rules


def _cap_text(rules, fallback):
    bits = [f"{CATEGORY_LABELS.get(k, k.upper())} ≤ {inr(v)}" for k, v in rules.items()]
    if fallback is not None:
        bits.append(f"others ≤ {inr(fallback)}" if rules else f"≤ {inr(fallback)}")
    return ", ".join(bits)


# --------------------------------------------------------------- matching
def evaluate(s, p):
    """Compare scholarship row `s` with profile `p`.

    Returns {"status": eligible|maybe|no, "ok": [...], "bad": [...], "unknown": [...]}"""
    ok, bad, unk = [], [], []

    def rule(known, matches, ok_t, bad_t, unk_t):
        if not known:
            unk.append(unk_t)
        elif matches:
            ok.append(ok_t)
        else:
            bad.append(bad_t)

    courses = split_list(s["courses"])
    if not is_all(courses):
        names = " / ".join(label(COURSES, c) for c in courses)
        rule(p["course"] is not None, p["course"] in courses,
             f"Open to your course ({label(COURSES, p['course'])})",
             f"Only for {names}", f"Only for {names} — add your course")

    levels = split_list(s["levels"])
    if not is_all(levels):
        names = " / ".join(label(LEVELS, c) for c in levels)
        rule(p["level"] is not None, p["level"] in levels,
             f"Open to {label(LEVELS, p['level'])} students",
             f"Only for {names}", f"Only for {names} — add your level")

    years = split_list(s["years"])
    if not is_all(years):
        names = ", ".join(years)
        rule(p["year"] is not None, str(p["year"]) in years,
             f"Open to year {p['year']} students",
             f"Only for year {names} students", f"Only for year {names} — add your year")

    lo, hi = s["min_age"], s["max_age"]
    if lo is not None or hi is not None:
        rng = (f"{lo}–{hi} years" if lo is not None and hi is not None
               else f"at least {lo} years" if lo is not None else f"up to {hi} years")
        fits = p["age"] is not None and (lo is None or p["age"] >= lo) and (hi is None or p["age"] <= hi)
        rule(p["age"] is not None, fits,
             f"Your age fits ({rng})", f"Age limit: {rng}", f"Age limit: {rng} — add your age")

    gender = (s["gender"] or "any").lower()
    if gender in ("female", "male"):
        g_label = "women" if gender == "female" else "men"
        if p["gender"] == "other":
            unk.append(f"Meant for {g_label} — check the scheme's rules")
        else:
            rule(p["gender"] is not None, p["gender"] == gender,
                 f"Open to {g_label}", f"Only for {g_label}", f"Only for {g_label} — add your gender")

    cats = split_list(s["categories"])
    if not is_all(cats):
        names = ", ".join(CATEGORY_LABELS.get(c, c.upper()) for c in cats)
        tags = set()
        if p["category"]:
            tags.add(p["category"])
        if p["minority"]:
            tags.add("minority")
        if tags & set(cats):
            ok.append(f"Your category qualifies ({names})")
        elif p["category"] is None and not p["minority"]:
            unk.append(f"Reserved for {names} — add your category")
        else:
            bad.append(f"Reserved for {names}")

    states = split_list(s["states"])
    if not is_all(states):
        names = ", ".join(x.title() for x in states)
        rule(p["state"] is not None, (p["state"] or "").lower() in states,
             f"Available in your state ({p['state']})", f"Only for residents of {names}",
             f"Only for residents of {names} — add your state")

    rules = parse_income_rules(s["income_rules"])
    fallback = s["max_income"]
    if rules or fallback is not None:
        if p["income"] is None:
            caps = list(rules.values()) + ([fallback] if fallback is not None else [])
            unk.append(f"Family income limit: {_cap_text(rules, fallback)} — add your income")
        else:
            tags = [t for t in (p["category"], "minority" if p["minority"] else None) if t]
            applicable = [rules[t] for t in tags if t in rules]
            if applicable:
                cap = max(applicable)
            elif tags or not rules:
                cap = fallback
            else:
                cap = None  # category unknown and caps differ by category
            if cap is not None or (tags and not applicable) or not rules:
                if cap is None or p["income"] <= cap:
                    ok.append("Family income is within the limit")
                else:
                    bad.append(f"Family income must be ≤ {inr(cap)}")
            else:
                every = list(rules.values()) + ([fallback] if fallback is not None else [])
                if p["income"] > max(every):
                    bad.append(f"Family income must be ≤ {inr(max(every))}")
                elif p["income"] > min(every):
                    unk.append(f"Income limit depends on category: {_cap_text(rules, fallback)} — add your category")
                else:
                    ok.append("Family income is within the limit")

    if s["min_percentage"] is not None:
        need = f"{s['min_percentage']:g}%"
        rule(p["percentage"] is not None,
             p["percentage"] is not None and p["percentage"] >= s["min_percentage"],
             f"Marks meet the {need} minimum", f"Needs at least {need} marks",
             f"Needs at least {need} marks — add your percentage")

    if s["disability_only"]:
        if p["disability"]:
            ok.append("Open to students with disability")
        else:
            bad.append("Only for students with disability (40%+)")

    if s["needs_check"]:
        # A condition we can't test from a profile: never claim a full match.
        unk.append(s["needs_check"])

    status = "no" if bad else ("maybe" if unk else "eligible")
    return {"status": status, "ok": ok, "bad": bad, "unknown": unk}


def deadline_info(s, today=None):
    today = today or date.today()
    d = parse_date(s["deadline"])
    if d is None:
        return {"date": None, "days": None, "state": "rolling",
                "text": s["deadline_note"] or "Check official site for dates"}
    days = (d - today).days
    if days < 0:
        state, text = "closed", f"Closed on {d.strftime('%d %b %Y')}"
    elif days == 0:
        state, text = "soon", "Closes today"
    elif days <= 14:
        state, text = "soon", f"Closes in {days} day{'s' if days != 1 else ''}"
    else:
        state, text = "open", f"Closes {d.strftime('%d %b %Y')} ({days} days left)"
    return {"date": d, "days": days, "state": state, "text": text}


def _deadline_sort_key(info):
    if info["state"] == "closed":
        return (2, -info["days"] if info["days"] is not None else 0)
    if info["state"] == "rolling":
        return (1, 0)
    return (0, info["days"])


def criteria(s):
    """Human-readable 'who can apply' lines for the detail and review pages."""
    def names(options, raw):
        items = split_list(raw)
        return None if is_all(items) else ", ".join(label(options, c) for c in items)

    out = [
        ("Courses", names(COURSES, s["courses"]) or "All courses"),
        ("Level", names(LEVELS, s["levels"]) or "All levels"),
    ]
    years = split_list(s["years"])
    out.append(("Year of study", "Any year" if is_all(years) else "Year " + ", ".join(years)))
    lo, hi = s["min_age"], s["max_age"]
    if lo is not None or hi is not None:
        out.append(("Age", f"{lo}–{hi} years" if lo is not None and hi is not None
                    else (f"At least {lo}" if lo is not None else f"Up to {hi}")))
    gender = (s["gender"] or "any").lower()
    out.append(("Gender", {"female": "Women only", "male": "Men only"}.get(gender, "Any")))
    cats = split_list(s["categories"])
    out.append(("Category", "Any category" if is_all(cats)
                else ", ".join(CATEGORY_LABELS.get(c, c.upper()) for c in cats)))
    states = split_list(s["states"])
    out.append(("State", "Any state" if is_all(states) else ", ".join(x.title() for x in states)))
    rules = parse_income_rules(s["income_rules"])
    if rules or s["max_income"] is not None:
        out.append(("Family income", _cap_text(rules, s["max_income"])))
    if s["min_percentage"] is not None:
        out.append(("Minimum marks", f"{s['min_percentage']:g}%"))
    if s["disability_only"]:
        out.append(("Disability", "Students with 40% or more disability"))
    return out


def fetch_active(sdb):
    return sdb.execute("SELECT * FROM scholarships WHERE status = 'active'").fetchall()


def search(rows, profile=None, q="", ptype="", include_closed=False, sort="best", today=None):
    """Filter + rank scholarships. Returns a list of dicts:
    {row, match (or None), deadline}"""
    today = today or date.today()
    use_profile = profile_active(profile)
    q = (q or "").strip().lower()
    terms = [t for t in re.split(r"\s+", q) if t]
    results = []
    for s in rows:
        if ptype in ("government", "private") and s["provider_type"] != ptype:
            continue
        if terms:
            hay = " ".join(str(s[k] or "") for k in
                           ("name", "provider", "keywords", "description", "courses")).lower()
            if not all(t in hay for t in terms):
                continue
        info = deadline_info(s, today)
        if info["state"] == "closed" and not include_closed:
            continue
        match = evaluate(s, profile) if use_profile else None
        if match and match["status"] == "no":
            continue
        results.append({"row": s, "match": match, "deadline": info})

    def best_key(r):
        status_rank = 0 if (r["match"] and r["match"]["status"] == "eligible") else 1
        if not r["match"]:
            status_rank = 0
        specific = -len(r["match"]["ok"]) if r["match"] else 0
        return (_deadline_sort_key(r["deadline"])[0] == 2, status_rank,
                _deadline_sort_key(r["deadline"]), specific)

    if sort == "amount":
        results.sort(key=lambda r: (-(r["row"]["amount_per_year"] or 0), _deadline_sort_key(r["deadline"])))
    elif sort == "name":
        results.sort(key=lambda r: r["row"]["name"].lower())
    elif sort == "deadline":
        results.sort(key=lambda r: _deadline_sort_key(r["deadline"]))
    else:
        results.sort(key=best_key)
    return results
