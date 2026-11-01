# Bot guide

A Telegram **file-store bot** with a monetised unlock flow.
Admins keep files in private *DB channels*; the bot turns any file or batch into a share link. When someone opens a link they pass a gate — **force-subscribe → link shortener → ad verification (Telegram Mini App)** — and the file is copied into their chat. **Premium** users skip the shortener and ads. A small **HTTP API** lets your other bots create monetised links (and manage premium users) through this one.

Stack: Python · Pyrogram (pyrofork) · aiohttp · MongoDB (motor). One process runs the bot *and* the web server.

---

## 1. Layout

| Path | Role |
|---|---|
| `main.py`, `bot.py` | Start-up: builds the client, loads settings/channels, creates DB indexes, registers the `/` command menu, starts the web server |
| `.env`, `config.py` | `.env` holds your settings and secrets (git-ignored); `.env.example` is the blank template; `config.py` reads them |
| `plugins/start.py` | `/start`, the file-link gate, `/request` |
| `plugins/premium.py`, `premium_settings.py` | `/myplan`, `/profile`; admin premium settings |
| `plugins/ads.py`, `route.py` | Ad settings & stats; the Mini App pages and unlock API |
| `plugins/api_routes.py`, `api_manage.py`, `api_keys.py` | Public API (links, premium, users) and key management |
| `plugins/link_generator.py`, `channel_post.py` | `/genlink`, `/batch`, `/nbatch`; "send a file → get a link" |
| `plugins/force_sub.py`, `join_request.py` | Force-subscribe channels and join-request handling |
| `plugins/shortner.py`, `broadcast.py`, `pro_users.py`, `others.py`, `settings.py`, `texts.py`, `admins.py`, `resources.py`, `help.py` | Shortener, broadcast, premium admin, DB channels & bans, settings menu, texts, `/stats`, `/resources`, `/help` |
| `helper/` | `database.py` (all Mongo access), `helper_func.py` (encode/decode, force-sub, auto-delete), `delivery.py`, `ads_func.py`, `premium_ui.py`, `webapp_templates.py`, `geo.py`, `api_*.py`, `preflight.py`, `monitor.py` (RAM/CPU sampler) |
| `examples/monetize_client.py` | Drop-in client for your other bots |
| `API_DOCS.md` | Full API reference (also served live at `/api/docs`) |

---

## 2. Flows

### 2.1 Opening a file link (the main flow)
```
t.me/<bot>?start=<payload>
  1. Force-subscribe     not in every required channel → "🔒 Join Channel" buttons + Try Again   (skipped for ?start=premium)
  2. Register / ban      new users are saved; banned users get a refusal
  3. Premium check       premium → jump straight to 6
  4. Shortener           shortener on and not yet used → short link (Open Link / Tutorial / Buy Premium buttons)
                         the short link returns the user as  ?start=yu3elk<payload>7
  5. Ad gate             ads on and zones configured → "🎬 Unlock & Watch" button (Mini App); admins skip
  6. Delivery            files are copied from the DB channel to the user
  7. Auto-delete         if AUTO_DEL > 0: files vanish after N seconds, with a "get files again" link
```
Anything misconfigured fails *open*: no zones set or ads off → the file is delivered, never blocked.

### 2.2 Ad verification (Mini App)
1. The bot stores a one-time **session** (10 min) with the steps the user must clear and sends the button.
2. The page `/unlock/<token>` shows: **native banner (top) · verification card (middle) · credits (bottom)**. Ad SDKs load after first paint.
3. Each tap runs one ad (`show_<zone>` via Monetag; `ymid` = `token:step`). Steps are saved to the server in the background.
4. **Verify & Unlock** → server checks Telegram's signed `initData` (so it can't be called outside Telegram), that every step is done and enough time passed, atomically locks the session, **pushes the file to the chat itself**, and the page closes.
5. Stats are recorded under the visitor's **GEO tier** (1–4, from their IP). Monetag's server-side postback is stored as extra proof for rewarded formats.
6. If one ad fails 3 times in a row (no fill / blocked SDK) the user is let through (`AD_FAIL_OPEN_AFTER`), and counted as "unlocked without an ad", not as a watched ad.

*Unlock modes* (`/adsmode`): **one / two / all** configured ad units. Order: In-App Interstitial → Interstitial → Rewarded Interstitial → Rewarded Popup.

