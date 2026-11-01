"""API documentation written once as data, rendered two ways: a themed HTML
page served at /api/docs and a Markdown file served at /api/docs.md (also
shipped as API_DOCS.md). `{BASE}` in any text is replaced with your public URL.
"""

import html
import re

from config import API_MAX_BATCH, API_MAX_UPLOAD_MB, API_RATE_LIMIT_PER_MIN

MAX_PAGE_DOC = 200  # keep in sync with MAX_PAGE in plugins/api_manage.py
from helper.webapp_templates import base_style

# Block types: ("p", text) ("h3", text) ("ul", [items]) ("note", text)
#              ("code", lang, source) ("table", headers, rows) ("endpoint", METHOD, path)
SECTIONS = [
    {"id": "overview", "title": "Overview", "blocks": [
        ("p", "This bot can act as a **monetization layer for content that lives anywhere** — including your other bots. "
              "Your bot (or script, or site) tells this API where the content is and gets back a normal Telegram link. "
              "When someone opens that link, this bot runs its usual flow — force-subscribe, link shortener, ad verification — "
              "and only then delivers the content. Every completed unlock earns you ad revenue."),
        ("code", "text",
         "Your other bot  --(1) tell the API where the content is-->  this API  --(2) returns link-->  Your other bot\n"
         "Your other bot  --(3) sends the LINK to its user (instead of the file)\n"
         "User taps link  -->  this bot: force-sub -> shortener -> watch ads -> file delivered"),
        ("note", "**If your other bot already posts its files directly into this bot's storage channel** (e.g. it's also an "
                 "admin there), the API never touches the file at all — it just wraps the message id you already have into a "
                 "link. No download, no re-upload, no second copy sitting in the channel. This is \"reference mode\", covered first below."),
    ]},
    {"id": "quickstart", "title": "Quick start (5 steps)", "blocks": [
        ("ul", [
            "**Deploy** this bot with `WEBAPP_URL` in `.env` set to its public HTTPS address.",
            "**Create a key** in the bot: `/newapikey mybot1` (one key per bot you run — it makes reporting easy). Copy it; it is shown once. Add scopes like `links,premium` only if that bot needs them.",
            "**Test it:** `curl {BASE}/api/v1/ping -H \"Authorization: Bearer YOUR_API_KEY\"`",
            "**Make a link** with one of the calls below (single or batch).",
            "**Send that link to your users** instead of the file. Check earnings per bot with `/apikeys`.",
        ]),
    ]},
    {"id": "auth", "title": "Authentication", "blocks": [
        ("p", "Send your key on every request in either header:"),
        ("code", "text", "Authorization: Bearer fsk_xxxxxxxxxxxxxxxxxxxxxxxx\nX-API-Key: fsk_xxxxxxxxxxxxxxxxxxxxxxxx"),
        ("ul", [
            "Create keys with `/newapikey <label> [scopes]`, list them with `/apikeys`, revoke with `/revokeapikey <id>` (or the buttons in `/apikeys`).",
            "Only a hash of each key is stored. If you lose a key, revoke it and create another.",
            "Keep keys on your **server**. Never put one in a client-side app, a public repo or a message to users.",
        ]),
    ]},
    {"id": "scopes", "title": "Permissions (scopes)", "blocks": [
        ("p", "Every key only works for the scopes it was created with. This matters: a key that can grant premium or ban users "
              "is far more sensitive than one that can only make links, so **new keys get `links` only** unless you choose more."),
        ("table", ["Scope", "Allows"], [
            ["`links`", "`/links/single`, `/links/batch` (plus `ping` and `usage`, which every key can call)"],
            ["`premium`", "`/premium` — add, remove, check and list premium users"],
            ["`users`", "`/users/...` ban, unban and look up users, and `/stats`"],
        ]),
        ("code", "text",
         "/newapikey moviebot                 -> scopes: links\n"
         "/newapikey shopbot links,premium    -> can make links AND grant premium\n"
         "/newapikey admintool all            -> every scope (use sparingly)\n"
         "/apikeyscopes a1b2c3d4 links,users  -> change an existing key"),
        ("p", "Calling an endpoint without the needed scope returns `403 insufficient_scope`. Keys created before scopes existed "
              "keep working as `links` only."),
        ("note", "Give `premium` / `users` only to servers you control (for example the payment webhook of a bot that sells premium). "
                 "Never to a key that lives in code other people can read."),
    ]},
    {"id": "limits", "title": "Limits", "blocks": [
        ("table", ["Limit", "Value"], [
            ["Requests per key", f"{API_RATE_LIMIT_PER_MIN} per minute (`429` + `Retry-After` header when exceeded)"],
            ["Files / messages per batch", f"{API_MAX_BATCH}"],
            ["Uploaded file size", f"{API_MAX_UPLOAD_MB} MB per file"],
            ["Caption length", "1024 characters"],
            ["`url` mode file size", "Telegram downloads the URL itself: roughly 20 MB (5 MB for photos). Use `copy` or upload for bigger files."],
        ]),
        ("note", "Writes into the storage channel are processed **one at a time** so batch links stay a clean consecutive range. "
                 "`copy` and `url` requests are quick; big uploads make other requests wait their turn."),
        ("note", "The **total** size of one multipart upload request is also capped (a bit above the single-file limit above). "
                 "For a batch of several large files, prefer `copy` mode (add this bot to the source channel) instead of uploading — "
                 "it has no size limit and is far faster."),
    ]},
    {"id": "ping", "title": "GET /api/v1/ping", "blocks": [
        ("endpoint", "GET", "/api/v1/ping"),
        ("p", "Checks that your key works."),
        ("code", "json", '{ "ok": true, "bot": "YourBotUsername", "key_label": "mybot1", "scopes": ["links"], "version": "v1" }'),
    ]},
    {"id": "single", "title": "POST /api/v1/links/single", "blocks": [
        ("endpoint", "POST", "/api/v1/links/single"),
        ("p", "Creates a link to **one** file (same as `/genlink`). Send exactly one of the shapes below."),
        ("h3", "Mode 1 — reference: content already in this bot's storage (fastest, no copy)"),
        ("p", "Use this when your other bot already posted the file into a channel this bot treats as storage — its "
              "**primary** DB channel, or any secondary one added with `/adddb`. Nothing is downloaded, copied or "
              "re-uploaded: the API just checks the message exists (metadata only) and encodes a link around its "
              "existing id. The response has `\"source\": \"reference\"` so you can tell it took this path."),
        ("table", ["Field", "Type", "Required", "Description"], [
            ["`source_chat_id`", "integer", "yes", "The **storage** channel id your other bot posted into"],
            ["`message_id`", "integer", "yes", "Id of the message your other bot got back after posting"],
        ]),
        ("code", "bash",
         "curl -X POST {BASE}/api/v1/links/single \\\n"
         "  -H \"Authorization: Bearer YOUR_API_KEY\" -H \"Content-Type: application/json\" \\\n"
         "  -d '{\"source_chat_id\": -1001234567890, \"message_id\": 45}'"),
        ("note", "If `source_chat_id` **isn't** a channel this bot already stores in, the exact same request "
                 "falls through to Mode 2 below (copy) automatically — you don't need to know in advance which "
                 "case you're in."),
        ("h3", "Mode 2 — copy from some other chat"),
        ("p", "For content that lives somewhere this bot doesn't already track. Add **this bot** to that chat "
              "(as admin, for channels) and it copies the message server-side inside Telegram — instant, any size, "
              "any type. Same fields as Mode 1; the difference is purely whether `source_chat_id` is already known."),
        ("note", "Tip: a post link like `t.me/c/1234567890/45` means chat id `-1001234567890`, message id `45`."),
        ("h3", "Mode 3 — `url`"),
        ("table", ["Field", "Type", "Required", "Description"], [
            ["`url`", "string", "yes", "Public `http(s)` link Telegram can download"],
            ["`type`", "string", "no", "`document` (default), `video`, `audio` or `photo`"],
            ["`caption`", "string", "no", "Caption shown with the file"],
        ]),
        ("code", "bash",
         "curl -X POST {BASE}/api/v1/links/single \\\n"
         "  -H \"Authorization: Bearer YOUR_API_KEY\" -H \"Content-Type: application/json\" \\\n"
         "  -d '{\"url\": \"https://example.com/clip.mp4\", \"type\": \"video\", \"caption\": \"My clip\"}'"),
        ("h3", "Mode 4 — upload a file"),
        ("p", "`multipart/form-data` with a `file` part, plus optional `type` and `caption` fields. "
              "If `type` is omitted it is guessed from the file extension (video / audio / otherwise document)."),
        ("code", "bash",
         "curl -X POST {BASE}/api/v1/links/single \\\n"
         "  -H \"Authorization: Bearer YOUR_API_KEY\" \\\n"
         "  -F \"file=@/path/to/movie.mp4\" -F \"caption=My movie\""),
        ("h3", "Response"),
        ("code", "json",
         '{\n  "ok": true,\n  "link": "https://t.me/YourBotUsername?start=Z2V0LTEyMzQ1Ng",\n'
         '  "message_id": 123,\n  "channel_id": -1001111111111,\n  "source": "reference"\n}'),
        ("p", "`source` is one of `reference`, `copy`, `url` or `file` — telling you which mode actually ran."),
    ]},
    {"id": "batch", "title": "POST /api/v1/links/batch", "blocks": [
        ("endpoint", "POST", "/api/v1/links/batch"),
        ("p", f"Creates **one link** that delivers several files (same as `/batch`), up to {API_MAX_BATCH}. Three input styles:"),
        ("h3", "Style 1 — `message_ids` shorthand (recommended when they're all from one chat)"),
        ("code", "json", '{ "source_chat_id": -1001234567890, "message_ids": [45, 46, 47, 48] }'),
        ("p", "Same auto-detection as the single-link endpoint: if `source_chat_id` is already a channel this bot "
              "stores in, this is **reference mode** — no copy, and the ids must be a contiguous run in that channel "
              "(exactly what you get if your other bot posted them back-to-back). Otherwise each message is copied "
              "into this bot's primary channel, same as Style 2."),
        ("note", "A batch link is fundamentally *one contiguous range in one channel* — that's how the link itself "
                 "is encoded. If your `message_ids` in a known channel aren't contiguous (something else was posted "
                 "in between), reference mode returns `400 not_contiguous`; use Style 2 (`items`) instead, which "
                 "copies your exact selection into a clean range."),
        ("h3", "Style 2 — `items` (mix sources freely; always copies)"),
        ("code", "bash",
         "curl -X POST {BASE}/api/v1/links/batch \\\n"
         "  -H \"Authorization: Bearer YOUR_API_KEY\" -H \"Content-Type: application/json\" \\\n"
         "  -d '{\"items\": [\n"
         "        {\"source_chat_id\": -1001234567890, \"message_id\": 45},\n"
         "        {\"source_chat_id\": -1009876543210, \"message_id\": 12},\n"
         "        {\"url\": \"https://example.com/extra.pdf\"}\n"
         "      ]}'"),
        ("h3", "Style 3 — upload several files"),
        ("code", "bash",
         "curl -X POST {BASE}/api/v1/links/batch \\\n"
         "  -H \"Authorization: Bearer YOUR_API_KEY\" \\\n"
         "  -F \"file=@ep1.mp4\" -F \"file=@ep2.mp4\" -F \"file=@ep3.mp4\""),
        ("h3", "Response"),
        ("code", "json",
         '{\n  "ok": true,\n  "link": "https://t.me/YourBotUsername?start=Z2V0LTEyMy00NTY",\n'
         '  "count": 3,\n  "first_message_id": 123,\n  "last_message_id": 125,\n'
         '  "message_ids": [123, 124, 125],\n  "skipped": [],\n  "source": "reference"\n}'),
        ("note", "In copy mode, if some items fail (for example a deleted source message) they're listed in "
                 "`skipped` with an `error` and `message`, and the link covers the rest. If **all** fail you get a "
                 "`502`. Reference mode has no partial failure — either the whole range is valid, or you get an error."),
    ]},
    {"id": "premium", "title": "Premium users", "blocks": [
        ("p", "Needs the `premium` scope. Premium users skip ads and the shortener. All dates are the bot server's local time; "
              "`expires_at_unix` is given as well so you never have to guess a timezone."),
        ("h3", "POST /api/v1/premium/add"),
        ("endpoint", "POST", "/api/v1/premium/add"),
        ("table", ["Field", "Type", "Required", "Description"], [
            ["`user_id`", "integer", "yes", "Telegram user id"],
            ["`days`", "integer", "no", f"1-3650. **Omit for permanent premium.**"],
            ["`mode`", "string", "no", "`extend` (default) adds `days` on top of the current plan; `replace` sets the plan to exactly `days` from now"],
            ["`notify`", "boolean", "no", "Send the user a message from this bot (default `false`). Never fails the request if they haven't started the bot"],
            ["`request_id`", "string", "no", "Your own unique id for this operation. Retrying with the same id is safe — it is applied only once"],
        ]),
        ("code", "bash",
         "curl -X POST {BASE}/api/v1/premium/add \\\n"
         "  -H \"Authorization: Bearer YOUR_API_KEY\" -H \"Content-Type: application/json\" \\\n"
         "  -d '{\"user_id\": 123456789, \"days\": 30, \"request_id\": \"order-8841\"}'"),
        ("code", "json",
         '{\n  "ok": true, "duplicate": false, "action": "activated",\n  "user_id": 123456789, "premium": true, "permanent": false,\n'
         '  "expires_at": "2026-10-30T12:00:00", "expires_at_unix": 1793361600, "days_left": 30,\n  "previous_expires_at": null\n}'),
        ("p", "`action` tells you what happened:"),
        ("table", ["action", "Meaning"], [
            ["`activated`", "The user wasn't premium (or it had expired) — now they are"],
            ["`extended`", "They were premium; `days` were added to the end of their current plan"],
            ["`replaced`", "`mode: replace` — the plan now ends exactly `days` from now"],
            ["`made_permanent`", "`days` was omitted and the user had a time-limited plan"],
            ["`unchanged`", "Nothing to do (for example: extending a plan that is already permanent)"],
        ]),
        ("note", "**Selling premium on another bot?** Call this from your payment-confirmation handler and always send a `request_id` "
                 "(your order or payment id). Payment providers retry webhooks, and without a `request_id` a retry would extend the plan twice. "
                 "With it, the repeat gets `\"duplicate\": true` and the plan is untouched."),
        ("h3", "POST /api/v1/premium/remove"),
        ("endpoint", "POST", "/api/v1/premium/remove"),
        ("p", "Body: `{ \"user_id\": 123456789, \"notify\": false }`. Safe to repeat — removing someone who isn't premium succeeds with `\"removed\": false`."),
        ("code", "json", '{ "ok": true, "removed": true, "was_active": true, "user_id": 123456789, "premium": false, "permanent": false,\n  "expires_at": null, "expires_at_unix": null, "days_left": null }'),
        ("h3", "GET /api/v1/premium/{user_id}"),
        ("endpoint", "GET", "/api/v1/premium/{user_id}"),
        ("p", "Current status of one user."),
        ("code", "json", '{ "ok": true, "user_id": 123456789, "premium": true, "permanent": false,\n  "expires_at": "2026-10-30T12:00:00", "expires_at_unix": 1793361600, "days_left": 29 }'),
        ("h3", "GET /api/v1/premium?limit=50&offset=0"),
        ("endpoint", "GET", "/api/v1/premium"),
        ("p", f"Active premium users, oldest id first. `limit` is 1-{MAX_PAGE_DOC}. `total` is the full count so you can page through."),
        ("code", "json", '{ "ok": true, "total": 2, "limit": 50, "offset": 0, "users": [\n  { "user_id": 111, "premium": true, "permanent": true, "expires_at": null, "expires_at_unix": null, "days_left": null },\n  { "user_id": 222, "premium": true, "permanent": false, "expires_at": "2026-10-30T12:00:00", "expires_at_unix": 1793361600, "days_left": 29 }\n] }'),
    ]},
    {"id": "users", "title": "Users & stats", "blocks": [
        ("p", "Needs the `users` scope."),
        ("h3", "GET /api/v1/users/{user_id}"),
        ("endpoint", "GET", "/api/v1/users/{user_id}"),
        ("code", "json", '{ "ok": true, "user_id": 123456789, "started_bot": true, "banned": false,\n  "premium": { "premium": false, "permanent": false, "expires_at": null, "expires_at_unix": null, "days_left": null } }'),
        ("h3", "POST /api/v1/users/ban  ·  POST /api/v1/users/unban"),
        ("endpoint", "POST", "/api/v1/users/ban"),
        ("p", "Body: `{ \"user_id\": 123456789 }`. Banning someone who has never started the bot works — the ban is already in place when they do. "
              "Admins and the owner can't be banned through the API (`400 protected_user`). Response: `{ \"ok\": true, \"user_id\": ..., \"banned\": true, \"changed\": true }` — `changed` is `false` if they were already in that state."),
        ("h3", "GET /api/v1/stats"),
        ("endpoint", "GET", "/api/v1/stats"),
        ("code", "json", '{ "ok": true, "users": 15230, "banned": 41, "premium_active": 312 }'),
    ]},
    {"id": "usage", "title": "GET /api/v1/usage", "blocks": [
        ("endpoint", "GET", "/api/v1/usage"),
        ("p", "Stats for the key you are calling with: links created, and how many times users finished the ads for links this key created."),
        ("code", "json",
         '{ "ok": true, "key_id": "a1b2c3d4", "label": "mybot1", "links_created": 42,\n'
         '  "ads_completed": 310, "scopes": ["links"], "created_at": "2026-09-28T09:00:00", "rate_limit_per_min": 60 }'),
    ]},
    {"id": "errors", "title": "Errors", "blocks": [
        ("p", "Every error is JSON: `{ \"ok\": false, \"error\": \"code\", \"message\": \"human readable\" }`."),
        ("table", ["HTTP", "error", "Meaning"], [
            ["401", "`missing_api_key` / `invalid_api_key`", "No key sent, or the key is wrong or revoked"],
            ["403", "`insufficient_scope`", "The key lacks the scope this endpoint needs — see Permissions"],
            ["400", "`protected_user`", "Tried to ban an admin or the owner"],
            ["429", "`rate_limited`", "Too many requests — wait `Retry-After` seconds"],
            ["429", "`telegram_flood_wait`", "Telegram asked the bot to slow down — retry later"],
            ["400", "`invalid_json` / `invalid_request`", "Body could not be parsed or fields are wrong"],
            ["400", "`too_many_items` / `too_many_files`", f"More than {API_MAX_BATCH} in one batch"],
            ["400", "`empty_file`", "Uploaded file has 0 bytes"],
            ["404", "`message_not_found`", "Reference mode: that message id doesn't exist in the given channel"],
            ["400", "`not_contiguous` (single-request)", "Reference-mode batch: the given ids aren't a contiguous run in that channel — use `items` instead"],
            ["413", "`file_too_large`", f"Upload is over {API_MAX_UPLOAD_MB} MB"],
            ["502", "`source_unreachable`", "Could not copy the message, or read the given chat — add this bot to that chat, check ids"],
            ["502", "`store_failed`", "Telegram rejected the url/file"],
            ["502", "`batch_empty`", "Nothing in the batch could be stored (see `skipped`)"],
            ["409", "`not_contiguous` (retry)", "Storage channel was busy while copying a batch — just retry"],
            ["503", "`api_disabled` / `server_starting`", "API is switched off or the bot is still booting"],
        ]),
    ]},
    {"id": "examples", "title": "Code examples", "blocks": [
        ("h3", "Python (requests)"),
        ("code", "python",
         "import requests\n\n"
         "BASE = \"{BASE}\"\n"
         "HEADERS = {\"Authorization\": \"Bearer YOUR_API_KEY\"}\n\n"
         "def monetized_link(chat_id, message_id):\n"
         "    r = requests.post(BASE + \"/api/v1/links/single\", headers=HEADERS, timeout=60,\n"
         "                      json={\"source_chat_id\": chat_id, \"message_id\": message_id})\n"
         "    data = r.json()\n"
         "    if not data.get(\"ok\"):\n"
         "        raise RuntimeError(data.get(\"message\"))\n"
         "    return data[\"link\"]\n\n"
         "print(monetized_link(-1001234567890, 45))"),
        ("h3", "Node.js (fetch)"),
        ("code", "javascript",
         "const res = await fetch(\"{BASE}/api/v1/links/batch\", {\n"
         "  method: \"POST\",\n"
         "  headers: { Authorization: \"Bearer YOUR_API_KEY\", \"Content-Type\": \"application/json\" },\n"
         "  body: JSON.stringify({ source_chat_id: -1001234567890, message_ids: [45, 46, 47] }),\n"
         "});\n"
         "const data = await res.json();\n"
         "console.log(data.link);"),
        ("p", "A ready-made async + sync client is included as `examples/monetize_client.py` — copy that one file into each of your bots."),
    ]},
    {"id": "guide", "title": "Guide: monetizing your other bots", "blocks": [
        ("h3", "Pick how each bot hands over its content"),
        ("ul", [
            "**Your bot already posts into this bot's storage channel** (it's an admin there too) → reference mode. "
            "Capture the message id it gets back right after posting, call the API with that id, done. No copy, no "
            "download, no duplicate file sitting in the channel — just a link.",
            "**Your bot stores files in some other channel of its own** → add *this* bot to that channel too, then "
            "call the same endpoint the same way — it copies once, automatically (Mode 2).",
            "**Your bot has files on disk or in memory, nowhere on Telegram yet** → use the upload mode. (Telegram "
            "`file_id`s only work inside the bot that owns them, so they can't be passed across bots.)",
            "**Your bot only knows a download URL** → use `url` mode (small files) or download and upload.",
            "**Series / packs / albums** → use the batch endpoint and give users the one batch link.",
        ]),
        ("h3", "Selling premium on another bot"),
        ("p", "Create a key with `/newapikey shopbot links,premium`. When a payment is confirmed on that bot, call "
              "`POST /api/v1/premium/add` with the buyer's user id, the plan length in `days`, and the payment/order id as `request_id`. "
              "Do the reverse (`/premium/remove`) when a plan is refunded."),
        ("h3", "Change one line in each bot"),
        ("p", "Wherever the bot currently sends a file to a user, instead call the API (once per file) and send the returned link. "
              "Store `file → link` in that bot's own database so the same file is only converted once."),
        ("h3", "One key per bot"),
        ("p", "Run `/newapikey botname` for each bot. `/apikeys` then shows, per key, how many links it created and how many ad-unlocks they produced — "
              "so you can see which bots actually earn and which are worth promoting."),
        ("h3", "Good habits"),
        ("ul", [
            "Handle `429` by waiting `Retry-After` seconds, then retrying.",
            "Create links **when a file is added or first requested**, not on every user click.",
            "Call the API from your server only; keep keys in environment variables.",
            "Revoke a key immediately if it leaks — links already created keep working.",
            "A key can copy from **any chat this bot can read**, so only give keys to bots you own.",
            "Only monetize content you own or are licensed to share, and check that it fits Telegram's terms and your ad networks' content policies. Networks such as Monetag and Adsterra restrict some content categories.",
        ]),
    ]},
    {"id": "troubleshooting", "title": "Troubleshooting", "blocks": [
        ("table", ["Symptom", "Likely cause / fix"], [
            ["`401 invalid_api_key`", "Wrong key, extra spaces, or the key was revoked. Create a new one with `/newapikey`."],
            ["`404 message_not_found`", "Reference mode: the message id doesn't exist in that channel (deleted, wrong id, or wrong chat)."],
            ["`502 source_unreachable`", "This bot isn't in the source channel (copy mode), or can't read the given chat at all. Add the bot and re-check ids."],
            ["Link opens but says invalid / expired", "The link was made by a different bot deployment or the storage channel changed. Recreate the link."],
            ["Users don't see ads", "`WEBAPP_URL` must be your real public HTTPS URL, ads must be enabled (`/adsenable`) and zones set (`/adssettings`)."],
            ["`429 rate_limited` in bulk jobs", f"Limit is {API_RATE_LIMIT_PER_MIN}/min per key. Batch files together, or space requests out."],
        ]),
    ]},
]


