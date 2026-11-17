"""Scholarly - scholarship finder with an eligibility filter.

Run locally:   python app.py        ->  http://127.0.0.1:5000
"""
import os
import re
import secrets
import time
from datetime import date
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import ai_updater
import db
import essay_coach
import matching as m
import quota
import store
from seed import seed_if_empty

app = Flask(__name__)
db.init_db()
seed_if_empty()


def _persistent_secret(filename, make):
    path = os.path.join(db.DATA_DIR, filename)
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    value = make()
    with open(path, "w") as fh:
        fh.write(value)
    os.chmod(path, 0o600)
    return value


app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or _persistent_secret(".secret_key", lambda: secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("PRODUCTION") == "1",
    MAX_CONTENT_LENGTH=1_000_000,
)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or _persistent_secret(
    ".admin_password", lambda: secrets.token_urlsafe(9))
if os.environ.get("TRUST_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.teardown_appcontext(db.close_dbs)


# ------------------------------------------------------------ security bits
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def csrf_protect():
    if request.method == "POST":
        expected = session.get("_csrf")
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        if not expected or not sent or not secrets.compare_digest(sent, expected):
            abort(400, "Your session expired. Go back, refresh the page and try again.")
    csrf_token()  # every visitor gets a token, so forms on any page can post


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


_fails = {}


def throttled(key):
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < 900]
    return len(_fails[key]) >= 5


def record_fail(key):
    _fails.setdefault(key, []).append(time.time())


def safe_next(target, default):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


# -------------------------------------------------------------- current user
def current_user():
    if "user" not in g:
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = db.get_udb().execute("SELECT id, name, email FROM users WHERE id = ?", (uid,)).fetchone()
            if g.user is None:
                session.pop("uid", None)
    return g.user


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*a, **kw)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*a, **kw)
    return wrapper


def profile_from_db(uid):
    row = db.get_udb().execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
    return m.parse_profile(dict(row) if row else {})


def effective_profile():
    user = current_user()
    if user:
        return profile_from_db(user["id"])
    return m.parse_profile(session.get("profile") or {})


def saved_ids():
    user = current_user()
    if not user:
        return set()
    rows = db.get_udb().execute("SELECT scholarship_id FROM saved WHERE user_id = ?", (user["id"],)).fetchall()
    return {r["scholarship_id"] for r in rows}


@app.context_processor
def inject():
    return {
        "csrf_token": csrf_token, "current_user": current_user(), "is_admin": bool(session.get("admin")),
        "inr": m.inr, "COURSES": m.COURSES, "LEVELS": m.LEVELS, "CATEGORIES": m.CATEGORIES,
        "GENDERS": m.GENDERS, "STATES": m.STATES, "label": m.label, "split_list": m.split_list,
        "today": date.today(), "criteria": m.criteria,
        "YEARS": [(1, "1st year"), (2, "2nd year"), (3, "3rd year"), (4, "4th year"), (5, "5th year"), (6, "6th year")],
    }


@app.template_filter("lines")
def lines_filter(value):
    return [x.strip() for x in str(value or "").splitlines() if x.strip()]


@app.template_filter("nicedate")
def nicedate(value):
    d = m.parse_date(str(value or "")[:10])
    return d.strftime("%d %b %Y") if d else ""


# ------------------------------------------------------------- public pages
@app.route("/")
def index():
    rows = m.fetch_active(db.get_sdb())
    results = m.search(rows, None, sort="deadline")
    dated = [r for r in results if r["deadline"]["date"]]
    stats = {
        "total": len(results),
        "government": sum(1 for r in results if r["row"]["provider_type"] == "government"),
        "private": sum(1 for r in results if r["row"]["provider_type"] == "private"),
    }
    return render_template("index.html", closing=dated[:5], stats=stats, p=effective_profile())