### 2.3 Premium
Premium = no ads, no shortener, `/request` access. Granted with `/addpremium` or the API; stored with a *purchased* date and expiry (or permanent). Users see it via `?start=premium`, `/myplan` and `/profile`. Every "Buy / Activate / Renew" button uses one link, set with `/setpremiumurl`.

### 2.4 Making links
1. **Send any file/message to the bot** (admins) → it is copied into the primary DB channel → you get the link.
2. **`/genlink`, `/batch`, `/nbatch`** → link files already posted in a DB channel.
3. **API** (§5) → your other bots post into a DB channel themselves (or reference/copy messages) and ask for the link.

Link format: `https://t.me/<bot>?start=<base64>` where the payload is `get-<msg_id × |channel_id|>` (batch: `get-<first×m>-<last×m>`). The multiplier identifies which DB channel the message is in.

---

## 3. Commands

**Everyone**

| Command | Response |
|---|---|
| `/start` | Welcome message (photo + Help / Close; admins also get ⛩️ Settings) |
| `/start <link>` | Runs the flow in §2.1 |
| `/start premium` | Premium: "💎 Premium Activated" + perks + expiry + Close. Otherwise: "✨ Activate Premium" + perks + button |
| `/myplan` | Premium: perks, purchase date, expiry/days left, Renew button. Otherwise the Activate screen |
| `/profile` | Name, username, ID, role, plan, expiry, what ads/shortener/requests apply to you, Buy/Renew + Contact buttons |
| `/request <text>` | Premium: sends your request to the owner. Free: upsell with Buy button |
| `/help` | Command reference (admins see the admin sections too) |

**Admin — files & channels**

| Command | Response |
|---|---|
| *(send any file)* | Copies it to the DB channel, replies with the link + Share button |
| `/genlink` | Asks you to forward/link a DB-channel post → single link |
| `/batch` | Asks for the first and last post → batch link |
| `/nbatch <n>` | Link covering the next *n* posts from a post you give |
| `/adddb <id>` (`/add_db`) | Adds a DB channel (posts a test message to check access) |
| `/removedb <id>` (`/rm_db`) | Removes one |
| `/db` | Lists DB channels (primary marked) with detail buttons |

**Admin — users & premium**

| Command | Response |
|---|---|
| `/users` | User count |
| `/ban <id>` · `/unban <id>` | Ban / unban |
| `/addpremium <id> [duration]` | `1 day`, `2 weeks`, `1 month`, `1 year`; no duration = permanent. Notifies the user |
| `/delpremium <id>` | Removes premium; user gets a "membership ended" note with a Renew button |
| `/premiumusers` | Owner only. Paged list (several messages if long) |
| `/premiumsettings` | Panel for the link, contact and perks below |
| `/setpremiumurl <url\|@user\|off>` · `/setcontact …` | Buy/Activate/Renew link · Contact button |
| `/setpremiumfeatures` | Perks list, one per line (`reset` for default) |
| `/broadcast` · `/pbroadcast` | Reply to a message: sends to all users (the second also pins). Reports ok / blocked / deleted / failed |

**Admin — ads, pages, API, other**

| Command | Response |
|---|---|
| `/adssettings` | Panel: on/off, mode, zones, template, banner height, stats |
| `/adsenable` · `/adsdisable` · `/adsmode one\|two\|all` | Gate on/off · how many ad units |
| `/setinterstitial` · `/setinappinterstitial` · `/setrewardedinterstitial` · `/setpopup <zone\|off>` | Monetag zone ids |
| `/setnativebanner <code\|off>` | Adsterra native-banner snippet (paste the full code) |
| `/adsstats` | Today / 7 d / 30 d / lifetime, by GEO tier, plus "unlocked without an ad" |
| `/postbackurl` | The Monetag postback URL to paste into their dashboard |
| `/bannerheight <px>` | Space reserved for the banner (120–700) |
| `/template violet\|emerald\|sunset` | Colour theme of the watch page, home page and docs |
| `/apikeys` · `/newapikey <label> [scopes]` · `/apikeyscopes <id> <scopes>` · `/revokeapikey <id>` · `/apidocs` | API keys (shown once; only a hash is stored) |
| `/shortner` | Shortener panel: on/off, provider URL + key, test, tutorial link |
| `/stats` | Uptime, CPU/RAM/swap/network, user count |
| `/resources [1h\|24h]` | **Now / min / avg / max** of bot RAM, bot CPU, server RAM/CPU, event-loop lag, tasks, threads, open files, network, MongoDB ping, plus a 7-day history and disk/log/cache sizes |

