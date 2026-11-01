# Link Generation API

Base URL: `https://your-app-domain.example.com`  ·  Auth: `Authorization: Bearer <API_KEY>`

## Overview

This bot can act as a **monetization layer for content that lives anywhere** — including your other bots. Your bot (or script, or site) tells this API where the content is and gets back a normal Telegram link. When someone opens that link, this bot runs its usual flow — force-subscribe, link shortener, ad verification — and only then delivers the content. Every completed unlock earns you ad revenue.

```text
Your other bot  --(1) tell the API where the content is-->  this API  --(2) returns link-->  Your other bot
Your other bot  --(3) sends the LINK to its user (instead of the file)
User taps link  -->  this bot: force-sub -> shortener -> watch ads -> file delivered
```

> **If your other bot already posts its files directly into this bot's storage channel** (e.g. it's also an admin there), the API never touches the file at all — it just wraps the message id you already have into a link. No download, no re-upload, no second copy sitting in the channel. This is "reference mode", covered first below.

## Quick start (5 steps)

- **Deploy** this bot with `WEBAPP_URL` in `.env` set to its public HTTPS address.
- **Create a key** in the bot: `/newapikey mybot1` (one key per bot you run — it makes reporting easy). Copy it; it is shown once. Add scopes like `links,premium` only if that bot needs them.
- **Test it:** `curl https://your-app-domain.example.com/api/v1/ping -H "Authorization: Bearer YOUR_API_KEY"`
- **Make a link** with one of the calls below (single or batch).
- **Send that link to your users** instead of the file. Check earnings per bot with `/apikeys`.

## Authentication

Send your key on every request in either header:

```text
Authorization: Bearer fsk_xxxxxxxxxxxxxxxxxxxxxxxx
X-API-Key: fsk_xxxxxxxxxxxxxxxxxxxxxxxx
```

- Create keys with `/newapikey <label> [scopes]`, list them with `/apikeys`, revoke with `/revokeapikey <id>` (or the buttons in `/apikeys`).
- Only a hash of each key is stored. If you lose a key, revoke it and create another.
- Keep keys on your **server**. Never put one in a client-side app, a public repo or a message to users.

## Permissions (scopes)

Every key only works for the scopes it was created with. This matters: a key that can grant premium or ban users is far more sensitive than one that can only make links, so **new keys get `links` only** unless you choose more.

| Scope | Allows |
|---|---|
| `links` | `/links/single`, `/links/batch` (plus `ping` and `usage`, which every key can call) |
| `premium` | `/premium` — add, remove, check and list premium users |
| `users` | `/users/...` ban, unban and look up users, and `/stats` |

```text
/newapikey moviebot                 -> scopes: links
/newapikey shopbot links,premium    -> can make links AND grant premium
/newapikey admintool all            -> every scope (use sparingly)
/apikeyscopes a1b2c3d4 links,users  -> change an existing key
```

Calling an endpoint without the needed scope returns `403 insufficient_scope`. Keys created before scopes existed keep working as `links` only.

> Give `premium` / `users` only to servers you control (for example the payment webhook of a bot that sells premium). Never to a key that lives in code other people can read.

## Limits

| Limit | Value |
|---|---|
| Requests per key | 60 per minute (`429` + `Retry-After` header when exceeded) |
| Files / messages per batch | 100 |
| Uploaded file size | 512 MB per file |
| Caption length | 1024 characters |
| `url` mode file size | Telegram downloads the URL itself: roughly 20 MB (5 MB for photos). Use `copy` or upload for bigger files. |

> Writes into the storage channel are processed **one at a time** so batch links stay a clean consecutive range. `copy` and `url` requests are quick; big uploads make other requests wait their turn.

> The **total** size of one multipart upload request is also capped (a bit above the single-file limit above). For a batch of several large files, prefer `copy` mode (add this bot to the source channel) instead of uploading — it has no size limit and is far faster.

## GET /api/v1/ping

**`GET /api/v1/ping`**

Checks that your key works.

```json
{ "ok": true, "bot": "YourBotUsername", "key_label": "mybot1", "scopes": ["links"], "version": "v1" }
```

## POST /api/v1/links/single

**`POST /api/v1/links/single`**

Creates a link to **one** file (same as `/genlink`). Send exactly one of the shapes below.

### Mode 1 — reference: content already in this bot's storage (fastest, no copy)

Use this when your other bot already posted the file into a channel this bot treats as storage — its **primary** DB channel, or any secondary one added with `/adddb`. Nothing is downloaded, copied or re-uploaded: the API just checks the message exists (metadata only) and encodes a link around its existing id. The response has `"source": "reference"` so you can tell it took this path.

