#!/usr/bin/env python3
"""Find what needs updating: missing next editions, TBA fields, and broken links.

Prints a Markdown checklist (used by the monthly GitHub Action to open/refresh an issue).
Exit code is 0 even when items are found; it's a report, not a test.

Usage:
    python scripts/check_updates.py
    python scripts/check_updates.py --links          # also HEAD-check every URL
    python scripts/check_updates.py --today 2027-03-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import urllib.error
import urllib.request

sys.path.insert(0, __import__("os").path.dirname(__file__))
from build import as_date, label, load  # noqa: E402

# How far ahead of an edition we start expecting its announcement on the official site.
LEAD_TIME_DAYS = {"conference": 400, "summer-school": 240}


def next_expected_year(s: dict, today: dt.date) -> int | None:
    years = [e["year"] for e in s["editions"]]
    last = max(years)
    freq = s["frequency"]
    if freq in ("annual", "multiple-per-year"):
        return last + 1
    if freq == "biennial-odd":
        return last + 2 if last % 2 else last + 1
    if freq == "biennial-even":
        return last + 2 if last % 2 == 0 else last + 1
    return None  # irregular


def typical_month(s: dict) -> int:
    starts = [as_date(e["start"]) for e in s["editions"] if e["start"]]
    return starts[-1].month if starts else 7


def missing_editions(series: list[dict], today: dt.date) -> list[str]:
    out = []
    for s in series:
        if s["status"] != "active":
            continue
        nxt = next_expected_year(s, today)
        if nxt is None:
            continue
        expected_start = dt.date(nxt, typical_month(s), 1)
        if (expected_start - today).days <= LEAD_TIME_DAYS[s["type"]]:
            out.append(
                f"- [ ] **{s['name']} {nxt}** — not in data yet (expected around {expected_start:%b %Y}). "
                f"Check [{s['homepage']}]({s['homepage']})"
            )
    return out


def tba_fields(series: list[dict], today: dt.date) -> list[str]:
    out = []
    for s in series:
        for e in s["editions"]:
            end = as_date(e["end"])
            if end and end < today:
                continue
            gaps = []
            if not e["location"] or "TBA" in str(e["location"]):
                gaps.append("location")
            if not e["start"]:
                gaps.append("dates")
            main = ["paper"] if s["type"] == "conference" else ["application", "registration"]
            dl = e["deadlines"] or {}
            if not any(dl.get(k) for k in main):
                gaps.append("main deadline")
            if e.get("notes") and "re-check" in e["notes"].lower():
                gaps.append("flagged for re-check")
            if gaps:
                out.append(f"- [ ] **{label(s, e)}** — {', '.join(gaps)}. Check [{e['url']}]({e['url']})")
    return out


def dormant(series: list[dict]) -> list[str]:
    return [
        f"- [ ] **{s['name']}** is marked dormant — any new edition? [{s['homepage']}]({s['homepage']})"
        for s in series
        if s["status"] == "dormant"
    ]


def broken_links(series: list[dict]) -> list[str]:
    urls = set()
    for s in series:
        urls.add(s["homepage"])
        for e in s["editions"]:
            urls.update([e["url"], e["verified_from"]])
    out = []
    for u in sorted(urls):
        req = urllib.request.Request(u, method="GET", headers={"User-Agent": "Mozilla/5.0 (awesome-cv-events link check)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status >= 400:
                    out.append(f"- [ ] {u} → HTTP {r.status}")
        except urllib.error.HTTPError as ex:
            if ex.code not in (401, 403, 405, 429):  # bot-blocking, not necessarily broken
                out.append(f"- [ ] {u} → HTTP {ex.code}")
        except Exception as ex:  # noqa: BLE001
            out.append(f"- [ ] {u} → {type(ex).__name__}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--links", action="store_true")
    args = ap.parse_args()

    series = load()
    sections = [
        ("🆕 Next editions to add", missing_editions(series, args.today)),
        ("❓ Announced editions with missing details", tba_fields(series, args.today)),
        ("💤 Dormant series to re-check", dormant(series)),
    ]
    if args.links:
        sections.append(("🔗 Possibly broken links", broken_links(series)))

    total = sum(len(items) for _, items in sections)
    print(f"Update check as of **{args.today:%d %b %Y}** — {total} item(s).\n")
    print(
        "For each item: open the official site, update `data/*.yaml` (use `null` for anything "
        "not yet published, and set `verified_from`), then run `python scripts/build.py`.\n"
    )
    for title, items in sections:
        print(f"### {title}\n")
        print("\n".join(items) if items else "_Nothing here._")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
