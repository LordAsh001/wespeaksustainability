# We Speak Sustainability

*Small actions. Real people. A better world.* Live at **https://wespeaksustainability.com**

This repository is a static site. `build.py` turns the content in `data/` into the website, and a GitHub Action rebuilds and publishes it on every change, plus once a week so the homepage features rotate.

## How to edit content (no coding needed)

All content lives in three files in `data/`:

| File | What it holds |
|---|---|
| `data/stories.json` | Every story (Small Things and People Making Change) |
| `data/legacy.json` | Memorial profiles: environmental defenders and footprints |
| `data/site.json` | Settings: Tally form IDs, analytics, taxonomy, problems, SDGs, evidence labels |

To edit: open a file on GitHub, click the pencil icon, make the change, then **Commit changes**. The site updates within about two minutes. If you make a mistake, the build stops with a message naming the problem and the live site stays as it was.

### Editorial workflow

Each story has an `editorial_status`. Only `published` and `updated` appear on the site.

`submitted → initial-review → verification-required → interview-requested → fact-checking → approved → published → updated → archived`

1. New submissions arrive in the Tally inbox (once `tally_story_form` is set in `data/site.json`).
2. The editor copies a submission into `stories.json` with `"editorial_status": "initial-review"`. It is saved but not public.
3. Check facts and add sources: at least 2 independent of the contributor. Set `evidence` to `verified`, `documented`, `self-reported` or `insufficient`.
4. Set `"editorial_status": "published"` and commit.

Flag problems in an `editor_flags` list (for example `["missing-evidence", "privacy"]`). It is never shown publicly.

### Corrections

Readers report errors at `/corrections/` (GitHub Issues, or a Tally form once `tally_correction_form` is set). Fix the story, add a dated line to its `status_note`, and set `"editorial_status": "updated"`.

### Rules every story must meet

- Never invent people, quotes, numbers or circumstances.
- Quotes must be verbatim from a cited source and name the actual speaker (`quote.speaker`).
- Impact figures must be attributed to whoever measured them.
- Map coordinates are town level only, never homes or sensitive sites.
- Contributors choose full name, first name only, or anonymous.

## Settings to complete

In `data/site.json`:
- `tally_story_form`: the ID of the Tally "Tell your story" form (the part after `tally.so/r/`).
- `tally_correction_form`: the ID of the Tally corrections form (optional; GitHub Issues is used until it is set).
- `goatcounter`: a GoatCounter site code for privacy-friendly analytics (optional).

## Run locally

```
python3 build.py      # writes the site to _site/
cd _site && python3 -m http.server
```