| Field | Type | Required | Description |
|---|---|---|---|
| `source_chat_id` | integer | yes | The **storage** channel id your other bot posted into |
| `message_id` | integer | yes | Id of the message your other bot got back after posting |

```bash
curl -X POST https://your-app-domain.example.com/api/v1/links/single \
  -H "Authorization: Bearer YOUR_API_KEY" -H "Content-Type: application/json" \
  -d '{"source_chat_id": -1001234567890, "message_id": 45}'
```

> If `source_chat_id` **isn't** a channel this bot already stores in, the exact same request falls through to Mode 2 below (copy) automatically — you don't need to know in advance which case you're in.

### Mode 2 — copy from some other chat

For content that lives somewhere this bot doesn't already track. Add **this bot** to that chat (as admin, for channels) and it copies the message server-side inside Telegram — instant, any size, any type. Same fields as Mode 1; the difference is purely whether `source_chat_id` is already known.

> Tip: a post link like `t.me/c/1234567890/45` means chat id `-1001234567890`, message id `45`.

### Mode 3 — `url`

| Field | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Public `http(s)` link Telegram can download |
| `type` | string | no | `document` (default), `video`, `audio` or `photo` |
| `caption` | string | no | Caption shown with the file |

```bash
curl -X POST https://your-app-domain.example.com/api/v1/links/single \
  -H "Authorization: Bearer YOUR_API_KEY" -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/clip.mp4", "type": "video", "caption": "My clip"}'
```

### Mode 4 — upload a file

`multipart/form-data` with a `file` part, plus optional `type` and `caption` fields. If `type` is omitted it is guessed from the file extension (video / audio / otherwise document).

```bash
curl -X POST https://your-app-domain.example.com/api/v1/links/single \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@/path/to/movie.mp4" -F "caption=My movie"
```

### Response

```json
{
  "ok": true,
  "link": "https://t.me/YourBotUsername?start=Z2V0LTEyMzQ1Ng",
  "message_id": 123,
  "channel_id": -1001111111111,
  "source": "reference"
}
```

`source` is one of `reference`, `copy`, `url` or `file` — telling you which mode actually ran.

## POST /api/v1/links/batch

**`POST /api/v1/links/batch`**

Creates **one link** that delivers several files (same as `/batch`), up to 100. Three input styles:

### Style 1 — `message_ids` shorthand (recommended when they're all from one chat)

```json
{ "source_chat_id": -1001234567890, "message_ids": [45, 46, 47, 48] }
```

Same auto-detection as the single-link endpoint: if `source_chat_id` is already a channel this bot stores in, this is **reference mode** — no copy, and the ids must be a contiguous run in that channel (exactly what you get if your other bot posted them back-to-back). Otherwise each message is copied into this bot's primary channel, same as Style 2.

> A batch link is fundamentally *one contiguous range in one channel* — that's how the link itself is encoded. If your `message_ids` in a known channel aren't contiguous (something else was posted in between), reference mode returns `400 not_contiguous`; use Style 2 (`items`) instead, which copies your exact selection into a clean range.

### Style 2 — `items` (mix sources freely; always copies)

```bash
curl -X POST https://your-app-domain.example.com/api/v1/links/batch \
  -H "Authorization: Bearer YOUR_API_KEY" -H "Content-Type: application/json" \
  -d '{"items": [
        {"source_chat_id": -1001234567890, "message_id": 45},
        {"source_chat_id": -1009876543210, "message_id": 12},
        {"url": "https://example.com/extra.pdf"}
      ]}'
```

### Style 3 — upload several files

```bash
curl -X POST https://your-app-domain.example.com/api/v1/links/batch \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@ep1.mp4" -F "file=@ep2.mp4" -F "file=@ep3.mp4"
```

### Response

```json
{
  "ok": true,
  "link": "https://t.me/YourBotUsername?start=Z2V0LTEyMy00NTY",
  "count": 3,
  "first_message_id": 123,
  "last_message_id": 125,
  "message_ids": [123, 124, 125],
  "skipped": [],
  "source": "reference"
}
```

> In copy mode, if some items fail (for example a deleted source message) they're listed in `skipped` with an `error` and `message`, and the link covers the rest. If **all** fail you get a `502`. Reference mode has no partial failure — either the whole range is valid, or you get an error.

## Premium users

Needs the `premium` scope. Premium users skip ads and the shortener. All dates are the bot server's local time; `expires_at_unix` is given as well so you never have to guess a timezone.

### POST /api/v1/premium/add

**`POST /api/v1/premium/add`**

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | integer | yes | Telegram user id |
| `days` | integer | no | 1-3650. **Omit for permanent premium.** |
| `mode` | string | no | `extend` (default) adds `days` on top of the current plan; `replace` sets the plan to exactly `days` from now |
| `notify` | boolean | no | Send the user a message from this bot (default `false`). Never fails the request if they haven't started the bot |
| `request_id` | string | no | Your own unique id for this operation. Retrying with the same id is safe — it is applied only once |

