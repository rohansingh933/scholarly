# Scholarly

A scholarship finder for Indian college students (engineering, commerce, medical, arts, law and more).
Government and private scholarships live in one database. A student enters their course, category,
family income, marks and state, and the site hides what they can't get, marks the rest **Eligible** or
**Maybe eligible**, and sorts by the nearest deadline. Each scholarship lists the documents, essay and
other requirements.

## Run it on your computer

You need Python 3.10 or newer.

```bash
# 1. open a terminal in this folder, then create an isolated environment
python -m venv .venv

# 2. activate it
#    Windows:      .venv\Scripts\activate
#    Mac / Linux:  source .venv/bin/activate

# 3. install and start
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

The first start creates `data/scholarships.db` and `data/users.db` and loads 11 starter scholarships.
The terminal prints your **admin password** (also saved in `data/.admin_password`).
Set your own with the `ADMIN_PASSWORD` environment variable.

Run the tests any time with `python tests/test_portal.py`.

## Two databases

| File | What is in it |
|------|---------------|
| `data/scholarships.db` | every scholarship (course, level, year, age, gender, category, state, income cap, minimum marks, documents, essay, deadline, links, source) and the history of AI searches |
| `data/users.db` | student registrations (password stored as a salted hash), their profiles, and saved scholarships |

## The eligibility filter

For every scholarship the profile is checked rule by rule. If the student fails a rule, the scholarship
is hidden. If a rule applies but the student left that field blank, it stays visible as
**Maybe eligible** with "to confirm" notes. Income limits can differ by category (for example
ONGC: SC/ST up to ₹4,50,000, OBC and General up to ₹2,00,000), which the filter handles.

## Admin password

It is created once and saved in `data/.admin_password`, so it stays the same every time you start the
site. To choose your own, set `ADMIN_PASSWORD` before starting (Windows: `set ADMIN_PASSWORD=yourpassword`
then `py app.py`). On a public host you must set it as an environment variable, because free hosts
lose the data folder.

## "Update scholarships" (AI search)

**Who pays.** By default students search with the site's own key, within the daily limits in "Free AI for students" below. A student can instead use their own key from the **Find new** page; it is used for that one search and never saved, and it isn't counted against the limits. One search runs at a time, and each student has a 10-minute cool-down. Admins can also paste a key on the admin page.

Admin page (`/admin`) has a button that asks Gemini or OpenAI, with live web search, for scholarships
that are not in the database yet.

1. Set **one** key in your environment:
   - `GEMINI_API_KEY` (Google AI Studio), or
   - `OPENAI_API_KEY`
   Optional: `AI_PROVIDER=gemini|openai`, `GEMINI_MODEL`, `OPENAI_MODEL` (model names change over time).
   Use `AI_PROVIDER=mock` to try the whole flow offline with fake data.
2. Open `/admin`, optionally type a focus ("girls in engineering"), press **Search for new scholarships**.
3. New finds land in **Review**, never straight on the public site. Each one shows its source link.
   Open it, check the deadline and amount, then **Approve**, **Edit first**, or **Reject**.

Safety built in: records without a source link or with an already-passed deadline are dropped,
duplicates (including ones you rejected) are skipped, only one search runs at a time, and there is a
cool-down between runs. To run it on a schedule: `python update_cli.py` from cron or Task Scheduler.

## Essay help

Signed-in students can open **Essay help** (or press "Get help with this essay" on any scholarship that
needs one). They either paste a draft and get feedback with suggested changes, or choose "Help me start"
and get questions to answer plus a simple outline.

- It is a coach, not a writer. The instructions sent to the AI forbid writing the essay or full
  paragraphs, forbid inventing facts about the student, and tell it to keep the student's own voice.
- It uses the site's own key within the daily limits (see "Free AI for students"), or the student's own key if they prefer. Scholarly never saves the essay or an own key. The essay goes to the AI provider, and that provider's terms apply.
- "Remember this key on this device" (optional, off by default): keeps the key in the student's own
  browser storage so the form fills itself next time. It is never saved on the server, and a "Forget
  saved key" link removes it. Not for shared computers.
- Limits: about 2,000 words per request and a short cool-down between requests (`ESSAY_COOLDOWN_SECONDS`).
- Model: `gemini-2.5-flash` by default, retrying once with a newer model if the key can't use it.
  Change it with `ESSAY_GEMINI_MODEL` or `ESSAY_OPENAI_MODEL`.
- The quality of the feedback depends on the model and has not been tried with a real key yet.
  Read a few results yourself before you promote the feature.

## Free AI for students (the site's own key)

Essay help and "Find new" work **without students needing a key**. They use the key you set for the
site, so the cost and quota are yours. To switch it on, set `GEMINI_API_KEY` (or `OPENAI_API_KEY`)
before starting the site. Without one, students see "not switched on yet" and can still use their own key.

To protect your quota, every student gets a small daily allowance and there is a cap for everyone
combined. A student who uses their own key is not counted. Change the limits with these settings:

| Setting | Default | Meaning |
|---|---|---|
| `ESSAY_PER_USER_DAILY` | 5 | free essay reviews per student per day |
| `ESSAY_GLOBAL_DAILY` | 150 | free essay reviews for all students per day |
| `SEARCH_PER_USER_DAILY` | 1 | free web searches per student per day |
| `SEARCH_GLOBAL_DAILY` | 20 | free web searches for all students per day |

If the AI provider fails, the student's allowance is given back. The admin page shows today's usage.
Anyone can register, so the combined cap is your real protection: keep it below your provider's own
limits, which change over time. Anything the search finds still waits for your approval. Free and
paid plans can differ in how submitted text may be used, so read your provider's terms before inviting
many students.

## Put it online for free

The app is a normal Flask app (`Procfile` and `render.yaml` are included).

- **Render** (free web service): push this folder to GitHub, create a Blueprint from `render.yaml`,
  set `ADMIN_PASSWORD` (and your AI key). Free services have no permanent disk, so the SQLite files
  reset when the service restarts or redeploys. Fine for a demo, not for real student accounts.
- **PythonAnywhere** (free tier): keeps files between restarts, so data persists. Upload the folder,
  create a virtualenv, install `requirements.txt`, and point a Flask web app at `app.py` (`app`).
- For a real launch with many users, move the data to a hosted database (for example Postgres) first.

When public, also set `PRODUCTION=1` and `TRUST_PROXY=1`, and keep `ADMIN_PASSWORD` secret.
Free-plan terms change, so check each host's current limits.

## Files

```
app.py          routes, login, admin
matching.py     eligibility engine and deadline logic
ai_updater.py   AI search, cleaning, duplicate check, review queue
essay_coach.py  essay feedback and "help me start" (student's own key)
store.py        reading/writing scholarship rows
seed.py         starter scholarships (python seed.py --reset reloads them)
db.py           the two SQLite databases
update_cli.py   run the AI search from the command line
templates/ static/ tests/
```

## Important notes

- **Check the starter data.** The 11 seed scholarships were read from public web pages on 12 Nov 2026
  and some sources disagreed. Four are marked "Details unverified". Confirm each on its official page
  and fix it in `/admin` before you rely on it. Several 2026-27 windows (Reliance, Kotak Kanya) had
  already closed, so they are hidden unless "Also show closed" is ticked.
- Scholarship rules change every year. Update deadlines each cycle.
- Never ask students for money or sensitive documents on this site. It only points to official pages.