**Settings menu** (`/start` → ⛩️ Settings, two pages): force-sub channels · DB channels (add / remove / set primary / enable) · admins · auto-delete · protect content · photos · texts (start, force-sub, about, reply) · shortener · ads · API keys · premium settings.

The "/" menu in Telegram is registered automatically from `plugins/help.py` at start-up: everyone sees the public commands, each admin sees all.

---

## 4. Web endpoints

| Route | Purpose |
|---|---|
| `GET /` | Landing page (themed) |
| `GET /unlock/{token}` | Ad-verification Mini App |
| `POST /api/unlock/{token}/step` · `/complete` | Used by that page (Telegram-signed) |
| `GET /postback/monetag?secret=…` | Monetag server-to-server confirmation |
| `GET /api/docs` · `/api/docs.md` | API documentation |
| `GET/POST /api/v1/…` | Public API, `Authorization: Bearer fsk_…` |

## 5. API in one glance
Scopes decide what a key may do (new keys get `links` only).

| Scope | Endpoints |
|---|---|
| any key | `GET /ping`, `GET /usage` |
| `links` | `POST /links/single`, `POST /links/batch` — *reference* a message already in a DB channel (fastest, nothing copied), *copy* from another chat, fetch a *url*, or *upload* |
| `premium` | `POST /premium/add` (`days`, `mode`, `request_id` for safe retries, `notify`) · `POST /premium/remove` · `GET /premium/{id}` · `GET /premium` |
| `users` | `GET /users/{id}` · `POST /users/ban` · `/users/unban` · `GET /stats` |

Limits: 60 requests/min per key, 100 items per batch, 512 MB per upload. Full detail: `API_DOCS.md`.

---

## 6. Design

- **Messages** are HTML. Older admin panels use the original small-caps style; newer screens (premium, ads, API) use plain text with `<blockquote>` headers and ✅ lists. Dynamic values are escaped.
- **Web pages** share one layout and switch colours with CSS variables: **violet** (default), **emerald**, **sunset**. No frameworks, no external fonts; one inline stylesheet, gzip-compressed, `Cache-Control: no-store` on per-user pages.
- **Watch page**: banner slot (auto-sized to the ad, hidden if nothing loads) → progress bar and step list → one big button (*Watch Ad & Continue → Verify & Unlock*) → perks and credit links. Honours reduced-motion.
- **Copy** is deliberately generic where it matters: force-sub buttons say "Join Channel" (never the channel name).

---

## 7. Data (MongoDB)

| Collection | Holds |
|---|---|
| `users` | One doc per user (`ban` flag) **plus** the bot's settings documents (`bot_settings`, `admins_list`, `ads_settings`, `site_settings`, `premium_settings`, …). Only numeric ids count as users |
| `pros` | Premium: `expiry_date` (none = permanent), `since`, `updated_at` |
| `channels`, `fsub_status`, `request_sub` | DB / force-sub channels, per-user membership and join requests |
| `verify_sessions` | Unlock sessions (auto-deleted a day after expiry) |
| `ads_daily` | Per-day and lifetime ad counters by tier |
| `resource_daily` | Per-day min/avg/max of the monitor's metrics (auto-deleted after 60 days) |
| `api_keys`, `api_links`, `api_requests` | Keys (hashed), links they created (for attribution), idempotency claims |

Indexes are created on every start (`ensure_indexes`); a failure is logged, not fatal.

---

## 8. Configuration

Settings live in **`.env`** (next to `config.py`; copy `.env.example` if you start from scratch). Each line is `NAME=value` — no quotes, comments on their own lines. Order of priority: **real environment variables → `.env` → built-in defaults**, so a host's config vars (Heroku, `docker run -e`) always win. If required settings are missing the bot refuses to start and lists exactly what to fix.

Required: `BOT_TOKEN`, `API_ID`, `API_HASH`, `OWNER_ID`, `DB_URI`, `DB_NAME`, `DB_CHANNEL`. `ADMINS` is a comma-separated list (the owner is always added). `FSUBS` is JSON: `[[channel_id, request_to_join, invite_minutes], ...]`. Booleans are `true`/`false`.

