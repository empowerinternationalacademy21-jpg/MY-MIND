# MyMind – My World activity tracking, caretaker analytics & personalised world: delivery report

Every file below is a **complete file at its repo path** (copy over the same path in `MY-MIND/mymind/`). Nothing was pushed to GitHub (no write access from here).

## A. Repository assessment
Flask 3 + SQLAlchemy 2 + Turso/SQLite, Jinja2, vanilla JS, Three.js island scene, hand-made SVG/CSS charts (no chart library). Existing and **reused**:
`ActivityEvent` + `/api/activity-events`, `child_scope` (caregiver↔child grants), `world_service` (themes, decorations, administrator island lock via
`island_lock`/`default_island`), `InterestProfile`, plan history limits, the caretaker glass theme. The administrator's island was **not touched**.

## B. Files
New: `routes/activity_dashboard.py`, `services/activity_analytics_service.py`, `services/interest_discovery_service.py`, `templates/caretaker_activity.html`,
`static/js/activity_dashboard.js`, `static/js/ct_charts.js`, `static/css/activity-dashboard.css`, `tests/test_activity_dashboard.py`.
Modified: `database/models.py` + `database/migrate.py` (migration 14), `routes/api.py`, `services/activity_service.py`, `services/world_service.py`,
`services/account_service.py`, `app.py`, `config.py`, `static/js/app.js`, `pictures.js`, `music.js`, `videos.js`, `world/ui.js`, `css/world3d.css`,
`css/caretaker.css`, `templates/ct_layout.html`, `caretaker.html`, `my_world.html`, `README.md`.

## C. Backend
* `activity_events` gets `content_type, category, completion_pct, content_seconds, pause/resume/replay_count, completed, measured` + 2 indexes. Existing rows back-filled.
* New event types `listen` (songs), `look` (pictures), `browse` (category explored). Server checks watch→video/short, listen→song, look→picture, ranges, categories.
* Sessions only grow (max duration/completion/counters, `completed` sticky) → retries and out-of-order heartbeats can't duplicate or shrink.
* Authorisation: caregiver-only; child resolved via `child_scope` grant; detail records via `child_scope.query(child AND caregiver)`; foreign child = 404; child sessions = 403.
* Retention: `ACTIVITY_RETENTION_DAYS` (365 default, min 30), daily opportunistic purge + `flask purge-activity`. Search text is never stored.
* Fixed: account deletion crashed and could leave children's data behind; it now erases every child and all dependent rows (also fixed 3 existing failing tests).

## D. Frontend
`/caretaker/activity`: stat cards, recent feed with real thumbnails, 8 graphs (daily-by-hour, 7-day, month, interest distribution, content types,
interest development, time allocation, most engaging), trends (up/down/steady/new), rankings, day timeline + 24h strip, filterable/searchable/paginated
history (type, action, category, title search, dates, today/week/month), record dialog showing the actual picture / embedded video or song, interests panel.
Responsive, keyboard/aria-friendly, reduced-motion aware. My World: "Lately loved" chips, glow + stars on loved places (3D labels, chips, flat-map halos).

## E. Analytics (all documented in the service and on the page)
Category share = category time ÷ categorised time × 100 · Weekly change = (this − previous) ÷ previous × 100 (None if no previous) · Average/day = total ÷ days ·
Completion = played ÷ length × 100 (only when the player reports length) · Content score = minutes + 2/finish + 1.5/replay + 1/like + 2/favorite.
Engagement excludes page-open time; overlapping sessions are credited once; day boundaries use the caretaker's time zone; plan history limits respected.
Interests: ≥3 engaged sessions on ≥2 days and decayed score ≥3 (half-life 14 d); trend = last 7 days vs previous 7. Each insight lists its evidence and the
dashboard states these are possible interests, not an assessment of ability or talent.

## F. 3D world
Every child still gets the administrator's island/world. `world_service.activity_interests()` adds modest decaying evidence from real sessions to the saved profile
(likes/favorites are not double counted): themes, unlocked "extra" places, decoration counts and the new per-stop `interest` level change per child. No activity = identical to before.

## G. Testing
Python: 14 new tests (tracking validation, no-shrink sessions, overlap, formulas, zero data, history filters/pagination/LIKE escaping, discovery, per-child world on one shared base, API security, grants, retention).
Full suite: **305 passed, 5 failed, 1 skipped**. The 5 failures also fail on the untouched original code: 1 island-lock test, 4 recovery tests (a 403 on the onboarding step).
JS: the dashboard ran in jsdom against real API output (all panels rendered, no errors, HTML in titles stays literal text); the tracker ran against simulated YouTube/Spotify
messages (40+50+10 s played with a 500 s pause excluded → 100 s, 2 pauses, 1 resume, 1 replay, completed; one session despite a duplicate start).

## H. Not done / needs you
* **Not tested in a real browser or against live YouTube/Spotify.** Player state relies on their postMessage protocols (YouTube `enablejsapi`, Spotify `playback_update`); if a player stays silent the app falls back to open-time and marks it `measured=false`. Please test once on a phone and desktop. `tests/browser` (Playwright) was not run.
* 3D scene geometry is unchanged: emphasis shows as glow/stars/halo and through the existing decorations, not new 3D models. New models (e.g. a football) need assets from your AI3D library.
* "Games" and "learning activities": the app has none yet; the new `/api/activity-events` + `MM.activity.startContent/log` is the single place to register them.
* Shots (`shots.js`) needed no change (it already uses `startWatch`, now player-aware). Live graph refresh polls every 45 s.
* Free plan: history is limited to 7 days (existing rule); 30-day range stays a paid feature.
* Remaining failing tests above are pre-existing and unrelated.
