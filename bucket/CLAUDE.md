# bucket

A tiny ephemeral file drop. The problem it solves: printing a file at a library that
requires using their dedicated computer, without wanting to log into a Google account
(2FA, etc.) on a public machine. Instead: upload from phone to `bucket.hellyhome.nl`,
walk to the library computer, open the same URL, download, print. No accounts.

## Why this lives in a `bucket/` subdirectory of `helly`, not its own repo

`helly` (this user's other `hellyhome.nl` project) is a static GitHub Pages site with no
build step and no server — it cannot run backend code, so it cannot hold upload state,
check a password, or expire files on a timer. This needs a real Flask process, deployed
the same way as this user's other small Flask/Railway apps (`zoosnap`, `chessscenes`).

A separate repo was the original plan, but the GitHub App backing this session isn't
authorized to create new repositories (`create_repository` returned 403 — an
org/integration-level restriction, not something to route around). Since this session
already had push access to `helly`, the app was placed in a `bucket/` subdirectory of
that repo instead. **The two deployments stay fully independent**: GitHub Pages keeps
serving the repo root (`index.html`, `games/`, `CNAME`) exactly as before, completely
unaware `bucket/` exists — Pages doesn't run any build step, so an extra subdirectory
with a `Procfile`/`requirements.txt` is inert noise to it. The Railway service for this
app must be configured with **root directory `bucket/`** (Railway's per-service "Root
Directory" setting) so it only ever builds/deploys this subtree, not the whole repo. If
a genuinely separate repo is ever wanted later (e.g. once repo-creation access is
granted), this directory can just be extracted with its git history intact
(`git subtree split`) — nothing here assumes it has to stay inside `helly`.
`bucket/.gitignore` carries a `!CLAUDE.md` negation because the repo root's own
`.gitignore` excludes any file named `CLAUDE.md` (its own CLAUDE.md is intentionally
untracked/local-only) — without the negation this file would be silently ignored too.

## Design

- **One shared bucket, no accounts — and now everything is behind the password,
  including reads.** The original design left `GET /api/files` and `GET /f/<slug>/
  <file>` unauthenticated on purpose (a library computer shouldn't need to log into
  anything). That was deliberately reversed on explicit request: `/api/files` and the
  download route both `abort(401)` when the session isn't unlocked, and the frontend
  shows a full-screen password gate before rendering anything else — no file list, no
  filenames, nothing is visible pre-auth. `POST /api/login` is unchanged; it's just no
  longer the *optional* half of the app.
- **Automatic expiry is still the real ephemerality guarantee**, independent of the
  read-gating above. `sweep_expired()` runs on every read (`/api/files`, `/f/<slug>/
  <file>`) and deletes any upload older than `TTL_HOURS` (default 12). This is a lazy
  sweep, not a scheduled job — no Railway cron needed.
- **Manual delete/clear are on top of that, not instead of it.** Once unlocked with the
  password, each file gets a delete button and there's a "clear all" — for when you
  don't want to wait out the TTL. Both automatic and manual paths were explicitly asked
  for; there was no need to pick one over the other.
- **No database.** Each upload is `data/<random-slug>/<original-filename>` — the slug
  is the unguessable/short URL component, the real filename is preserved for the
  download's `Content-Disposition`. Upload time comes from the folder's mtime, so
  there's nothing to keep in sync with a DB row. This mirrors zoosnap's "don't add
  infra a one-page app doesn't need" instinct, just taken one step further since this
  app doesn't even need SQLite.
- **Session auth, not a token in the URL.** `POST /api/login` checks `BUCKET_PASSWORD`
  and sets a signed Flask session cookie (`unlocked=True`) — same shared-password-behind-
  a-cookie pattern as zoosnap's `/admin`/`/judge`, chosen for the same reason: this is a
  low-stakes personal tool, not something that needs real user accounts.
- **`BUCKET_PASSWORD` has no default.** Unlike zoosnap's `noor`-default (a party game
  where the stakes of a guessed password are near zero), this app guards real personal
  documents being uploaded from a phone, so `/api/login` returns 503 rather than
  silently accepting a guessable default if the env var is unset.
- **UI is a Finder/Explorer-style icon grid, not a list.** One page, neutral palette,
  system font stack, no loud colors/animation. Each tile shows a type badge (extension
  text on a soft per-type tint — pdf/doc/sheet/slide/zip/text/generic) or, for image
  extensions, an actual `<img>` thumbnail pointed straight at the download URL (works
  fine despite the download route's `as_attachment=True` — browsers only honor
  `Content-Disposition: attachment` on top-level navigation/direct downloads, not on
  `<img src>` sub-resource fetches, so no separate thumbnail endpoint was needed).
  Filename and size sit below each icon; the goal (per explicit ask) is "know the file
  type, most of the name, and the size at a glance," matching how a real file browser
  reads, not a spreadsheet-style row.
- **Files are grouped by hours-remaining, not shown with a per-file countdown.**
  `hoursGroup()` in the template buckets each file into a `Math.ceil` hour count (so a
  freshly-uploaded file reads as "12h left" immediately rather than "11h left"), and
  files render under a section header per bucket, sorted newest-group-first. This was
  an explicit simplification request — exact per-file countdowns weren't wanted, just
  a coarse "grip" for how urgent a batch of files is.
- **The primary CTA is "add files" (a plain `+`), not "unlock."** Since reaching the
  app screen at all now requires having already passed the password gate, `+` just
  opens the file picker directly — no per-click password check needed anymore (that
  used to live on this button before reads were gated too; now the gate at page-load
  covers it). Delete crosses are always visible on every tile, and the footer only has
  "clear all" — there's no "lock"/logout affordance, by explicit request (`/api/logout`
  was removed along with it; nothing in the UI could reach it anymore).
- **`gatePw`/`gateSubmit` (a full-page screen, `#gateScreen`) replaced the old
  password modal.** `boot()` calls `/api/files` on load; a 401 shows the gate, a 200
  shows the app directly with that response's files — no separate "am I unlocked"
  flag needed, the fetch's status *is* the auth check. `refresh()` (used by the 20s
  poll and after delete/upload/clear) falls back to `showGate()` on a 401 too, in case
  a session ever expires while the app is open.
- The file list polls `/api/files` every 20s so a phone upload shows up on an
  already-open page without a manual refresh.

## Env vars

- `DATA_DIR` — where uploads live. Set to a Railway volume mount (e.g. `/data`) in
  production — same "real runtime data needs a volume, never git" lesson as zoosnap.
- `TTL_HOURS` — how long an upload survives before the lazy sweep deletes it. Default
  12 (raised from an initial 6 — 6h was judged too short in practice).
- `BUCKET_PASSWORD` — required for anything at all now, including viewing the file
  list or downloading — not just upload/delete/clear (see Design above).
- `SECRET_KEY` — signs the Flask session cookie. Set to a real random value in
  production.

## Local development

```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
DATA_DIR=./data BUCKET_PASSWORD=test PORT=5400 python3 app.py
```

## Deployment

Live on Railway (project `bucket`, service `bucket`, sourced from this repo's
`bucket/` subdirectory — see the root-directory note above) with a volume at `/data`,
same pattern as zoosnap. Custom domain `bucket.hellyhome.nl` is verified and serving
traffic (CNAME → the Railway-assigned target, plus a `_railway-verify` TXT record for
ownership verification — both added by the user directly on `hellyhome.nl`'s DNS
provider, not something this session can do). The plain Railway-provided domain
(`*.up.railway.app`) also keeps working as a fallback.