```bash
curl -X POST https://your-app-domain.example.com/api/v1/premium/add \
  -H "Authorization: Bearer YOUR_API_KEY" -H "Content-Type: application/json" \
  -d '{"user_id": 123456789, "days": 30, "request_id": "order-8841"}'
```

```json
{
  "ok": true, "duplicate": false, "action": "activated",
  "user_id": 123456789, "premium": true, "permanent": false,
  "expires_at": "2026-10-30T12:00:00", "expires_at_unix": 1793361600, "days_left": 30,
  "previous_expires_at": null
}
```

`action` tells you what happened:

| action | Meaning |
|---|---|
| `activated` | The user wasn't premium (or it had expired) — now they are |
| `extended` | They were premium; `days` were added to the end of their current plan |
| `replaced` | `mode: replace` — the plan now ends exactly `days` from now |
| `made_permanent` | `days` was omitted and the user had a time-limited plan |
| `unchanged` | Nothing to do (for example: extending a plan that is already permanent) |

> **Selling premium on another bot?** Call this from your payment-confirmation handler and always send a `request_id` (your order or payment id). Payment providers retry webhooks, and without a `request_id` a retry would extend the plan twice. With it, the repeat gets `"duplicate": true` and the plan is untouched.

### POST /api/v1/premium/remove

**`POST /api/v1/premium/remove`**

Body: `{ "user_id": 123456789, "notify": false }`. Safe to repeat — removing someone who isn't premium succeeds with `"removed": false`.

```json
{ "ok": true, "removed": true, "was_active": true, "user_id": 123456789, "premium": false, "permanent": false,
  "expires_at": null, "expires_at_unix": null, "days_left": null }
```

### GET /api/v1/premium/{user_id}

**`GET /api/v1/premium/{user_id}`**

Current status of one user.

```json
{ "ok": true, "user_id": 123456789, "premium": true, "permanent": false,
  "expires_at": "2026-10-30T12:00:00", "expires_at_unix": 1793361600, "days_left": 29 }
```

### GET /api/v1/premium?limit=50&offset=0

**`GET /api/v1/premium`**

Active premium users, oldest id first. `limit` is 1-200. `total` is the full count so you can page through.

```json
{ "ok": true, "total": 2, "limit": 50, "offset": 0, "users": [
  { "user_id": 111, "premium": true, "permanent": true, "expires_at": null, "expires_at_unix": null, "days_left": null },
  { "user_id": 222, "premium": true, "permanent": false, "expires_at": "2026-10-30T12:00:00", "expires_at_unix": 1793361600, "days_left": 29 }
] }
```

## Users & stats

Needs the `users` scope.

### GET /api/v1/users/{user_id}

**`GET /api/v1/users/{user_id}`**

```json
{ "ok": true, "user_id": 123456789, "started_bot": true, "banned": false,
  "premium": { "premium": false, "permanent": false, "expires_at": null, "expires_at_unix": null, "days_left": null } }
```

### POST /api/v1/users/ban  ·  POST /api/v1/users/unban

**`POST /api/v1/users/ban`**

Body: `{ "user_id": 123456789 }`. Banning someone who has never started the bot works — the ban is already in place when they do. Admins and the owner can't be banned through the API (`400 protected_user`). Response: `{ "ok": true, "user_id": ..., "banned": true, "changed": true }` — `changed` is `false` if they were already in that state.

### GET /api/v1/stats

**`GET /api/v1/stats`**

```json
{ "ok": true, "users": 15230, "banned": 41, "premium_active": 312 }
```

## GET /api/v1/usage

**`GET /api/v1/usage`**

Stats for the key you are calling with: links created, and how many times users finished the ads for links this key created.

```json
{ "ok": true, "key_id": "a1b2c3d4", "label": "mybot1", "links_created": 42,
  "ads_completed": 310, "scopes": ["links"], "created_at": "2026-09-28T09:00:00", "rate_limit_per_min": 60 }
```

## Errors

Every error is JSON: `{ "ok": false, "error": "code", "message": "human readable" }`.

