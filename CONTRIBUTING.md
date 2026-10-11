# Contributing

Thanks for helping keep this tracker accurate.

## Ground rules

1. **Official sources only.** Every edition needs a `verified_from` URL on the event's own website. Aggregators (WikiCFP, deadline trackers) are fine for finding things, not for citing.
2. **Never guess.** If a date, city or deadline isn't published yet, write `null`. The table shows it as *TBA* and the monthly check will flag it.
3. **Don't edit the generated part of README.md** (between the `BEGIN/END GENERATED` markers). Edit the YAML and run `python scripts/build.py`.

## Yearly routine

The **Monthly update check** issue tells you what to do. Typically:

| When | What |
|---|---|
| A conference ends | Add next year's edition as soon as its site goes up, even with only dates/location |
| CfP published | Fill in `deadlines` and `timezone` |
| Jan–Mar | Summer schools announce — add new editions and application deadlines |
| A series skips a year or stops | Set `status: dormant` (it moves to the archive section) |

## Schema

```yaml
- id: cvpr                      # unique, lowercase
  name: CVPR                    # short name shown in tables
  full_name: IEEE/CVF Conference on Computer Vision and Pattern Recognition
  type: conference              # conference | summer-school
  area: [computer-vision]       # computer-vision | machine-learning | artificial-intelligence
  frequency: annual             # annual | biennial-odd | biennial-even | multiple-per-year | irregular
  status: active                # active | dormant
  homepage: https://cvpr.thecvf.com
  editions:
    - year: 2027
      title: null               # optional; set when a series has several editions in one year
      url: https://cvpr.thecvf.com/Conferences/2027
      location: Seattle, USA    # or null
      start: 2027-06-20         # or null
      end: 2027-06-25           # or null
      timezone: AoE             # optional
      deadlines:                # any of: abstract, paper, notification, application,
        abstract: 2026-11-10    #   registration, round2_abstract, round2_paper, round2_notification
        paper: 2026-11-16
        notification: 2027-02-25
      notes: optional free text shown under the name
      verified_from: https://cvpr.thecvf.com/Conferences/2027/CallForPapers
```

`frequency` drives the update check: it's how the checker knows ICCV skips even years and that CVPR 2028 should appear about a year before June 2028.

## Local commands

```bash
pip install -r requirements.txt
python scripts/build.py                  # validate + regenerate README.md and calendar.ics
python scripts/build.py --check          # validate only, fail if generated files are stale
python scripts/check_updates.py --links  # what needs updating + broken-link check
```