@app.route("/scholarships")
def scholarships():
    args = request.args
    user = current_user()
    submitted = args.get("f") == "1"
    if args.get("profile") == "1" and user:
        profile = profile_from_db(user["id"])
    elif submitted:
        profile = m.parse_profile(args)
        if m.profile_active(profile):
            session["profile"] = profile
        else:
            session.pop("profile", None)
    else:
        profile = effective_profile()

    q = (args.get("q") or "").strip()[:100]
    ptype = args.get("type") if args.get("type") in ("government", "private") else ""
    include_closed = args.get("include_closed") == "1"
    sort = args.get("sort") if args.get("sort") in ("best", "deadline", "amount", "name") else "best"

    rows = m.fetch_active(db.get_sdb())
    results = m.search(rows, profile, q=q, ptype=ptype, include_closed=include_closed, sort=sort)
    use_profile = m.profile_active(profile)
    counts = {
        "eligible": sum(1 for r in results if r["match"] and r["match"]["status"] == "eligible"),
        "maybe": sum(1 for r in results if r["match"] and r["match"]["status"] == "maybe"),
    }
    return render_template(
        "scholarships.html", results=results, p=profile, use_profile=use_profile, counts=counts,
        q=q, ptype=ptype, include_closed=include_closed, sort=sort, saved=saved_ids(),
        total_active=len(rows), from_account=bool(user and not submitted))


@app.route("/scholarship/<int:sid>")
def detail(sid):
    s = db.get_sdb().execute("SELECT * FROM scholarships WHERE id = ?", (sid,)).fetchone()
    if s is None or (s["status"] != "active" and not session.get("admin")):
        abort(404)
    profile = effective_profile()
    match = m.evaluate(s, profile) if m.profile_active(profile) else None
    return render_template("detail.html", s=s, match=match, dl=m.deadline_info(s), p=profile,
                           saved=sid in saved_ids(), crit=m.criteria(s))