| HTTP | error | Meaning |
|---|---|---|
| 401 | `missing_api_key` / `invalid_api_key` | No key sent, or the key is wrong or revoked |
| 403 | `insufficient_scope` | The key lacks the scope this endpoint needs — see Permissions |
| 400 | `protected_user` | Tried to ban an admin or the owner |
| 429 | `rate_limited` | Too many requests — wait `Retry-After` seconds |
| 429 | `telegram_flood_wait` | Telegram asked the bot to slow down — retry later |
| 400 | `invalid_json` / `invalid_request` | Body could not be parsed or fields are wrong |
| 400 | `too_many_items` / `too_many_files` | More than 100 in one batch |
| 400 | `empty_file` | Uploaded file has 0 bytes |
| 404 | `message_not_found` | Reference mode: that message id doesn't exist in the given channel |
| 400 | `not_contiguous` (single-request) | Reference-mode batch: the given ids aren't a contiguous run in that channel — use `items` instead |
| 413 | `file_too_large` | Upload is over 512 MB |
| 502 | `source_unreachable` | Could not copy the message, or read the given chat — add this bot to that chat, check ids |
| 502 | `store_failed` | Telegram rejected the url/file |
| 502 | `batch_empty` | Nothing in the batch could be stored (see `skipped`) |
| 409 | `not_contiguous` (retry) | Storage channel was busy while copying a batch — just retry |
| 503 | `api_disabled` / `server_starting` | API is switched off or the bot is still booting |

## Code examples

### Python (requests)

```python
import requests

BASE = "https://your-app-domain.example.com"
HEADERS = {"Authorization": "Bearer YOUR_API_KEY"}

def monetized_link(chat_id, message_id):
    r = requests.post(BASE + "/api/v1/links/single", headers=HEADERS, timeout=60,
                      json={"source_chat_id": chat_id, "message_id": message_id})
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("message"))
    return data["link"]

print(monetized_link(-1001234567890, 45))
```

### Node.js (fetch)

```javascript
const res = await fetch("https://your-app-domain.example.com/api/v1/links/batch", {
  method: "POST",
  headers: { Authorization: "Bearer YOUR_API_KEY", "Content-Type": "application/json" },
  body: JSON.stringify({ source_chat_id: -1001234567890, message_ids: [45, 46, 47] }),
});
const data = await res.json();
console.log(data.link);
```

A ready-made async + sync client is included as `examples/monetize_client.py` — copy that one file into each of your bots.

## Guide: monetizing your other bots

### Pick how each bot hands over its content

- **Your bot already posts into this bot's storage channel** (it's an admin there too) → reference mode. Capture the message id it gets back right after posting, call the API with that id, done. No copy, no download, no duplicate file sitting in the channel — just a link.
- **Your bot stores files in some other channel of its own** → add *this* bot to that channel too, then call the same endpoint the same way — it copies once, automatically (Mode 2).
- **Your bot has files on disk or in memory, nowhere on Telegram yet** → use the upload mode. (Telegram `file_id`s only work inside the bot that owns them, so they can't be passed across bots.)
- **Your bot only knows a download URL** → use `url` mode (small files) or download and upload.
- **Series / packs / albums** → use the batch endpoint and give users the one batch link.

### Selling premium on another bot

Create a key with `/newapikey shopbot links,premium`. When a payment is confirmed on that bot, call `POST /api/v1/premium/add` with the buyer's user id, the plan length in `days`, and the payment/order id as `request_id`. Do the reverse (`/premium/remove`) when a plan is refunded.

### Change one line in each bot

Wherever the bot currently sends a file to a user, instead call the API (once per file) and send the returned link. Store `file → link` in that bot's own database so the same file is only converted once.

### One key per bot

Run `/newapikey botname` for each bot. `/apikeys` then shows, per key, how many links it created and how many ad-unlocks they produced — so you can see which bots actually earn and which are worth promoting.

### Good habits

- Handle `429` by waiting `Retry-After` seconds, then retrying.
- Create links **when a file is added or first requested**, not on every user click.
- Call the API from your server only; keep keys in environment variables.
- Revoke a key immediately if it leaks — links already created keep working.
- A key can copy from **any chat this bot can read**, so only give keys to bots you own.
- Only monetize content you own or are licensed to share, and check that it fits Telegram's terms and your ad networks' content policies. Networks such as Monetag and Adsterra restrict some content categories.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `401 invalid_api_key` | Wrong key, extra spaces, or the key was revoked. Create a new one with `/newapikey`. |
| `404 message_not_found` | Reference mode: the message id doesn't exist in that channel (deleted, wrong id, or wrong chat). |
| `502 source_unreachable` | This bot isn't in the source channel (copy mode), or can't read the given chat at all. Add the bot and re-check ids. |
| Link opens but says invalid / expired | The link was made by a different bot deployment or the storage channel changed. Recreate the link. |
| Users don't see ads | `WEBAPP_URL` must be your real public HTTPS URL, ads must be enabled (`/adsenable`) and zones set (`/adssettings`). |
| `429 rate_limited` in bulk jobs | Limit is 60/min per key. Batch files together, or space requests out. |
