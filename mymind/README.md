# MyMind — Built and Powered by Emtrixz

*Your thoughts. Your world.* — a discovery app where a child's picture / video / music choices help caregivers understand what they enjoy. Flask + SQLAlchemy + Turso (libSQL), Jinja2, vanilla JS.

MyMind describes **observed choices**. It never diagnoses or claims to know what a child thinks or feels.

## Quick start (local, no API keys needed)

```bash
cd mymind
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                      # then set SECRET_KEY
export ADMIN_USERNAME=owner ADMIN_PASSWORD='a-long-password-1'   # Windows: set ...
python -m database.seed                                   # tables, default settings, admin account
python app.py                                             # http://127.0.0.1:5000
```
(or `./run_local.sh`). Without API keys the app runs in **demo mode**: every demo picture/video/song is badged "Demo", and nothing pretends to come from a real API.

Tests (no keys, no network, no real payments): `python -m pytest -q`

## First-run checklist
1. Log in as admin → **Settings**: fill in WhatsApp, phone and bank details. Until then caregivers see clearly marked `[NOT SET …]` placeholders and the WhatsApp button is disabled. Nothing is invented.
2. Register a caregiver in another browser, pick a plan, submit a payment reference, then approve it under **Admin → Payments**.
3. The caregiver completes the questionnaire and lands on the personalised feed.