def _inline(text: str) -> str:
    """Tiny inline formatter for the docs HTML: escape, then `code` and **bold**."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)


def _sub(text: str, base: str) -> str:
    return text.replace("{BASE}", base)


def render_api_docs_markdown(base_url: str) -> str:
    base = base_url.rstrip("/")
    out = ["# Link Generation API", "",
           f"Base URL: `{base}`  ·  Auth: `Authorization: Bearer <API_KEY>`", ""]
    for section in SECTIONS:
        out += [f"## {section['title']}", ""]
        for block in section["blocks"]:
            kind = block[0]
            if kind == "p":
                out += [_sub(block[1], base), ""]
            elif kind == "h3":
                out += [f"### {block[1]}", ""]
            elif kind == "ul":
                out += [f"- {_sub(item, base)}" for item in block[1]] + [""]
            elif kind == "note":
                out += [f"> {_sub(block[1], base)}", ""]
            elif kind == "code":
                out += [f"```{block[1]}", _sub(block[2], base), "```", ""]
            elif kind == "endpoint":
                out += [f"**`{block[1]} {block[2]}`**", ""]
            elif kind == "table":
                out += ["| " + " | ".join(block[1]) + " |", "|" + "---|" * len(block[1])]
                out += ["| " + " | ".join(_sub(c, base) for c in row) + " |" for row in block[2]] + [""]
    return "\n".join(out)


def render_api_docs_page(base_url: str, theme_key: str = "violet") -> str:
    base = base_url.rstrip("/")
    nav = "".join(f'<a href="#{s["id"]}">{html.escape(s["title"].split(" (")[0])}</a>' for s in SECTIONS)
    body = []
    for section in SECTIONS:
        body.append(f'<section id="{section["id"]}"><h2>{html.escape(section["title"])}</h2>')
        for block in section["blocks"]:
            kind = block[0]
            if kind == "p":
                body.append(f"<p>{_inline(_sub(block[1], base))}</p>")
            elif kind == "h3":
                body.append(f"<h3>{_inline(block[1])}</h3>")
            elif kind == "ul":
                body.append("<ul>" + "".join(f"<li>{_inline(_sub(i, base))}</li>" for i in block[1]) + "</ul>")
            elif kind == "note":
                body.append(f'<div class="note">{_inline(_sub(block[1], base))}</div>')
            elif kind == "code":
                body.append(f'<div class="codewrap"><button class="copy" type="button">Copy</button>'
                            f"<pre><code>{html.escape(_sub(block[2], base))}</code></pre></div>")
            elif kind == "endpoint":
                body.append(f'<div class="endpoint"><span class="m {block[1].lower()}">{block[1]}</span>'
                            f"<code>{html.escape(block[2])}</code></div>")
            elif kind == "table":
                head = "".join(f"<th>{html.escape(h)}</th>" for h in block[1])
                rows = "".join("<tr>" + "".join(f"<td>{_inline(_sub(c, base))}</td>" for c in row) + "</tr>" for row in block[2])
                body.append(f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
        body.append("</section>")

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link Generation API</title>
<style>{base_style(theme_key)}
.page{{max-width:860px;margin:0 auto;padding:22px 16px 60px}}
header.top h1{{margin:0 0 6px;font-size:clamp(24px,5vw,34px);letter-spacing:-.02em}}
header.top p{{margin:0;color:var(--muted);font-size:14px}}
header.top code{{background:var(--card);padding:2px 7px;border-radius:6px;border:1px solid var(--border)}}
nav{{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;padding:12px 0;margin:14px 0 8px;
background:linear-gradient(var(--bg) 70%,transparent);scrollbar-width:none}}
nav a{{flex:none;text-decoration:none;font-size:12.5px;font-weight:600;color:var(--muted);background:var(--card);
border:1px solid var(--border);padding:6px 12px;border-radius:999px}}
nav a:hover{{color:var(--text)}}
section{{margin-top:34px;scroll-margin-top:64px}}
h2{{font-size:22px;margin:0 0 12px;letter-spacing:-.01em}}
h3{{font-size:16px;margin:22px 0 8px}}
p,li{{color:#c9cde6;line-height:1.65;font-size:14.5px}}
ul{{padding-left:20px}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}}
p code,li code,td code{{background:var(--card);border:1px solid var(--border);padding:1px 6px;border-radius:6px}}
.codewrap{{position:relative;margin:12px 0}}
pre{{margin:0;background:#0a0b12;border:1px solid var(--border);border-radius:12px;padding:14px 16px;overflow-x:auto;font-size:12.5px;line-height:1.55}}
.copy{{position:absolute;top:8px;right:8px;border:1px solid var(--border);background:var(--card2);color:var(--muted);
font-size:11px;padding:4px 9px;border-radius:8px;cursor:pointer}}
.note{{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--accent1);border-radius:10px;
padding:11px 14px;margin:12px 0;font-size:13.5px;color:#c9cde6;line-height:1.6}}
.endpoint{{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--border);
border-radius:12px;padding:10px 14px;margin:8px 0 12px;overflow-x:auto}}
.m{{font-size:11px;font-weight:800;letter-spacing:.05em;padding:4px 9px;border-radius:7px;color:#fff;
background:linear-gradient(90deg,var(--accent1),var(--accent2))}}
.tablewrap{{overflow-x:auto;margin:12px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:top;color:#c9cde6}}
th{{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.05em}}
</style></head><body><div class="page">
<header class="top"><h1>Link Generation API</h1>
<p>Base URL <code>{html.escape(base)}</code> · Auth <code>Authorization: Bearer &lt;API_KEY&gt;</code> ·
<a href="/api/docs.md">Markdown version</a></p></header>
<nav>{nav}</nav>
{''.join(body)}
</div>
<script>
document.querySelectorAll('.copy').forEach(function(b){{
  b.addEventListener('click', function(){{
    var t = b.parentElement.querySelector('code').innerText;
    (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function(){{
      b.textContent = 'Copied'; setTimeout(function(){{ b.textContent = 'Copy'; }}, 1400);
    }}).catch(function(){{ b.textContent = 'Press Ctrl+C'; }});
  }});
}});
</script></body></html>"""