| Setting | Meaning |
|---|---|
| `WEBAPP_URL` | **Public HTTPS URL of this server.** Required for the Unlock button, watch page and API links |
| `PORT` | Web port (`$PORT` if the host sets it, else 5010) |
| `FSUBS`, `DB_CHANNEL` | Initial force-sub and primary DB channels (more can be added from the bot) |
| `AUTO_DEL`, `PROTECT`, `DISABLE_BTN` | Auto-delete seconds · block forwarding/saving · hide Share buttons |
| `SHORT_URL`, `SHORT_API`, `SHORT_TUT` | Default shortener provider and tutorial link |
| `VERIFY_SESSION_TTL`, `MIN_AD_STEP_SECONDS`, `AD_FAIL_OPEN_AFTER`, `BANNER_MIN_HEIGHT` | Unlock-session life · anti-bypass minimum per step · let-through after N failed ads (0 = never) · default banner height |
| `POSTBACK_SECRET` | Shared secret in the Monetag postback URL — **change it** |
| `API_ENABLED`, `API_RATE_LIMIT_PER_MIN`, `API_MAX_BATCH`, `API_MAX_UPLOAD_MB` | API switches and limits |
| `DEFAULT_PREMIUM_URL`, `CONTACT_USERNAME`, `START_PHOTO`, `FSUB_PHOTO`, `SHORT_PIC`, `SHORT_IMAGE`, `UNLOCK_PHOTO` | Fallback buy link · landing-page contact · the bot's pictures |
| `LOG_FILE_NAME`, `LOG_MAX_MB`, `LOG_BACKUPS` | Log file and rotation (disk use ≈ (backups + 1) × size) |
| `SESSION`, `WORKERS`, `MSG_EFFECT`, `MONETAG_SDK_SRC`, `DEFAULT_AD_ZONE` | Pyrogram session name and workers · /start effect · ad SDK address · example zone shown in the panel |

The long default texts (`ABOUT`, `REPLY`, …) stay in `MESSAGES` inside `config.py`; admins can also change texts from the bot.

---

## 9. Deployment

**Needs:** Python 3.10+ (Docker image is 3.10, `runtime.txt` says 3.11.9), a MongoDB, a Telegram bot token + API id/hash, and a server reachable over **HTTPS** (Telegram only opens Mini Apps on HTTPS).