## Forgot password (self-service)
Login → *Forgot password?* → username → 5 questions about what the caregiver originally entered (everyday activities, interests, communication, routine, child's nickname). Each answer is scored (multi-choice = overlap with the stored answer, nickname = fuzzy match); an **average of 80% or more** unlocks a 10-minute, single-use "choose a new password" page. Below 80% the caregiver can refill the form or contact the administrator (WhatsApp/phone from Admin → Settings). Hardening: identical questions for unknown usernames (no account enumeration), 3 failures lock recovery for an hour, per-IP limits, admin accounts excluded, accounts with too few stored answers cannot self-recover, answers/scores are never shown or logged, and every reset is written to the audit log. *Trade-off:* these answers are knowable by someone who knows the family, so the admin-assisted reset remains available and the limits above matter.

## Icons
All icons are inline [Lucide](https://lucide.dev) line icons (ISC licence, see `static/vendor/LUCIDE-LICENSE.txt`), rendered in black from one SVG sprite (`templates/_icons.html`); no emoji are used in the interface.

## Subscription workflow
**Free trial:** every new account gets a free trial (default **30 days**, configurable in Admin → Settings; `0` disables it) that starts at registration and skips straight to the questionnaire. When it ends, the server closes the app (all pages and APIs) until a plan is paid for and approved. Paying early stacks after the trial. One trial per account.

register → choose plan (Weekly $25/7d, Monthly $50/30d, Yearly $250/365d; editable by admin) → payment instructions → "request verification" (reference + date; status `pending_verification`) → admin approves/rejects → access. Access is checked **on the server on every request**. Approval is an atomic conditional `UPDATE … WHERE status='pending_verification'` in a transaction, so a request can only be approved once; payment references are unique; every decision is audit-logged. Renewals stack after the current expiry. Expired accounts keep their data and see renewal options.

## Turso (production database)
```bash
turso db create mymind && turso db show mymind --url && turso db tokens create mymind
# .env:  TURSO_DATABASE_URL=libsql://mymind-<org>.turso.io   TURSO_AUTH_TOKEN=...
python -m database.seed
```
Turso is reached through a small **pure-Python HTTPS driver** (`database/hrana.py`, Turso's "Hrana over HTTP" API). It needs only `requests`, so there is nothing native to compile (the official `libsql-experimental` package has no Windows wheels and needs Rust). With no Turso variables the same code uses local SQLite. The full test suite also passes against a local stand-in Turso server (`MYMIND_TEST_BACKEND=hrana python -m pytest`), but it has **not** been run against a live Turso database here — run the seed command first and confirm it prints "applied migration 1". Every query is one HTTPS round-trip, so pick the Turso region closest to your app server.

## API keys (optional, server-side only)
| Variable | Used for | Notes |
|---|---|---|
| `YOUTUBE_API_KEY` | video search + metadata | `safeSearch=strict`, embeddable only, official embed player. "Shots" = results ≤60 s; not an official Shorts API. Search costs 100 quota units; results cached 1 h. |
| `SPOTIFY_CLIENT_ID/SECRET` | track search, artwork, links | Client-credentials flow; playback via Spotify's official embed/link only; explicit tracks skipped. |
| `PEXELS_API_KEY` | photos | URLs + photographer credit stored (never image files); credit shown on each card. |

Re-check each provider's current terms before launch. On failure or quota exhaustion the app shows a notice and falls back to labelled demo content.

## Deployment
* Set `SECRET_KEY`, `FLASK_ENV=production`, Turso + API variables; for YouTube, use the exact variable name `YOUTUBE_API_KEY` in your host's environment settings. Host environment variables take precedence over `.env`; restart or redeploy after changing them. Start `gunicorn "app:create_app()"` (see `Procfile`); run `python -m database.seed` once.
* Use **HTTPS** — production mode sets `Secure` cookies and refuses the default `SECRET_KEY`.
* Rate limiter and cache are in-process; with multiple workers/instances move them to Redis.
* Create/rotate the admin with `flask --app app create-admin`. There is no default admin password.

## Security & privacy summary
Argon2id hashes · DB-enforced unique usernames · CSRF on every POST/API call · HttpOnly/SameSite cookies · login, signup and API rate limits · strict CSP (no inline scripts) · ownership checks on all child records (other accounts' IDs return 404) · server-side admin guards · audit log · child names/notes never sent to third parties (generic topic words only) · 18+ ID check for caretakers (Sumsub; only the outcome is stored) · consent records · JSON export + deletion workflow (caregiver requests, admin deletes) · no ads, chat, comments, public profiles, streaks or autoplay.

## How recommendations work
`services/recommendation_service.py` (weights are constants at the top):
* Caregiver answers become a **seed** (interest +4, activity/preference +1.5) kept separate from child evidence; it fades as the child's own evidence grows.
* like +3 · favorite +4 · watched +1.5 · explore +1.5 · open +0.5 · dislike −0.75 · skip 0 (recorded, not scored). Impressions are never scored; rapid duplicate taps are ignored.
* Child score decays (45-day half-life) so new interests emerge. A disliked item is hidden but never removes a whole category.
* Feed = weighted picks of liked categories + one exploration category, preferring items not shown in the last 48 h, each with a plain-language reason.

## Caretaker 18+ verification (Sumsub)
Account creators must be verified adults. Flow (`services/sumsub_service.py` documents each step): register -> `/verify` form (name, email, date of birth, consent) -> **server age gate** (exact to the day, UTC; under 18 is refused with a supportive "Access denied" and Sumsub is never called) -> signed server calls create the applicant and an SDK access token -> the WebSDK is mounted in the page -> Sumsub reviews -> **signed webhook** (`/verify/webhook`) -> the server fetches the applicant from Sumsub itself and decides. Verified means a green review **and** a document date of birth that is 18+; the typed date is only a pre-filter. Only the outcome is stored (status, time, country, document type): never a name, email, date of birth or document number.
* **Gate**: until verified, plans, trial, questionnaire, feed, My World, settings and every API are closed server-side (data export/deletion and logout stay available). The free trial starts when verification succeeds. Existing accounts verify at their next login. Admins are exempt.
* **Setup**: in the Sumsub dashboard create a level (name = `SUMSUB_LEVEL_NAME`), create an app token + secret, and add a webhook to `https://YOUR-DOMAIN/verify/webhook` for `applicantReviewed` with a secret key (= `SUMSUB_WEBHOOK_SECRET`; HMAC SHA256/SHA512, legacy SHA1 is refused). Use sandbox credentials first.
* **Modes**: `ID_VERIFICATION=` auto / `off` / `demo` (development only, the app refuses to start in production with it) / `sumsub`.
* **Safety rails**: per-account and per-IP rate limits, three under-18 declarations pause the form for 24 h, 10-minute SDK tokens refreshed on demand, webhook never trusted without a signature *and* a server-side re-fetch, strict CSP relaxed only on `/verify` for the Sumsub SDK host.
* **Not verified here (needs your sandbox)**: live Sumsub calls, how `fixedInfo` pre-fill interacts with your level's data-mismatch rules, the exact applicant JSON for your level, the SDK script URL (`SUMSUB_SDK_URL`), camera behaviour on real phones, and which ID types Sumsub accepts in each country you serve (including refugee documents).

* **Off by default**: with no Sumsub keys set (local development, the test suite) the check is switched off, so nothing changes until you add credentials. Existing databases are upgraded automatically (migration 5 adds the outcome columns to `users`).

## Parent links (family view)
A caregiver can let a parent or family member look at the child's world, read-only, without an account (Settings → *Parent links*, `/settings/parent-links`).
* **Two secrets, both needed:** a private link (256 random bits, **never stored**: only its SHA-256) and a per-link *view password* the caregiver chooses (Argon2id; not the account password). The full link is shown once, at creation.
* **Brute-force and enumeration:** five wrong passwords pause that link for 15 minutes (counted per link, so changing IP doesn't help), plus per-IP limits. Unknown, malformed, expired and revoked links all show the same "not available" page.
* **Control:** links can expire (7 / 30 / 90 days or until revoked) and be revoked at any time; revoking, expiry, a suspended account and a deleted account take effect on the **next request**, even mid-session. Up to 5 active links per child. Each link shows its open count and last-opened time.
* **What is shown:** nickname, avatar, enjoyed and exploring interests and favourites, worded as observations. Never caregiver notes, questionnaire answers, settings, payments or account details.
* **Privacy headers:** `/p/*` is sent `noindex`, `no-store` and `no-referrer`; `/robots.txt` disallows `/p/`. Link creation and revocation are audit-logged (never the token). Migration 4 adds `parent_links`.

## World Library (art uploads)
`/admin/world` (Admin dashboard → *World Library*): island art, stop interiors, backgrounds and characters or stars, filed by stop, sports zone and theme.
* **Uploads are untrusted input:** opened with Pillow (PNG, JPEG, WebP only), pixel-bomb and size limits (`WORLD_UPLOAD_MAX_BYTES`, 10 MB), EXIF orientation applied, scaled to at most 2048 px, **re-encoded to WebP (all metadata, GPS included, is dropped)** and stored under a random name. The original bytes are never kept or served.
* **Rights:** every upload needs a rights confirmation. A picture of a **real person** also needs a source or licence note, is labelled "Not affiliated with or endorsed by the person shown", and stays **hidden unless the caregiver turns on** *Show licensed pictures of real people* in Settings.
* **Showing it:** visible art appears in a "Friends and places" section on `/world`. Endpoints: `GET /api/world-assets` (filters `kind`, `stop`, `zone`, `theme`) and `GET /world-assets/<file>`, both caregiver-only. Admins can hide, show or delete any item.
* **Production:** point `WORLD_ASSET_DIR` at persistent storage. Migration 2 adds `world_assets`.

## AI 3D pipeline (Admin → AI 3D)
Admins create ORIGINAL items and characters in four categories (food, nature, music, sports). Children only ever see what an admin has **approved**.
* **Safety by construction** (`services/ai3d/safe_prompts.py`): prompts are assembled only from allow-listed archetypes and attributes (colour, style, mood, accessory), never from free text. Names and captions are screened and **refused, never rewritten**, when they mention real people, teams, leagues, brands, links, or "looks like / inspired by / parody" phrasing. Reference photos are not supported at all. The block-list is a safety net; the admin's review before publishing is the real gate. Licensed real-star art goes through the World Library.
* **Flow** (`services/ai3d/pipeline.py`, resumable, state in `assets3d`): items: text to 3D (Meshy preview then refine, or Tripo `text_to_model`). Characters: safe prompt, 2D concept image (OpenAI or Stability), image-to-3D, auto-rig (Meshy walk/run come with the rig; Tripo `animate_retarget` walk and run), then download, optimise, **admin review**, publish. Failed jobs record a safe message and *Retry* restarts only the failed step, so earlier paid steps are not repeated.
* **Guard-rails:** `AI3D_MAX_JOBS_PER_DAY` (default 20); downloads must be HTTPS, from an allow-listed host (`AI3D_DOWNLOAD_HOSTS`), without redirects, under a size cap, and must be a valid GLB. Unpublished files sit in `AI3D_PRIVATE_DIR` and are served only to admins; caregivers get **published models only** (never the concept image).
* **Budget:** the provider parameters set the polygon target (`AI3D_TARGET_POLYS`, default 12k). If `@gltf-transform/cli` is installed (`npm i -g @gltf-transform/cli`) each model is also compressed with Meshopt and its textures resized to WebP (simplification is off: it can damage skinned meshes); otherwise the file is kept as delivered. The review page shows triangles, size, textures, animations and warnings.
* **Run:** `flask --app app ai3d-worker` (loops; `--once` for cron) advances jobs; the job page also has *Refresh*.
* **Viewer** (`static/js/asset3d.js`, `static/vendor/three-gltf.min.js`, rebuild with `sh tools/vendor/build.sh`): Three.js (MIT) with GLTFLoader, Meshopt and Draco decoders, procedural studio lighting, shadow, drag-to-turn, animation-clip buttons. A model loads only when tapped, one at a time, and frees the GPU when closed or when the tab is hidden; reduced-motion is respected. The CSP allows `wasm-unsafe-eval`, `worker-src blob:` and `connect-src blob:` for the decoders. KTX2 textures are not supported.
* **Verified in a real browser:** the viewer renders Meshopt-compressed models with lighting, shadow, drag-to-turn and animation clips (see Tests). **Not verified here:** live Meshy, Tripo, OpenAI and Stability calls, which need your keys and network (they are written to each provider's documented REST shapes and tested against mocks). Run `flask --app app ai3d-check`, then **one test job per provider**, and confirm the model names in `config.py` in each dashboard.

## Make your islands with Meshy, Tripo and OpenAI (step by step)
The map works out of the box with a built-in procedural look. These steps replace it, piece by piece, with AI-generated models.
1. **Put your keys in `.env`** (never in code or in `.env.example`): `MESHY_API_KEY`, `TRIPO_API_KEY` and `OPENAI_API_KEY` (OpenAI makes the concept image that Meshy or Tripo turn into 3D; it is used for the island kit and for characters). Check the model names in `config.py` against each dashboard (`MESHY_MODEL`, `TRIPO_MODEL`, `OPENAI_IMAGE_MODEL`).
2. **Run `flask --app app ai3d-check`.** It confirms each key works, shows balances, checks the OpenAI image model exists for your key, and checks storage. Fix anything marked FAIL first.
3. **Keep a worker running:** `flask --app app ai3d-worker` as a second process next to the web server (or `--once` from cron). Point `AI3D_PRIVATE_DIR` and `WORLD_ASSET_DIR` at persistent storage on your host. Optional: `npm i -g @gltf-transform/cli` to compress models for phones.
4. **Try one piece first.** Admin → AI 3D → *New model* → "Island piece: Home", choose a provider. Watch it reach *review*, open it, and look at it from every side. Only publish what you like.
5. **Then queue the whole island kit** (Admin → AI 3D → *Island kit*). It creates one job per piece: an island base plus a landmark for each place (13 jobs, subject to `AI3D_MAX_JOBS_PER_DAY`, and it uses your provider credits). Each goes to review; publish the good ones, retry or reject the rest.
6. **What happens on the map:** a published *Island base* replaces the island shape on every island (its flat top becomes the surface), and a published landmark replaces that place's built-in landmark. Anything unpublished, missing or failing to load keeps the built-in look, so the map never breaks. Unpublish a piece to go back; if you publish a newer one, it wins.
* **Tips for good results:** generate the island base first and check it has a flat top; pieces are sized automatically (a landmark is scaled to about two units tall and stands on the island). Landmark prompts are fixed, safe and generic (cottage, television, drum, ice-cream, and so on) so results stay original and child-friendly. Meshy and Tripo run on the providers' own schedules, so a job can take several minutes.
* **What I could not verify for you:** the live provider calls. Everything around them (prompts, job steps, downloads, validation, review, publishing, the map swapping models in, the fallback) is tested, including in a real browser with synthetic island and house models.

## My World (adaptive island world)
`/world` is a game-like island map built from the child's own choices and fully controlled by the caregiver. Everything in it is a plain observation of choices, never a diagnosis.
* **Stops are data** (`STOP_DEFS` in `services/world_service.py`): Home, Pictures, Videos, Shorts, Music, Sports, Food & Ice-cream, Colors & Shapes and Nature are always there; **Animals, Vehicles and Art** appear only when that interest is saved or ticked by the caregiver. Adding a stop is a data change. Islands are joined by a walk of bridges.
* **Theme engine** (`resolve_theme`, a pure function of saved data): a theme (Music, Food, Colors, Animals, Nature, Vehicles, Art, Football, Basketball, or Mixed) applies only after **repeated positive evidence** (score >= 3 and >= 3 child actions) or an interest the caregiver confirmed. One click, skips, views and dislikes never create a theme; a runner-up within 80% of the leader keeps the world **Mixed**. **Football and Basketball come only from the sports zones the caregiver picks**, never from guesses. Every theme shows its plain-language reason. A caregiver can pick a style by hand, or *Reset theme* (it starts counting evidence from now; nothing is deleted).
* **Decorations** grow with the child's evidence for each place (tiers at 3 / 6 / 10 actions: 3, 6 or 10 small props), scaled by a *Light / Balanced / Strong* setting, and can be switched off per place.
* **Friends:** characters uploaded to the World Library rotate on the map and in each place (`WORLD_ROTATION_SECONDS`, a time slot so it is stable across refreshes; the "Meet another friend" button always works), filtered by theme and sports zone. Approved AI 3D models show up in the place they belong to. Real-person pictures stay hidden unless the caregiver turns them on and always carry the "not affiliated" label. Island art becomes a place's badge, interior art its header, background art the map's backdrop.
* **Each place opens a sheet** with its friends, zone or flavour chips (sports zones, ice-cream flavours) and a shelf that reuses the normal Pictures / Videos / Shorts / Music cards (same reactions, favourites, quotas and safety filters). Home shows the child's favourites.
* **Caregiver controls** (the sliders button on the map): theme, strength, confirmed interests, sports zones, places to hide (Home always stays), decorations off, friend rotation, gentle animation, soft sounds (WebAudio tones, no files), licensed real-person pictures, and a simple-map switch. Reduced motion in Settings or the operating system always wins over animation. Endpoints: `GET /api/world`, `GET /api/world/stop/<key>`, `POST /api/world/settings` (validated; unknown keys are refused), `POST /api/world/reset-theme`.
* **3D scene** (`static/js/world/scene.js`): fully procedural Three.js (no art or model files): floating islands with a landmark each, plank bridges, animated water, drifting clouds, theme palettes. Drag to pan, wheel / pinch / buttons / `+` `-` keys to zoom, tap a place to fly to it; place labels are real focusable buttons and a list of places sits under the map. It adapts: slow frames drop shadows and pixel ratio, then offer the simple map.
* **Simple map fallback** (`ui.js`): a flat SVG map with the same places, used automatically when WebGL is missing, is software-rendered (too slow), or its context is lost, and by choice (`?flat=1` or the settings switch). `?gl=force` overrides the software check.
* Migrations 2-4 add the world, AI 3D and parent-link tables; the world's settings live in the caregiver's settings (`world`).

## Tests
* Screenshots taken by those browser tests' Chromium are in `docs/screenshots/` (3D world on desktop and mobile, a place sheet, the caregiver settings, the simple map, the 3D model viewer, the family view).
* `pytest` runs the whole suite (200+ tests). The new-feature tests also pass through the Turso HTTP driver emulation: `MYMIND_TEST_BACKEND=hrana pytest`.
* **Real-browser end-to-end tests** (`tests/browser`, `sh run.sh`): headless Chromium with software WebGL against a freshly seeded throw-away instance. They cover rendering the 3D world, the automatic simple-map fallback, opening a place with friends, chips, shelf and a 3D friend (and releasing the GPU), drag / wheel / reset, keyboard use, saving caregiver settings, GPU context loss, reduced motion, parent links, and the admin 3D review viewer. Needs Node 18+ and one `npm install` (it downloads a bundled Chromium from npm).
* **Setup self-checks** that talk to the real services and cost nothing: `flask --app app sumsub-check` (Sumsub) and `flask --app app ai3d-check` (Meshy, Tripo, OpenAI/Stability keys and balances, whether the configured image model exists for the key, storage, optimiser).

## Layout
`app.py` factory + CLI · `config.py` · `database/` models, migrations, seed · `routes/` blueprints · `services/` providers, recommendations, payments, safety · `templates/` (+`admin/`) · `static/` · `tests/` (200+ unit tests plus `tests/browser`).

## Known limits
* JS was syntax-checked and every page renders in tests, but it has not been click-tested in a real browser — try it on an Android phone.
* YouTube/Spotify/Pexels are tested with mocks only (no keys here).
* Screen-time reminders are counted per browser: a gentle reminder, not enforcement.