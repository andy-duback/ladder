#!/usr/bin/env python3
"""Apply dashboard requests to holdings.csv.

The dashboard's buttons open pre-filled GitHub issues with titles like

    ladder: add AAPL 2024-03-15 shares=10 price=172.50
    ladder: done AAPL 2024-03-15 -20
    ladder: undo AAPL 2024-03-15 -20
    ladder: remove AAPL 2024-03-15

`manage.py apply` reads every open issue of that shape from someone with
write access to the repository, applies it to holdings.csv and remembers a
reply. `manage.py reply` posts the replies and closes the issues.
"""
import csv
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS = ROOT / "holdings.csv"
STRATEGY = ROOT / "strategy.json"
FIELDS = ["ticker", "purchase_date", "shares", "purchase_price", "done"]
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}

COMMAND = re.compile(r"^\s*ladder:\s*(add|remove|done|undo)\s+(\S+)(.*)$", re.I)
TICKER = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=]{0,14}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RUNG = re.compile(r"^[+-]?\d{1,3}$")
NUMBER = re.compile(r"^\d+(\.\d+)?$")


def fmt(x):
    return ("%.6f" % x).rstrip("0").rstrip(".")


def read_holdings(path=HOLDINGS):
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    rows = []
    for raw in csv.DictReader(io.StringIO("\n".join(lines))):
        row = {k: (raw.get(k) or "").strip() for k in FIELDS}
        row["ticker"] = row["ticker"].upper()
        if row["ticker"]:
            rows.append(row)
    return rows


def write_holdings(rows, path=HOLDINGS):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(out.getvalue())


def parse_done(text):
    return {int(tok) for tok in re.split(r"[;\s]+", text) if RUNG.match(tok)}


def format_done(values):
    return ";".join(("+%d" % v) if v > 0 else str(v) for v in sorted(values))


def describe(row):
    return row["ticker"] + (" bought " + row["purchase_date"] if row["purchase_date"] else "")


def apply_command(title, rows, rungs, today=None):
    """Apply one request to rows in place. Returns (changed, message)."""
    today = today or dt.date.today()
    m = COMMAND.match(title)
    if not m:
        return False, None
    verb, ticker, rest = m.group(1).lower(), m.group(2).upper(), m.group(3).split()
    if not TICKER.match(ticker):
        return False, "`%s` doesn't look like a ticker symbol." % ticker[:20]

    date, rung, options = "", None, {}
    for tok in rest:
        if DATE.match(tok):
            date = tok
        elif "=" in tok:
            key, _, value = tok.partition("=")
            options[key.lower()] = value
        elif RUNG.match(tok):
            rung = int(tok)
        else:
            return False, "I couldn't read `%s` in that request." % tok[:30]

    if date:
        try:
            parsed = dt.date.fromisoformat(date)
        except ValueError:
            return False, "`%s` isn't a real date. Use YYYY-MM-DD." % date
        if parsed > today + dt.timedelta(days=1):
            return False, "The purchase date %s is in the future." % date

    match = [r for r in rows if r["ticker"] == ticker and r["purchase_date"] == date]

    if verb == "add":
        for key in ("shares", "price"):
            if key in options and not NUMBER.match(options[key]):
                return False, "`%s=%s` should be a plain number." % (key, options[key][:20])
        if not date and "price" not in options:
            return False, "Add needs a purchase date, a price paid, or both."
        if match:
            return False, "%s is already on the dashboard." % describe(match[0])
        row = {"ticker": ticker, "purchase_date": date,
               "shares": options.get("shares", ""),
               "purchase_price": options.get("price", ""), "done": ""}
        rows.append(row)
        return True, "Added %s. Prices load on this run; reload the dashboard in a minute." % describe(row)

    if not match:
        return False, "I couldn't find %s%s in holdings.csv." % (ticker, " bought " + date if date else "")
    row = match[0]

    if verb == "remove":
        rows.remove(row)
        return True, "Removed %s." % describe(row)

    step = next((r for r in rungs if r["change"] == rung), None)
    if step is None or step["action"] == "hold":
        return False, "There's no buy or sell rule at %s%%." % ("—" if rung is None else "%+d" % rung)
    done = parse_done(row["done"])
    pct = step["percent"] / 100.0
    factor = (1 + pct) if step["action"] == "add" else (1 - pct)
    label = "%s %d%% at %+d%%" % (step["action"], step["percent"], rung)

    if verb == "done":
        if rung in done:
            return False, "%s was already marked done for %s." % (label.capitalize(), describe(row))
        done.add(rung)
        note = ""
        if row["shares"] and 0 < factor:
            old = float(row["shares"])
            row["shares"] = fmt(old * factor)
            note = " Share count changed from %s to %s." % (fmt(old), row["shares"])
        row["done"] = format_done(done)
        return True, "Marked %s done for %s.%s" % (label, describe(row), note)

    # undo
    if rung not in done:
        return False, "%s wasn't marked done for %s." % (label.capitalize(), describe(row))
    done.discard(rung)
    note = ""
    if row["shares"] and 0 < factor:
        old = float(row["shares"])
        row["shares"] = fmt(old / factor)
        note = " Share count changed from %s back to %s." % (fmt(old), row["shares"])
    row["done"] = format_done(done)
    return True, "Undid %s for %s.%s" % (label, describe(row), note)


def replies_path():
    return Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "ladder_replies.json"


def open_issues():
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return []
    out = subprocess.run(
        ["gh", "api", "repos/%s/issues?state=open&per_page=100" % repo],
        check=True, capture_output=True, text=True).stdout
    return [i for i in json.loads(out) if "pull_request" not in i]


def cmd_apply():
    rungs = json.loads(STRATEGY.read_text())["rungs"]
    rows = read_holdings()
    replies, changed_any = [], False
    for issue in sorted(open_issues(), key=lambda i: i["number"]):
        if issue.get("author_association") not in TRUSTED:
            continue
        changed, message = apply_command(issue.get("title", ""), rows, rungs)
        if message is None:
            continue  # not a dashboard request; leave the issue alone
        changed_any = changed_any or changed
        replies.append({"number": issue["number"], "message": message})
        print("#%d: %s" % (issue["number"], message))
    if changed_any:
        write_holdings(rows)
    replies_path().write_text(json.dumps(replies))


def cmd_reply():
    path = replies_path()
    if not path.exists():
        return
    for reply in json.loads(path.read_text()):
        number = str(reply["number"])
        subprocess.run(["gh", "issue", "comment", number, "--body", reply["message"]], check=False)
        subprocess.run(["gh", "issue", "close", number], check=False)


if __name__ == "__main__":
    {"apply": cmd_apply, "reply": cmd_reply}[sys.argv[1] if len(sys.argv) > 1 else "apply"]()