```bash
cp .env.example .env       # fill it in (skip this if you received a filled .env)
pip install -r requirements.txt
python3 main.py            # or: docker build -t bot . && docker run -p 5010:5010 bot
```
`.env` is read from next to `config.py` (override the path with `ENV_FILE`). **Docker:** `COPY . .` puts `.env` inside the image, so don't push that image to a public registry — or add `.env` to `.dockerignore` and run with `--env-file .env`. **Git deploys (Heroku etc.):** `.env` is git-ignored and won't be uploaded; set the same names as config vars there.
Put a reverse proxy (Caddy / nginx / your host's HTTPS) in front of port `PORT`; it must forward `X-Forwarded-For` so visitor GEO tiers are right.

**Heroku note:** the Procfile and `heroku.yml` define a `worker` process. Workers receive no web traffic, so the Mini App and API would be unreachable there; use a `web` process (the app binds `$PORT` automatically) or another host.

**First-run checklist**
1. Fill `.env` — above all `WEBAPP_URL`. Add the bot as **admin** in your DB channel(s) (`DB_CHANNEL`, or `/adddb`).
2. Start it and read the log: it warns if `WEBAPP_URL` or `POSTBACK_SECRET` are still placeholders.
3. Open `/adssettings` → set Monetag zone ids (`/setinappinterstitial`, `/setpopup`, …), paste the Adsterra banner code (`/setnativebanner`), `/adsenable`, choose `/adsmode`.
4. `/postbackurl` → paste the URL into Monetag for the rewarded zones.
5. `/setpremiumurl`, `/setcontact` (and `/setpremiumfeatures` if you sell other perks).
6. `/shortner` → provider URL + API key → *Test*.
7. Test as a normal user: send yourself a file link from a non-admin account, go through the gate, check `/adsstats`.
8. Other bots: `/newapikey shopbot links,premium`, then see `/api/docs`.

**Secrets:** they live in `.env`, which is git-ignored — never commit or share it (share `.env.example` instead), and rotate anything that was ever pushed.

---

## 10. Behaviour worth knowing

- **Nothing blocks the event loop**: shortener calls run in a worker thread with an 8 s timeout (concurrent requests for one link share a single call; a failing provider is skipped for 30 s); `/stats` samples CPU off-loop.
- Force-sub channels are checked **in parallel**; invite links are only created for channels the user still has to join.
- Ad/site/premium settings are cached ~5 s and cleared immediately when you change them.
- Broadcasts send 10 at a time, survive flood-waits and blocked users, and only target real users.
- **Auto-delete timers and the shortener cache live in memory**: a restart forgets pending deletions. Each pending delivery now costs about 2 KB (it keeps message *ids*, not Message objects) and is deleted in batches of 100 per API call.
- The ad anti-bypass is a heuristic (signed session, minimum time, optional postback), not a guarantee against a determined script.
- GEO tiers use a free IP-lookup service (rate-limited, cached per IP); unknown IPs count as tier 4. The country lists are in `helper/geo.py`.

## 11. Resource usage (minimum → maximum)

Run **`/resources`** after the bot has been up for a day for the real figures from your server — it records every 30 s and shows now / min / avg / max, plus daily history. The table below separates what was **measured** here (the bot's own code, in a test harness) from what is an **estimate** for the whole process; the libraries (Pyrogram, MongoDB driver, aiohttp) are not installed in the build sandbox, so total RSS could not be measured there.

| Resource | Minimum (idle) | Typical day | Peak / worst case |
|---|---|---|---|
| **RAM** | ≈ 70–120 MB *(estimate for this stack)*; the bot's own code adds only ≈ 13 MB *(measured)* | + a few MB: caches ≤ 1.3 MB, monitor 1.6 MB *(measured)*, ≈ 2 KB per pending auto-delete *(measured)* | + 38 MB per 1,000,000 users while a broadcast runs *(measured)*; tens of MB for ~1,000 simultaneous page loads *(estimate)*. Plan ≈ 150–250 MB; a 512 MB container is comfortable |
| **CPU** | ≈ 0–1 % of one core | < 5 % *(estimate)*. Python cost of one whole unlock is ≈ 0.4 ms *(measured, excludes HTTP/TLS and the Mongo driver)* | Broadcast (10 sends in flight) and API uploads can use a good part of one core *(estimate)*; the event loop is single-threaded, so watch **loop lag** in `/resources` |
| **Network out** | a few KB/min | ≈ 7–9 KB per unlock: watch page 6.6 KB gzip *(measured)* + three tiny API replies *(estimate)*. Files are copied inside Telegram and never pass through your server | API uploads / URL mode: the file size, once |
| **Disk** | logs ≈ 0 | MongoDB: 100,000 users ≈ 2.3 MB; 10,000 unlocks/day ≈ 5.3 MB steady *(measured document sizes; indexes add about the same again)* | **Logs up to ≈ 550 MB** (50 MB × 10 backups + current); API uploads use temp space up to `API_MAX_UPLOAD_MB` while a request runs |
| **Threads / sockets** | ≈ 10 threads, a handful of sockets *(estimate)* | thread pool grows to at most `cpu+4` (shortener, `/stats`) | MongoDB pool up to 100 connections (normally a few) |

Page weights (gzip): watch page 6.6 KB, home 2.3 KB, API docs 10 KB. Render cost: watch page 0.14 ms, home 0.01 ms (docs page 0.6 ms, rendered per request). The monitor itself costs ≈ 0.2 ms of CPU per 30 s sample.

**To cut costs on a small server:** set `LOG_MAX_MB=10` and `LOG_BACKUPS=3` in `.env` (≤ 40 MB of logs), keep `AUTO_DEL` modest, and run broadcasts off-peak.

---

## 12. Customise before you sell it
Template leftovers still in the code: the default texts in `MESSAGES` (`ABOUT`, `REPLY`), `SHORT_TUT`, `DEFAULT_PREMIUM_URL`, the default tutorial link in `plugins/shortner.py`/`start.py`, the test messages posted when adding a DB channel (`plugins/others.py`, `plugins/settings.py`, `bot.py`), and the stop-log link in `bot.py`.
