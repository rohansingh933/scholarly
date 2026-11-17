"""Run the 'update scholarships' search from the command line or a cron job.

    python update_cli.py
    python update_cli.py --focus "scholarships for girls in engineering"
    python update_cli.py --provider mock

New finds go to the admin review queue (status 'pending'), never straight to the site.
"""
import argparse

import ai_updater
import db

parser = argparse.ArgumentParser()
parser.add_argument("--provider", choices=ai_updater.PROVIDERS)
parser.add_argument("--focus", default="")
args = parser.parse_args()

db.init_db()
ok, message = ai_updater.run_sync(args.provider, args.focus)
print(("OK: " if ok else "FAILED: ") + message)
raise SystemExit(0 if ok else 1)
