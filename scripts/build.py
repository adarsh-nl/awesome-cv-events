#!/usr/bin/env python3
"""Validate data/*.yaml and regenerate the README tables and calendar.ics.

Usage:
    python scripts/build.py            # validate + write README.md and calendar.ics
    python scripts/build.py --check    # validate only; exit 1 if generated files are stale
    python scripts/build.py --today 2027-01-01   # render as of another date (testing)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_FILES = [ROOT / "data" / "conferences.yaml", ROOT / "data" / "summer-schools.yaml"]
README = ROOT / "README.md"
ICS = ROOT / "calendar.ics"

BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

TYPES = {"conference", "summer-school"}
AREAS = {"computer-vision", "machine-learning", "artificial-intelligence"}
FREQS = {"annual", "biennial-odd", "biennial-even", "multiple-per-year", "irregular"}
STATUSES = {"active", "dormant"}
SERIES_KEYS = {"id", "name", "full_name", "type", "area", "frequency", "status", "homepage", "editions"}
EDITION_REQ = {"year", "url", "location", "start", "end", "deadlines", "verified_from"}
EDITION_OPT = {"title", "timezone", "notes"}
AREA_BADGE = {"computer-vision": "CV", "machine-learning": "ML", "artificial-intelligence": "AI"}
DEADLINE_LABEL = {
    "abstract": "Abstract",
    "paper": "Paper",
    "notification": "Notification",
    "application": "Application",
    "registration": "Registration",
    "round2_abstract": "Abstract (round 2)",
    "round2_paper": "Paper (round 2)",
    "round2_notification": "Notification (round 2)",
}


# ----------------------------------------------------------------------------- loading


def load() -> list[dict]:
    series: list[dict] = []
    for f in DATA_FILES:
        items = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        for s in items:
            s["_file"] = f.name
        series.extend(items)
    return series


def as_date(v):
    if v is None or isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def validate(series: list[dict]) -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for s in series:
        where = f"{s.get('_file')}:{s.get('id', '?')}"
        missing = SERIES_KEYS - s.keys()
        if missing:
            errs.append(f"{where}: missing keys {sorted(missing)}")
            continue
        if s["id"] in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(s["id"])
        if s["type"] not in TYPES:
            errs.append(f"{where}: bad type {s['type']!r}")
        if s["frequency"] not in FREQS:
            errs.append(f"{where}: bad frequency {s['frequency']!r}")
        if s["status"] not in STATUSES:
            errs.append(f"{where}: bad status {s['status']!r}")
        for a in s["area"]:
            if a not in AREAS:
                errs.append(f"{where}: bad area {a!r}")
        if not s["editions"]:
            errs.append(f"{where}: no editions")
        for e in s["editions"]:
            ew = f"{where}/{e.get('year')}{'/' + e['title'] if e.get('title') else ''}"
            if EDITION_REQ - e.keys():
                errs.append(f"{ew}: missing {sorted(EDITION_REQ - e.keys())}")
                continue
            extra = e.keys() - EDITION_REQ - EDITION_OPT
            if extra:
                errs.append(f"{ew}: unknown keys {sorted(extra)}")
            try:
                start, end = as_date(e["start"]), as_date(e["end"])
                if start and end and end < start:
                    errs.append(f"{ew}: end before start")
                if start and start.year != e["year"]:
                    errs.append(f"{ew}: start year {start.year} != edition year {e['year']}")
                for k, v in (e["deadlines"] or {}).items():
                    if k not in DEADLINE_LABEL:
                        errs.append(f"{ew}: unknown deadline {k!r}")
                    d = as_date(v)
                    if d and start and d > start:
                        errs.append(f"{ew}: deadline {k} {d} is after the event starts")
            except ValueError as ex:
                errs.append(f"{ew}: bad date ({ex})")
            if not str(e["verified_from"]).startswith("http"):
                errs.append(f"{ew}: verified_from must be a URL")
    return errs


# ----------------------------------------------------------------------------- helpers


def fmt_range(start, end) -> str:
    start, end = as_date(start), as_date(end)
    if not start:
        return "TBA"
    if not end or end == start:
        return start.strftime("%d %b %Y")
    if start.year != end.year:
        return f"{start:%d %b %Y} – {end:%d %b %Y}"
    if start.month != end.month:
        return f"{start:%d %b} – {end:%d %b %Y}"
    return f"{start:%d}–{end:%d %b %Y}"


def fmt_date(v) -> str:
    d = as_date(v)
    return d.strftime("%d %b %Y") if d else "TBA"


def label(s: dict, e: dict) -> str:
    if e.get("title"):
        return e["title"] if str(e["year"]) in e["title"] else f"{e['title']} {e['year']}"
    return f"{s['name']} {e['year']}"


def is_current(e: dict, today: dt.date) -> bool:
    """Edition still ahead of us (or running now), or announced without dates."""
    end, start = as_date(e["end"]), as_date(e["start"])
    if end:
        return end >= today
    if start:
        return start >= today
    return e["year"] >= today.year


def key_deadline(s: dict, e: dict):
    d = e["deadlines"] or {}
    keys = ["paper", "abstract"] if s["type"] == "conference" else ["application", "registration"]
    for k in keys:
        if k in d:
            return d[k]
    return None


def deadline_cell(s: dict, e: dict, today: dt.date) -> str:
    v = as_date(key_deadline(s, e))
    if not v:
        return "TBA"
    txt = fmt_date(v)
    tz = f" {e['timezone']}" if e.get("timezone") else ""
    return f"~~{txt}~~" if v < today else f"**{txt}**{tz}"


# ----------------------------------------------------------------------------- README


def table(series: list[dict], typ: str, today: dt.date) -> str:
    head = "Paper deadline" if typ == "conference" else "Application"
    rows = [f"| Event | Area | Dates | Location | {head} | Links |", "|---|---|---|---|---|---|"]
    picked = []
    for s in series:
        if s["type"] != typ or s["status"] != "active":
            continue
        eds = sorted(s["editions"], key=lambda e: (e["year"], str(e["start"])))
        current = [e for e in eds if is_current(e, today)]
        latest = [e for e in eds if e["year"] == eds[-1]["year"]]
        for e in current or latest:
            picked.append((s, e, bool(current)))
    picked.sort(key=lambda t: (str(as_date(t[1]["start"]) or f"{t[1]['year']}-12-31"), t[0]["name"]))
    for s, e, upcoming in picked:
        area = " ".join(f"`{AREA_BADGE[a]}`" for a in s["area"])
        name = f"[**{label(s, e)}**]({e['url']})"
        if not upcoming:
            name += " <sub>(next TBA)</sub>"
        if e.get("notes"):
            name += f"<br><sub>{e['notes']}</sub>"
        links = f"[home]({s['homepage']}) · [source]({e['verified_from']})"
        rows.append(
            f"| {name} | {area} | {fmt_range(e['start'], e['end'])} | {e['location'] or 'TBA'} "
            f"| {deadline_cell(s, e, today)} | {links} |"
        )
    return "\n".join(rows)


def upcoming_deadlines(series: list[dict], today: dt.date) -> str:
    items = []
    for s in series:
        for e in s["editions"]:
            for k, v in (e["deadlines"] or {}).items():
                d = as_date(v)
                if d and d >= today:
                    items.append((d, s, e, k))
    if not items:
        return "_No announced deadlines ahead — check back soon._"
    items.sort(key=lambda t: (t[0], t[1]["name"]))
    rows = ["| Date | Event | Deadline | Timezone |", "|---|---|---|---|"]
    for d, s, e, k in items:
        rows.append(f"| {d:%a %d %b %Y} | [{label(s, e)}]({e['url']}) | {DEADLINE_LABEL[k]} | {e.get('timezone') or '—'} |")
    return "\n".join(rows)


def archive(series: list[dict], today: dt.date) -> str:
    rows = ["| Event | Dates | Location |", "|---|---|---|"]
    past = []
    for s in series:
        for e in s["editions"]:
            if not is_current(e, today):
                past.append((s, e))
    past.sort(key=lambda t: str(as_date(t[1]["start"])), reverse=True)
    for s, e in past:
        rows.append(f"| [{label(s, e)}]({e['url']}) | {fmt_range(e['start'], e['end'])} | {e['location'] or '—'} |")
    dormant = [s for s in series if s["status"] == "dormant"]
    out = "\n".join(rows)
    if dormant:
        out += "\n\n**Dormant series** (no edition currently announced): " + ", ".join(
            f"[{s['name']}]({s['homepage']})" for s in dormant
        )
    return out


def render(series: list[dict], today: dt.date) -> str:
    return "\n\n".join(
        [
            BEGIN,
            f"_Last generated: {today:%d %b %Y}. Struck-through deadlines have passed. "
            "`CV` computer vision · `ML` machine learning · `AI` artificial intelligence._",
            "## ⏰ Upcoming deadlines",
            upcoming_deadlines(series, today),
            "## 🏛️ Conferences",
            table(series, "conference", today),
            "## ☀️ Summer schools",
            table(series, "summer-school", today),
            "## 📚 Past editions",
            "<details><summary>Show archive</summary>\n\n" + archive(series, today) + "\n\n</details>",
            END,
        ]
    )


def splice(readme: str, block: str) -> str:
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pat.search(readme):
        raise SystemExit(f"README.md is missing the {BEGIN} / {END} markers")
    return pat.sub(lambda _: block, readme)


# ----------------------------------------------------------------------------- ICS


def ics_escape(t: str) -> str:
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def vevent(uid: str, summary: str, start: dt.date, end_incl: dt.date, url: str, desc: str) -> list[str]:
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}@awesome-cv-events",
        "DTSTAMP:20260101T000000Z",
        f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
        f"DTEND;VALUE=DATE:{end_incl + dt.timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{ics_escape(summary)}",
        f"URL:{url}",
        f"DESCRIPTION:{ics_escape(desc)}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def build_ics(series: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//awesome-cv-events//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:CV & DL Conferences + Summer Schools",
    ]
    for s in series:
        for e in s["editions"]:
            lab = label(s, e)
            base = hashlib.sha1(f"{s['id']}-{lab}".encode()).hexdigest()[:12]
            start, end = as_date(e["start"]), as_date(e["end"])
            if start:
                lines += vevent(base, f"📍 {lab} — {e['location'] or 'TBA'}", start, end or start, e["url"], s["full_name"])
            for k, v in (e["deadlines"] or {}).items():
                d = as_date(v)
                if d:
                    tz = f" ({e['timezone']})" if e.get("timezone") else ""
                    lines += vevent(f"{base}-{k}", f"⏰ {lab}: {DEADLINE_LABEL[k]} deadline{tz}", d, d, e["url"], s["full_name"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ----------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate and verify generated files are up to date")
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = ap.parse_args()

    series = load()
    errs = validate(series)
    if errs:
        print("Validation failed:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1

    readme_new = splice(README.read_text(encoding="utf-8"), render(series, args.today))
    ics_new = build_ics(series)

    if args.check:
        # The "last generated" line changes daily; ignore it when checking staleness.
        strip = lambda t: re.sub(r"_Last generated: [^.]*\.", "", t)
        stale = strip(README.read_text(encoding="utf-8")) != strip(readme_new) or (
            not ICS.exists() or ICS.read_bytes() != ics_new.encode("utf-8")
        )
        if stale:
            print("Generated files are out of date — run: python scripts/build.py", file=sys.stderr)
            return 1
        print(f"OK: {len(series)} series, {sum(len(s['editions']) for s in series)} editions")
        return 0

    README.write_text(readme_new, encoding="utf-8")
    ICS.write_bytes(ics_new.encode("utf-8"))
    print(f"Wrote README.md and calendar.ics ({len(series)} series)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
