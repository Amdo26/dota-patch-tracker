# Dota 2 Patch Tracker

Single-page Dota 2 patch tracker built from Valve's official patch data (plus OpenDota meta stats).

- `update_patches.py` builds `dota2-patch-tracker.html`
- GitHub Actions (`.github/workflows/update.yml`) re-runs it every 6 hours and commits the result
- Vercel republishes the site automatically after each commit

To update by hand: GitHub -> Actions -> "Update Dota patches" -> Run workflow.