# ------------------------------------------------------------ registration
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("profile"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        email = request.form.get("email", "").strip().lower()[:200]
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        error = None
        if not name:
            error = "Enter your name."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif len(pw) < 8:
            error = "Use a password with at least 8 characters."
        elif pw != pw2:
            error = "The two passwords don't match."
        if not error:
            udb = db.get_udb()
            if udb.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                error = "An account with this email already exists. Log in instead."
            else:
                cur = udb.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                                  (name, email, generate_password_hash(pw, method="pbkdf2:sha256:600000")))
                uid = cur.lastrowid
                # keep whatever the visitor already filled in on the filter
                _save_profile(udb, uid, m.parse_profile(session.get("profile") or {}))
                udb.commit()
                session.clear()
                session["uid"] = uid
                flash("Account created. Check your details below so matches are accurate.", "ok")
                return redirect(url_for("profile"))
        flash(error, "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("profile"))
    nxt = request.args.get("next") or request.form.get("next") or ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        key = f"{request.remote_addr}:{email}"
        if throttled(key):
            flash("Too many failed attempts. Wait 15 minutes and try again.", "error")
        else:
            row = db.get_udb().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                prof = session.get("profile")
                session.clear()
                session["uid"] = row["id"]
                if prof and not db.get_udb().execute("SELECT 1 FROM profiles WHERE user_id = ?", (row["id"],)).fetchone():
                    _save_profile(db.get_udb(), row["id"], m.parse_profile(prof))
                    db.get_udb().commit()
                return redirect(safe_next(nxt, url_for("scholarships", profile=1)))
            record_fail(key)
            flash("Wrong email or password.", "error")
    return render_template("login.html", next=nxt)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


def _save_profile(udb, uid, p):
    udb.execute(
        """INSERT INTO profiles (user_id, age, gender, course, level, year_of_study, percentage,
                                 category, minority, disability, family_income, state, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             age=excluded.age, gender=excluded.gender, course=excluded.course, level=excluded.level,
             year_of_study=excluded.year_of_study, percentage=excluded.percentage,
             category=excluded.category, minority=excluded.minority, disability=excluded.disability,
             family_income=excluded.family_income, state=excluded.state, updated_at=excluded.updated_at""",
        (uid, p["age"], p["gender"], p["course"], p["level"], p["year"], p["percentage"], p["category"],
         int(p["minority"]), int(p["disability"]), p["income"], p["state"]))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    udb = db.get_udb()
    if request.method == "POST":
        _save_profile(udb, user["id"], m.parse_profile(request.form))
        udb.commit()
        flash("Profile saved.", "ok")
        return redirect(url_for("profile"))
    p = profile_from_db(user["id"])
    top = []
    if m.profile_active(p):
        top = m.search(m.fetch_active(db.get_sdb()), p, sort="best")[:5]
    return render_template("profile.html", p=p, top=top, saved=saved_ids())


@app.route("/saved")
@login_required
def saved_page():
    ids = saved_ids()
    rows = [r for r in m.fetch_active(db.get_sdb()) if r["id"] in ids]
    p = effective_profile()
    results = m.search(rows, p, include_closed=True, sort="deadline")
    return render_template("saved.html", results=results, use_profile=m.profile_active(p), saved=ids)


@app.route("/save/<int:sid>", methods=["POST"])
@login_required
def toggle_save(sid):
    user = current_user()
    udb = db.get_udb()
    if db.get_sdb().execute("SELECT 1 FROM scholarships WHERE id = ? AND status = 'active'", (sid,)).fetchone() is None:
        abort(404)
    if udb.execute("SELECT 1 FROM saved WHERE user_id = ? AND scholarship_id = ?", (user["id"], sid)).fetchone():
        udb.execute("DELETE FROM saved WHERE user_id = ? AND scholarship_id = ?", (user["id"], sid))
    else:
        udb.execute("INSERT INTO saved (user_id, scholarship_id) VALUES (?, ?)", (user["id"], sid))
    udb.commit()
    return redirect(safe_next(request.form.get("next"), url_for("detail", sid=sid)))


@app.route("/find-new", methods=["GET", "POST"])
@login_required
def find_new():
    """A signed-in student runs the web search with THEIR OWN API key.
    The key is used for this one search only and is never stored. Anything found waits for admin approval."""
    user = current_user()
    by = f"user:{user['id']}"
    udb = db.get_udb()
    if request.method == "POST":
        own_key = ai_updater.clean_key(request.form.get("api_key"))
        focus = request.form.get("focus", "")
        if own_key:                       # their own key: not counted against the site's allowance
            ok, message = ai_updater.start_update(request.form.get("provider"), focus, api_key=own_key, by=by)
            flash(message, "ok" if ok else "error")
            return redirect(url_for("find_new"))
        provider = ai_updater.default_provider()
        if not ai_updater.provider_status(provider)["ready"]:
            flash("Free searching isn't switched on right now. Open “Use my own key instead” to search.", "error")
        else:
            try:
                usage_id = quota.take(udb, user["id"], "search")
            except quota.QuotaError as exc:
                flash(str(exc), "error")
            else:
                ok, message = ai_updater.start_update(provider, focus, api_key=None, by=by)
                if not ok:
                    quota.release(udb, usage_id)     # didn't start, so it doesn't use up the allowance
                flash(message, "ok" if ok else "error")
                return redirect(url_for("find_new"))
    last = db.get_sdb().execute(
        "SELECT status, found, added, message, finished_at FROM update_runs WHERE triggered_by = ? "
        "ORDER BY id DESC LIMIT 1", (by,)).fetchone()
    left = quota.remaining(udb, user["id"], "search")
    free_ok = ai_updater.provider_status(ai_updater.default_provider())["ready"] \
        and left["user_left"] > 0 and left["global_left"] > 0
    return render_template("find_new.html", last=last, running=bool(last and last["status"] == "running"),
                           left=left, free_ok=free_ok)


@app.route("/essay-coach", methods=["GET", "POST"])
@login_required
def essay_coach_page():
    """Feedback on a scholarship essay, using the student's own API key (never stored).
    Nothing the student pastes is saved: it goes to their AI provider and is shown back once."""
    user = current_user()
    sid = request.values.get("s", type=int)
    sch = None
    if sid:
        sch = db.get_sdb().execute(
            "SELECT id, name, essay_details FROM scholarships WHERE id = ? AND status = 'active'", (sid,)).fetchone()
    form = {"provider": "gemini", "mode": "draft", "limit": "", "draft": "",
            "question": (sch["essay_details"] or "") if sch else ""}
    result = None
    if request.method == "POST":
        form.update(
            provider=request.form.get("provider", "gemini"),
            mode=request.form.get("mode", "draft"),
            limit=request.form.get("limit", "")[:10],
            question=request.form.get("question", "")[:essay_coach.MAX_PROMPT_CHARS + 1],
            draft=request.form.get("draft", "")[:essay_coach.MAX_ESSAY_CHARS + 1])
        try:
            result = essay_coach.run(form["provider"], request.form.get("api_key"), form["mode"],
                                     form["question"], form["draft"], form["limit"],
                                     sch["name"] if sch else "", user["id"], db.get_udb())
        except essay_coach.CoachError as exc:
            flash(str(exc), "error")
    left = quota.remaining(db.get_udb(), user["id"], "essay")
    server_provider = ai_updater.essay_provider()
    free_ok = bool(server_provider) and left["user_left"] > 0 and left["global_left"] > 0
    return render_template("essay_coach.html", form=form, sch=sch, result=result,
                           words=essay_coach.word_count(form["draft"]), left=left,
                           server_provider=server_provider, free_ok=free_ok)


@app.route("/find-new/status")
@login_required
def find_new_status():
    last = db.get_sdb().execute("SELECT status FROM update_runs WHERE triggered_by = ? ORDER BY id DESC LIMIT 1",
                                (f"user:{current_user()['id']}",)).fetchone()
    return jsonify({"status": last["status"] if last else "none"})


@app.route("/healthz")
def healthz():
    return "ok"


# -------------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        key = f"admin:{request.remote_addr}"
        if throttled(key):
            flash("Too many failed attempts. Wait 15 minutes.", "error")
        elif secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(safe_next(request.args.get("next"), url_for("admin")))
        else:
            record_fail(key)
            flash("Wrong admin password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    sdb = db.get_sdb()
    status_filter = request.args.get("status") if request.args.get("status") in ("active", "pending", "rejected") else ""
    sql = "SELECT * FROM scholarships" + (" WHERE status = ?" if status_filter else "") + " ORDER BY id DESC"
    rows = sdb.execute(sql, (status_filter,) if status_filter else ()).fetchall()
    counts = {r["status"]: r["n"] for r in sdb.execute("SELECT status, COUNT(*) AS n FROM scholarships GROUP BY status")}
    runs = sdb.execute("SELECT * FROM update_runs ORDER BY id DESC LIMIT 8").fetchall()
    users = db.get_udb().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    prov = ai_updater.default_provider()
    return render_template("admin.html", rows=rows, counts=counts, runs=runs, users=users,
                           provider=ai_updater.provider_status(prov), status_filter=status_filter,
                           running=any(r["status"] == "running" for r in runs),
                           usage=quota.today_totals(db.get_udb()), essay_limits=quota.limits("essay"),
                           search_limits=quota.limits("search"))


@app.route("/admin/update", methods=["POST"])
@admin_required
def admin_update():
    provider = request.form.get("provider")
    provider = provider if provider in ("gemini", "openai") else ai_updater.default_provider()
    ok, message = ai_updater.start_update(provider, request.form.get("focus", ""),
                                          api_key=request.form.get("api_key"), by="admin")
    flash(message, "ok" if ok else "error")
    return redirect(url_for("admin"))


@app.route("/admin/update/status")
@admin_required
def admin_update_status():
    run = db.get_sdb().execute("SELECT * FROM update_runs ORDER BY id DESC LIMIT 1").fetchone()
    return jsonify(dict(run) if run else {"status": "none"})


@app.route("/admin/review")
@admin_required
def admin_review():
    rows = db.get_sdb().execute("SELECT * FROM scholarships WHERE status = 'pending' ORDER BY id").fetchall()
    return render_template("admin_review.html", rows=[{"s": r, "dl": m.deadline_info(r)} for r in rows])


@app.route("/admin/scholarship/<int:sid>/status", methods=["POST"])
@admin_required
def admin_set_status(sid):
    new = request.form.get("status")
    if new not in ("active", "pending", "rejected"):
        abort(400)
    sdb = db.get_sdb()
    sdb.execute("UPDATE scholarships SET status = ?, verified_on = CASE WHEN ? = 'active' THEN date('now') "
                "ELSE verified_on END WHERE id = ?", (new, new, sid))
    sdb.commit()
    flash({"active": "Approved and published.", "rejected": "Rejected.", "pending": "Moved back to review."}[new], "ok")
    return redirect(safe_next(request.form.get("next"), url_for("admin_review")))


@app.route("/admin/scholarship/<int:sid>/delete", methods=["POST"])
@admin_required
def admin_delete(sid):
    sdb = db.get_sdb()
    sdb.execute("DELETE FROM scholarships WHERE id = ?", (sid,))
    sdb.commit()
    flash("Scholarship deleted.", "ok")
    return redirect(url_for("admin"))


def _url_or_none(v):
    v = (v or "").strip()
    p = urlparse(v)
    return v if p.scheme in ("http", "https") and p.netloc else None


def _int_or_none(v):
    v = re.sub(r"[^\d]", "", str(v or ""))
    return int(v) if v else None


def rec_from_form(f):
    """Turn the admin edit form into a record; returns (rec, errors)."""
    errors = []

    def pick(name):
        return f.getlist(name) or ["all"]

    states = []
    for part in re.split(r"[,\n]", f.get("states", "")):
        part = part.strip().lower()
        if part:
            if part in m.STATE_LOOKUP:
                states.append(part)
            else:
                errors.append(f"Unknown state: {part}")
    deadline = f.get("deadline", "").strip()
    if deadline and not m.parse_date(deadline):
        errors.append("Deadline must be a valid date.")
        deadline = ""
    pct = None
    if f.get("min_percentage", "").strip():
        try:
            pct = float(f["min_percentage"])
        except ValueError:
            errors.append("Minimum percentage must be a number.")
    rules = f.get("income_rules", "").strip()
    if rules and not m.parse_income_rules(rules):
        errors.append("Income rules look like: sc:450000,obc:200000")
    rec = {
        "name": f.get("name", "").strip()[:200], "provider": f.get("provider", "").strip()[:200],
        "provider_type": f.get("provider_type") if f.get("provider_type") in ("government", "private") else "private",
        "description": f.get("description", "").strip()[:2000], "amount_text": f.get("amount_text", "").strip()[:200],
        "amount_per_year": _int_or_none(f.get("amount_per_year")),
        "courses": pick("courses"), "levels": pick("levels"), "years": pick("years"),
        "min_age": _int_or_none(f.get("min_age")), "max_age": _int_or_none(f.get("max_age")),
        "gender": f.get("gender") if f.get("gender") in ("female", "male") else "any",
        "categories": pick("categories"), "states": states or ["all"],
        "max_income": _int_or_none(f.get("max_income")), "income_rules": rules or None,
        "min_percentage": pct, "disability_only": f.get("disability_only") == "1",
        "needs_check": f.get("needs_check", "").strip()[:250] or None,
        "keywords": f.get("keywords", ""), "documents": f.get("documents", ""),
        "essay_required": f.get("essay_required") == "1", "essay_details": f.get("essay_details", "").strip()[:400],
        "other_requirements": f.get("other_requirements", ""),
        "selection_process": f.get("selection_process", "").strip()[:400],
        "deadline": deadline or None, "deadline_note": f.get("deadline_note", "").strip()[:200],
        "apply_url": _url_or_none(f.get("apply_url")), "source_url": _url_or_none(f.get("source_url")),
        "status": f.get("status") if f.get("status") in ("active", "pending", "rejected") else "active",
    }
    if not rec["name"] or not rec["provider"]:
        errors.append("Name and provider are required.")
    if f.get("apply_url", "").strip() and not rec["apply_url"]:
        errors.append("Apply link must start with http:// or https://")
    return rec, errors


MULTI_FIELDS = ("courses", "levels", "years", "categories")


def _form_data(existing=None, form=None):
    """Values for the admin edit form (an empty list for a checkbox group means 'no restriction')."""
    if form is not None:
        d = form.to_dict()
        for k in MULTI_FIELDS:
            d[k] = form.getlist(k)
        d["disability_only"] = form.get("disability_only") == "1"
        d["essay_required"] = form.get("essay_required") == "1"
        return d
    if existing is None:
        return {k: [] for k in MULTI_FIELDS} | {"status": "active", "provider_type": "private", "gender": "any", "states": ""}
    d = dict(existing)
    for k in MULTI_FIELDS:
        items = m.split_list(d[k])
        d[k] = [] if m.is_all(items) else items
    states = m.split_list(d["states"])
    d["states"] = "" if m.is_all(states) else ", ".join(x.title() for x in states)
    return d


@app.route("/admin/scholarship/new", methods=["GET", "POST"])
@app.route("/admin/scholarship/<int:sid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit(sid=None):
    sdb = db.get_sdb()
    existing = None
    if sid is not None:
        existing = sdb.execute("SELECT * FROM scholarships WHERE id = ?", (sid,)).fetchone()
        if existing is None:
            abort(404)
    if request.method == "POST":
        rec, errors = rec_from_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("admin_edit.html", d=_form_data(form=request.form), sid=sid)
        if sid is None:
            rec.update(source="manual", verified_on=date.today().isoformat())
            sid = store.insert_scholarship(sdb, rec)
        else:
            rec.update(source=existing["source"], source_url=rec["source_url"] or existing["source_url"],
                       verified_on=existing["verified_on"])
            store.update_scholarship(sdb, sid, rec)
        sdb.commit()
        flash("Saved.", "ok")
        return redirect(url_for("admin"))
    return render_template("admin_edit.html", d=_form_data(existing), sid=sid)


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="We couldn't find that page."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message=getattr(e, "description", "Bad request.")), 400


if __name__ == "__main__":
    print("Admin password:", ADMIN_PASSWORD)
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
