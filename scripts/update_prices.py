#!/usr/bin/env python3
"""Fetch daily closing prices for every ticker in holdings.csv and write
data/prices.json, which the dashboard reads.

For each ticker it records the latest close, and for each purchase date the
close on that day (or the last trading day before it) plus the lowest and
highest close since. "close" is split-adjusted; "adj" also folds in
dividends and fund distributions, for the dashboard's total-return view.
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manage import read_holdings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices.json"


def fetch(symbol, start):
    """Return (rows, meta). rows is a list of (date, close, adj) oldest first."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    frame = ticker.history(start=start.isoformat(), interval="1d",
                           auto_adjust=False, actions=False)
    rows = []
    if frame is not None and len(frame):
        has_adj = "Adj Close" in frame.columns
        for stamp, rec in frame.iterrows():
            close = rec["Close"]
            if close != close or close <= 0:  # NaN or junk
                continue
            adj = rec["Adj Close"] if has_adj else close
            if adj != adj or adj <= 0:
                adj = close
            rows.append((stamp.strftime("%Y-%m-%d"), float(close), float(adj)))
    meta = {}
    try:
        meta = ticker.get_history_metadata() or {}
    except Exception:
        pass
    return rows, meta


def fetch_with_retry(symbol, start, tries=3):
    candidates = [symbol]
    if "." in symbol:
        candidates.append(symbol.replace(".", "-"))  # BRK.B is BRK-B at the source
    last_error = "No price data found. Check the ticker symbol."
    for candidate in candidates:
        for attempt in range(tries):
            try:
                rows, meta = fetch(candidate, start)
                if rows:
                    return rows, meta
                break  # empty answer: try the next spelling, don't hammer
            except Exception as exc:  # network trouble, rate limits
                last_error = "Price lookup failed: %s" % str(exc)[:160]
                time.sleep(5 * (attempt + 1))
    raise LookupError(last_error)


def summarize(rows, dates):
    """Build the per-ticker record from price rows and the purchase dates."""
    r4 = lambda x: round(x, 4)
    last = rows[-1]
    record = {"last": {"date": last[0], "close": r4(last[1]), "adj": r4(last[2])},
              "from": {}}
    for date in sorted(dates):
        on_or_before = [r for r in rows if r[0] <= date]
        if on_or_before:
            entry = on_or_before[-1]
        else:
            first = dt.date.fromisoformat(rows[0][0])
            if (first - dt.date.fromisoformat(date)).days > 10:
                record["from"][date] = {
                    "error": "Price history only goes back to %s." % rows[0][0]}
                continue
            entry = rows[0]
        since = [r for r in rows if r[0] >= entry[0]]
        record["from"][date] = {
            "date": entry[0], "close": r4(entry[1]), "adj": r4(entry[2]),
            "lowClose": r4(min(r[1] for r in since)),
            "highClose": r4(max(r[1] for r in since)),
            "lowAdj": r4(min(r[2] for r in since)),
            "highAdj": r4(max(r[2] for r in since)),
        }
    return record


def main():
    holdings = read_holdings()
    wanted = {}
    for row in holdings:
        wanted.setdefault(row["ticker"], set())
        if row["purchase_date"]:
            wanted[row["ticker"]].add(row["purchase_date"])

    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text()).get("tickers", {})
        except ValueError:
            pass

    today = dt.date.today()
    tickers, failures = {}, 0
    for symbol in sorted(wanted):
        dates = wanted[symbol]
        earliest = min([dt.date.fromisoformat(d) for d in dates] + [today])
        start = earliest - dt.timedelta(days=12)
        try:
            rows, meta = fetch_with_retry(symbol, start)
            record = summarize(rows, dates)
            record["name"] = meta.get("longName") or meta.get("shortName") or ""
            record["currency"] = meta.get("currency") or "USD"
            print("%s: %s close %.2f" % (symbol, record["last"]["date"], record["last"]["close"]))
        except Exception as exc:
            failures += 1
            record = dict(previous.get(symbol, {}))  # keep the last good prices
            record["error"] = str(exc)
            print("%s: FAILED - %s" % (symbol, exc))
        tickers[symbol] = record
        time.sleep(0.5)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": os.environ.get("GITHUB_REPOSITORY"),
        "tickers": tickers,
    }, indent=1) + "\n")

    if wanted and failures == len(wanted):
        sys.exit("Every price lookup failed; the dashboard is showing old prices.")


if __name__ == "__main__":
    main()
