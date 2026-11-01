"""Pure HTML builders for the aiohttp web layer.

Kept free of Telegram/DB imports on purpose: route.py fetches the data,
these functions only turn it into HTML strings. All CSS/JS is inlined (no
external stylesheets/fonts/frameworks) so both pages render on the first
response with no extra round trips.
"""

import html
import json
import re

from config import AD_FAIL_OPEN_AFTER, BANNER_MIN_HEIGHT, CONTACT_USERNAME, MONETAG_SDK_SRC

# Ad-step metadata: how each show_ZONE() call is invoked, per Monetag's
# documented TMA SDK behaviour (default call for Rewarded/In-App
# Interstitial, the 'pop' argument for Rewarded Popup).
STEP_CALL_ARG = {
    "inapp_interstitial": None,
    "interstitial": None,
    "rewarded_interstitial": None,
    "rewarded_popup": "pop",
}
# Catchy, position-based labels shown to the user — deliberately generic
# ("Quick Ad", "Almost there!") rather than naming the ad format, since that
# reads better than "Rewarded Popup ad" in a consumer-facing flow.
CATCHY_STEP_TITLES = ["🎬 Quick Ad", "🎁 Almost There!", "✨ One More!", "🔓 Final Ad"]

# --- Color templates -------------------------------------------------
# Same markup/CSS structure everywhere; only these variables change, so
# adding a 4th theme later is a one-line addition, not a new template file.
THEMES = {
    "violet": {
        "name": "Violet (default)",
        "bg": "#0b0c14", "bg2": "#14101f", "card": "#161a2b", "card2": "#1c2036",
        "accent1": "#7c6cff", "accent2": "#a78bff", "good": "#3ddc97",
        "glow": "#2a2456", "shadow": "rgba(124,108,255,.35)", "border": "rgba(167,139,255,.16)",
    },
    "emerald": {
        "name": "Emerald",
        "bg": "#07110d", "bg2": "#0a1a15", "card": "#0f1f1a", "card2": "#132922",
        "accent1": "#16c98a", "accent2": "#5eead4", "good": "#5eead4",
        "glow": "#12352a", "shadow": "rgba(22,201,138,.35)", "border": "rgba(94,234,212,.16)",
    },
    "sunset": {
        "name": "Sunset",
        "bg": "#150a08", "bg2": "#1f0f0a", "card": "#231311", "card2": "#2c1815",
        "accent1": "#ff5f3d", "accent2": "#ffb15c", "good": "#ffd166",
        "glow": "#42200f", "shadow": "rgba(255,95,61,.35)", "border": "rgba(255,177,92,.16)",
    },
}
DEFAULT_THEME = "violet"


def _theme(theme_key: str) -> dict:
    return THEMES.get(theme_key, THEMES[DEFAULT_THEME])


def base_style(theme_key: str) -> str:
    t = _theme(theme_key)
    return f"""
:root{{--bg:{t['bg']};--bg2:{t['bg2']};--card:{t['card']};--card2:{t['card2']};
--accent1:{t['accent1']};--accent2:{t['accent2']};--text:#f3f4fb;--muted:#9298b8;
--good:{t['good']};--shadow:{t['shadow']};--border:{t['border']};--radius:18px}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--text);min-height:100vh;-webkit-font-smoothing:antialiased;
background-color:var(--bg);
background-image:radial-gradient(720px 420px at 15% -8%,{t['glow']} 0%,transparent 60%),
radial-gradient(600px 380px at 105% 10%,var(--bg2) 0%,transparent 55%),
radial-gradient(900px 500px at 50% 115%,var(--bg2) 0%,transparent 60%)}}
a{{color:inherit}}
::selection{{background:var(--accent1);color:#fff}}
@keyframes riseIn{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:translateY(0)}}}}
@keyframes pulseDot{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}
@keyframes sheen{{0%,55%{{transform:translateX(-100%)}}100%{{transform:translateX(100%)}}}}
@keyframes popIn{{0%{{transform:scale(.4);opacity:0}}70%{{transform:scale(1.15)}}100%{{transform:scale(1);opacity:1}}}}
@media (prefers-reduced-motion:reduce){{*,*::before,*::after{{animation:none!important;transition:none!important}}}}
"""


def _preconnect_hints(native_banner_html: str) -> str:
    """Warm up DNS+TLS for every origin the page is about to hit, so the
    first ad request doesn't pay that latency (fewer users give up before an
    ad finishes loading = more completed, viewable impressions)."""
    hosts = [MONETAG_SDK_SRC.split("//", 1)[-1].split("/", 1)[0], "telegram.org"]
    for src in re.findall(r'src=["\']([^"\']+)["\']', native_banner_html or ""):
        m = re.match(r'^(?:https?:)?//([^/]+)', src)
        if m:
            hosts.append(m.group(1))
    return "\n".join(f'<link rel="preconnect" href="https://{h}" crossorigin>' for h in dict.fromkeys(hosts))


def _native_banner_html(raw_snippet: str, min_height: int) -> str:
    """Third-party native banner (Adsterra etc.) inside a sandboxed iframe, so
    whatever CSS/markup the network injects can't touch our layout.

    Why it used to look small: the iframe document centred its content with
    flexbox, which shrinks the ad's container to its own content width — the
    ad then sized itself against that tiny box. Here the body is a plain block
    so the ad container gets the frame's full width, and the frame reports
    its real content height back (ads load asynchronously) so the page can
    resize it to fit. The reserved height is `min_height` (admin-tunable)."""
    if not raw_snippet:
        return ""
    inner = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="color-scheme" content="dark"><base target="_blank"><style>
html,body{{margin:0;padding:0;background:transparent;width:100%}}
body{{display:block;overflow-x:hidden;font-family:-apple-system,Segoe UI,Roboto,sans-serif}}
body>*{{max-width:100%}}
body>div,[id^="container-"]{{width:100%!important}}
img,iframe{{max-width:100%}}
</style></head><body>{raw_snippet}
<script>
(function () {{
  var last = -1;
  function size() {{
    var b = document.body;
    return Math.ceil(Math.max(b.scrollHeight, b.getBoundingClientRect().height));
  }}
  function report() {{
    var v = size();
    if (v === last) return;
    last = v;
    try {{ parent.postMessage({{__nativeBannerHeight: v}}, '*'); }} catch (e) {{}}
  }}
  if (window.ResizeObserver) new ResizeObserver(report).observe(document.body);
  window.addEventListener('load', report);
  // ad scripts often inject their markup a while after load
  [200, 600, 1200, 2500, 5000].forEach(function (ms) {{ setTimeout(report, ms); }});
}})();
</script>
</body></html>"""
    escaped = html.escape(inner, quote=True)
    return (
        f'<div class="banner-slot loading" id="banner-slot"><iframe id="native-banner-frame" class="banner-frame" '
        f'style="height:{int(min_height)}px" srcdoc="{escaped}" title="Advertisement" '
        f'sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox allow-same-origin" '
        f'scrolling="no"></iframe></div>'
    )


def render_error_page(title: str, message: str, theme_key: str = DEFAULT_THEME) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title><style>{base_style(theme_key)}
.wrap{{display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px;text-align:center}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:36px 26px;
max-width:380px;animation:riseIn .5s ease both;box-shadow:0 20px 50px rgba(0,0,0,.35)}}
h1{{font-size:21px;margin:0 0 10px;letter-spacing:-.02em}} p{{color:var(--muted);font-size:14px;line-height:1.6;margin:0}}
</style></head><body><div class="wrap"><div class="card"><h1>{title}</h1><p>{message}</p></div></div></body></html>"""


def _js(value) -> str:
    """json.dumps that is safe to drop inside an inline <script> block."""
    return json.dumps(value).replace("</", "<\\/")


_UNLOCK_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="__BG_RAW__">
<title>File Verification</title>
__PRECONNECT__
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>__STYLE__
.wrap{max-width:460px;margin:0 auto;padding:16px 14px calc(32px + env(safe-area-inset-bottom))}

/* TOP: native banner. The ad SDKs are NOT in <head> — they load after first paint. */
.banner-slot{position:relative;border-radius:14px;overflow:hidden;background:var(--card2);border:1px solid var(--border);
margin-bottom:16px;animation:riseIn .45s ease both}
.banner-slot.loading::after{content:"";position:absolute;inset:0;pointer-events:none;
background:linear-gradient(100deg,transparent 30%,rgba(255,255,255,.06) 50%,transparent 70%);
transform:translateX(-100%);animation:sheen 1.6s linear infinite}
.banner-slot.empty{display:none}
.banner-frame{display:block;width:100%;border:0;background:transparent}

/* MIDDLE: verification */
.verify-card{background:linear-gradient(180deg,var(--card2),var(--card));border:1px solid var(--border);
border-radius:var(--radius);padding:24px 20px 22px;box-shadow:0 14px 34px rgba(0,0,0,.3);animation:riseIn .5s ease .05s both}
.verify-card h2{margin:0 0 4px;font-size:20px;font-weight:700;letter-spacing:-.01em}
.verify-card .sub{color:var(--muted);font-size:13px;margin:0 0 20px}
.progress{height:8px;border-radius:99px;background:rgba(255,255,255,.06);overflow:hidden;margin-bottom:22px}
.progress-bar{height:100%;width:0%;border-radius:99px;background:linear-gradient(90deg,var(--accent1),var(--accent2));
transition:width .35s cubic-bezier(.34,1.3,.64,1)}
ul.steps{list-style:none;margin:0 0 22px;padding:0;display:flex;flex-direction:column;gap:9px}
.step{display:flex;align-items:center;gap:11px;padding:12px 13px;border-radius:13px;background:rgba(255,255,255,.025);
border:1px solid transparent;color:var(--muted);font-size:14px;font-weight:500;
transition:background .2s ease,border-color .2s ease,color .2s ease}
.step.active{background:rgba(255,255,255,.05);border-color:var(--border);color:var(--text)}
.step.done{color:var(--good)}
.step .num{width:26px;height:26px;border-radius:50%;background:rgba(255,255,255,.08);display:flex;align-items:center;
justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;transition:background .2s ease}
.step.active .num{background:linear-gradient(135deg,var(--accent1),var(--accent2));color:#fff;box-shadow:0 0 0 4px var(--shadow)}
.step.done .num{background:var(--good);color:#06231a}
.step .check{margin-left:auto;opacity:0;color:var(--good);font-weight:700}
.step.done .check{opacity:1;animation:popIn .3s ease}
button.cta{position:relative;overflow:hidden;width:100%;border:0;border-radius:14px;padding:16px;font-size:15.5px;
font-weight:700;letter-spacing:.01em;background:linear-gradient(90deg,var(--accent1),var(--accent2));color:#fff;
cursor:pointer;box-shadow:0 10px 24px var(--shadow);touch-action:manipulation;user-select:none;
-webkit-tap-highlight-color:transparent;transition:transform .12s ease,opacity .2s ease}
button.cta::after{content:"";position:absolute;inset:0;pointer-events:none;
background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.22) 50%,transparent 70%);
transform:translateX(-100%);animation:sheen 3.4s ease-in-out infinite}
button.cta:active{transform:scale(.98)}
button.cta:disabled{opacity:.5;cursor:default;box-shadow:none}
button.cta:disabled::after{display:none}
.status{margin:14px 0 0;text-align:center;font-size:12.5px;color:var(--muted);min-height:18px;line-height:1.5}
.card-foot{margin-top:18px;padding-top:14px;border-top:1px solid var(--border);display:flex;justify-content:space-between;
align-items:center;font-size:11px;color:var(--muted)}
.card-foot .secure{display:flex;align-items:center;gap:5px}
.card-foot .dot{width:5px;height:5px;border-radius:50%;background:var(--good);animation:pulseDot 1.8s ease-in-out infinite}
.verify-card.verified{box-shadow:0 0 0 1px var(--good),0 14px 34px var(--shadow)}

/* BOTTOM: credits & others */
.credits{margin-top:22px;text-align:center}
.perks{display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.perks span{font-size:11px;font-weight:600;color:var(--muted);background:rgba(255,255,255,.05);
border:1px solid var(--border);padding:5px 10px;border-radius:999px}
.credit-links{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.credit-links a{text-decoration:none;font-size:12.5px;font-weight:600;color:var(--text);background:var(--card);
border:1px solid var(--border);padding:9px 14px;border-radius:12px}
.fine{margin:0;font-size:11.5px;color:var(--muted);line-height:1.7}
.fine a{color:var(--accent2);text-decoration:none}
</style></head>
<body><div class="wrap">
  __BANNER__
  <main class="verify-card" id="verify-card">
    <h2>File Verification</h2>
    <p class="sub">Complete the quick steps below to unlock your file.</p>
    <div class="progress"><div class="progress-bar" id="progress"></div></div>
    <ul class="steps" id="steps">
      __STEP_ITEMS__
    </ul>
    <button class="cta" id="action-btn" type="button">Watch Ad &amp; Continue</button>
    <p class="status" id="status" aria-live="polite">Step 1 ready.</p>
    <div class="card-foot">
      <span id="left">Step 1 of __TOTAL__</span>
      <span class="secure"><span class="dot"></span> Protected &amp; encrypted</span>
    </div>
  </main>
  <footer class="credits">
    <div class="perks"><span>⚡ Instant</span><span>🔒 Secure</span><span>🎁 100% Free</span></div>
    <div class="credit-links">__CREDIT_LINKS__</div>
    <p class="fine">__POWERED_BY__ Ads keep this service free.</p>
  </footer>
</div>
<script>
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) {
  tg.ready(); tg.expand();
  try { tg.setHeaderColor(__BG_JS__); tg.setBackgroundColor(__BG_JS__); } catch (e) {}
}
const initData = () => (tg && tg.initData) || '';

// t.me links go through Telegram's own handler so they never replace this page.
document.querySelectorAll('a[data-tg]').forEach(function (a) {
  a.addEventListener('click', function (ev) {
    if (tg && tg.openTelegramLink) { ev.preventDefault(); tg.openTelegramLink(a.href); }
  });
});

// ---- native banner: sized by the ad itself (see _native_banner_html) ----
const BANNER_MIN = __BANNER_MIN__;
const bannerSlot = document.getElementById('banner-slot');
const bannerFrame = document.getElementById('native-banner-frame');
let bannerSeen = false;
if (bannerFrame) {
  window.addEventListener('message', function (e) {
    if (e.source !== bannerFrame.contentWindow) return;       // only trust our own banner frame
    const h = e.data && e.data.__nativeBannerHeight;
    if (typeof h !== 'number' || h < 40) return;              // nothing rendered (yet)
    bannerSeen = true;
    bannerSlot.classList.remove('loading', 'empty');
    bannerFrame.style.height = Math.min(Math.max(h + 6, BANNER_MIN), 800) + 'px';
  });
  // If no ad ever shows up (blocked / no fill), hide the empty box instead of leaving a grey hole.
  setTimeout(function () { if (!bannerSeen) bannerSlot.classList.add('empty'); }, 7000);
}

const TOKEN = __TOKEN_JS__;
const STEPS = __STEPS_JS__;
const ZONES = __ZONES_JS__;
const CALL_ARGS = __CALL_ARGS_JS__;
const SDK_SRC = __SDK_JS__;
const FAIL_OPEN_AFTER = __FAIL_OPEN__;

// ---- ad SDKs: injected after first paint (never block rendering) ----
const sdk = {};
function loadSdk(zone) {
  if (!zone) return Promise.resolve(false);
  if (!sdk[zone]) {
    sdk[zone] = new Promise(function (resolve) {
      const s = document.createElement('script');
      s.src = SDK_SRC;
      s.async = true;
      s.dataset.zone = zone;
      s.dataset.sdk = 'show_' + zone;
      s.onload = function () { resolve(true); };
      s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
  }
  return sdk[zone];
}
// Start now so every SDK is ready by the time the first button is tapped.
Array.from(new Set(STEPS.map(function (s) { return ZONES[s]; }))).forEach(loadSdk);

async function getShowFn(zone) {
  const loaded = await loadSdk(zone);
  const name = 'show_' + zone;
  // some SDK builds define the function slightly after the script's load event
  for (let i = 0; i < 20 && typeof window[name] !== 'function'; i++) {
    if (!loaded && i > 2) break;
    await new Promise(function (r) { setTimeout(r, 150); });
  }
  return typeof window[name] === 'function' ? window[name] : null;
}

function withTimeout(promise, ms) {
  return new Promise(function (resolve, reject) {
    const t = setTimeout(function () { reject(new Error('ad_timeout')); }, ms);
    promise.then(function (v) { clearTimeout(t); resolve(v); }, function (e) { clearTimeout(t); reject(e); });
  });
}

// One ad call, with a single quick retry. `ymid` ties the step to Monetag's
// server-side postback; `requestVar` shows up as "source" in their reports.
async function fireAd(step, allowRetry) {
  const showFn = await getShowFn(ZONES[step]);
  if (!showFn) throw new Error('sdk_unavailable');
  const popType = CALL_ARGS[step];
  const opts = Object.assign({ ymid: TOKEN + ':' + step, requestVar: step }, popType ? { type: popType } : {});
  const call = function () {
    return withTimeout(Promise.resolve().then(function () { return showFn(opts); }), 90000);
  };
  try {
    await call();
  } catch (e) {
    if (!allowRetry) throw e;     // only the first failure is retried silently; later ones are the user's Retry taps
    await new Promise(function (r) { setTimeout(r, 700); });
    await call();
  }
}

// ---- state machine: phase 'ads' -> 'verify' -> 'done' (or 'closed') ----
let cursor = 0;
let phase = 'ads';
let busy = false;
const acked = new Set();     // steps the server has confirmed
const shownMap = {};         // step -> false when it was finished without a real ad
const failCount = {};
const inflight = [];

const card = document.getElementById('verify-card');
const btn = document.getElementById('action-btn');
const statusEl = document.getElementById('status');
const leftEl = document.getElementById('left');
const progressEl = document.getElementById('progress');

function setBtn(label, disabled) { btn.textContent = label; btn.disabled = !!disabled; }
function setStatus(text) { statusEl.textContent = text; }

function setProgress() {
  const total = STEPS.length + 1;                       // every ad + the final verify
  const doneUnits = cursor + (phase === 'done' ? 1 : 0);
  progressEl.style.width = Math.round((doneUnits / total) * 100) + '%';
  leftEl.textContent = phase === 'done' ? 'Verified' :
    phase === 'verify' ? 'Ready to verify' : 'Step ' + (cursor + 1) + ' of ' + STEPS.length;
}

function markDone(i) {
  const el = document.getElementById('step-' + i);
  el.classList.remove('active');
  el.classList.add('done');
  const next = document.getElementById('step-' + (i + 1));
  if (next) next.classList.add('active');
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    const err = new Error(data.error || 'request_failed');
    err.code = data.error;
    throw err;
  }
  return data;
}

function postStep(step) {
  return postJSON('/api/unlock/' + TOKEN + '/step',
    { step: step, ad_shown: shownMap[step] !== false, init_data: initData() })
    .then(function () { acked.add(step); });
}

function handleError(e) {
  const code = e && e.code;
  if (code === 'auth_failed') {
    phase = 'closed'; setBtn('Close', false);
    return setStatus('Please open this page from inside Telegram, using the button in the bot.');
  }
  if (code === 'session_invalid' || code === 'already_processed') {
    phase = 'closed'; setBtn('Close', false);
    return setStatus('This link expired or was already used. Check your chat, or open the file link again.');
  }
  if (code === 'too_fast') {
    setBtn('✅ Verify & Unlock', false);
    return setStatus('Almost there — wait a couple of seconds, then tap Verify again.');
  }
  if (code === 'delivery_failed') {
    setBtn('Try again', false);
    return setStatus("Couldn't send your file just now. Tap to try again.");
  }
  setBtn('Try again', false);
  setStatus('Verification failed — please try again.');
}

async function runStep() {
  const step = STEPS[cursor];
  setBtn('Loading ad…', true);
  setStatus('Loading ad…');
  try {
    await fireAd(step, !failCount[step]);
  } catch (e) {
    failCount[step] = (failCount[step] || 0) + 1;
    if (FAIL_OPEN_AFTER > 0 && failCount[step] >= FAIL_OPEN_AFTER) {
      shownMap[step] = false;     // don't trap the user behind an ad that keeps failing to load
    } else {
      setBtn('Retry', false);
      setStatus('Ad failed to load — tap to retry' +
        (FAIL_OPEN_AFTER > 0 ? ' (' + failCount[step] + '/' + FAIL_OPEN_AFTER + ').' : '.'));
      return;
    }
  }
  // Update the screen immediately and tell the server in the background —
  // finish() re-sends anything that didn't land, so nothing is lost.
  markDone(cursor);
  inflight.push(postStep(step).catch(function () {}));
  cursor += 1;
  if (cursor >= STEPS.length) {
    phase = 'verify';
    setBtn('✅ Verify & Unlock', false);
    setStatus('All done — tap to verify and get your file.');
  } else {
    setBtn('Watch Ad & Continue', false);
    setStatus('Step ' + (cursor + 1) + ' ready.');
  }
  setProgress();
}

async function finish() {
  setBtn('Verifying…', true);
  setStatus('Verifying…');
  try {
    await Promise.all(inflight);
    for (const step of STEPS) { if (!acked.has(step)) await postStep(step); }
    await postJSON('/api/unlock/' + TOKEN + '/complete', { init_data: initData() });
  } catch (e) {
    return handleError(e);
  }
  phase = 'done';
  const last = document.getElementById('step-' + STEPS.length);
  last.classList.remove('active');
  last.classList.add('done');
  card.classList.add('verified');
  setProgress();
  setBtn('Verified ✓', true);
  setStatus('✅ Verified! Sending your file to the chat…');
  // The server pushes the file into the chat itself; this page just closes.
  setTimeout(function () { if (tg && tg.close) tg.close(); }, 1200);
}

btn.addEventListener('click', async function () {
  if (busy) return;
  busy = true;
  try {
    if (phase === 'ads') await runStep();
    else if (phase === 'verify') await finish();
    else if (phase === 'closed' && tg && tg.close) tg.close();
  } finally {
    busy = false;
  }
});
setProgress();
</script>
</body></html>"""


def render_unlock_page(token: str, steps: list, zones: dict, bot_username: str,
                       theme_key: str = DEFAULT_THEME, banner_min_height: int = BANNER_MIN_HEIGHT) -> str:
    """Watch page: native banner (top) · verification (middle) · credits (bottom)."""
    native_banner_raw = zones.get("native_banner", "")
    banner_min_height = max(120, min(int(banner_min_height or BANNER_MIN_HEIGHT), 700))

    rows = [
        f'<li id="step-{i}" class="step{" active" if i == 0 else ""}">'
        f'<span class="num">{i + 1}</span><span class="label">{CATCHY_STEP_TITLES[i % len(CATCHY_STEP_TITLES)]}</span>'
        f'<span class="check">✓</span></li>'
        for i in range(len(steps))
    ]
    rows.append(  # the final row: unlocking the file itself
        f'<li id="step-{len(steps)}" class="step"><span class="num">{len(steps) + 1}</span>'
        f'<span class="label">🔓 Unlock your file</span><span class="check">✓</span></li>'
    )

    bot = html.escape(bot_username or "")
    contact = html.escape(CONTACT_USERNAME)
    credit_links = (
        f'<a data-tg href="https://t.me/{contact}" rel="noopener">💼 Buy This Bot</a>'
        f'<a data-tg href="https://t.me/{contact}" rel="noopener">🛠️ Hire Me</a>'
        + (f'<a data-tg href="https://t.me/{bot}" rel="noopener">🤖 @{bot}</a>' if bot else "")
    )
    powered_by = f'Powered by <a data-tg href="https://t.me/{bot}" rel="noopener">@{bot}</a>.' if bot else ""
    bg = _theme(theme_key)["bg"]

    page = (
        _UNLOCK_TEMPLATE
        .replace("__STYLE__", base_style(theme_key))
        .replace("__PRECONNECT__", _preconnect_hints(native_banner_raw))
        .replace("__STEP_ITEMS__", "\n      ".join(rows))
        .replace("__TOTAL__", str(len(steps)))
        .replace("__CREDIT_LINKS__", credit_links)
        .replace("__POWERED_BY__", powered_by)
        .replace("__BG_RAW__", bg)
        .replace("__BG_JS__", _js(bg))
        .replace("__TOKEN_JS__", _js(token))
        .replace("__STEPS_JS__", _js(steps))
        .replace("__ZONES_JS__", _js({s: zones.get(s, "") for s in steps}))
        .replace("__CALL_ARGS_JS__", _js({s: STEP_CALL_ARG.get(s) for s in steps}))
        .replace("__SDK_JS__", _js(MONETAG_SDK_SRC))
        .replace("__FAIL_OPEN__", str(int(AD_FAIL_OPEN_AFTER)))
        .replace("__BANNER_MIN__", str(banner_min_height))
    )
    # Inserted last so third-party ad code can never collide with a placeholder.
    return page.replace("__BANNER__", _native_banner_html(native_banner_raw, banner_min_height))


def render_home_page(bot_username: str, theme_key: str = DEFAULT_THEME) -> str:
    add_link = f"https://t.me/{bot_username}" if bot_username else "#"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{bot_username or 'File Store Bot'} — Fast, Secure File Sharing on Telegram</title>
<meta name="description" content="A Telegram file-store bot with force-subscribe, link shortening and ad-based unlocks.">
<style>{base_style(theme_key)}
.nav{{display:flex;align-items:center;justify-content:space-between;max-width:1000px;margin:0 auto;
padding:22px 20px}}
.nav .brand{{font-weight:700;font-size:18px}}
.nav a.btn{{background:var(--card);padding:9px 18px;border-radius:999px;text-decoration:none;font-size:14px}}
.hero{{max-width:820px;margin:60px auto 0;text-align:center;padding:0 20px}}
.hero h1{{font-size:clamp(28px,5vw,46px);line-height:1.15;margin:0 0 16px;
background:linear-gradient(90deg,#fff,var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}}
.hero p{{color:var(--muted);font-size:16px;max-width:560px;margin:0 auto 32px;line-height:1.6}}
.cta-row{{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-bottom:80px}}
.cta{{padding:14px 26px;border-radius:12px;text-decoration:none;font-weight:600;font-size:15px}}
.cta.primary{{background:linear-gradient(90deg,var(--accent1),var(--accent2));color:#fff}}
.cta.ghost{{background:var(--card);color:var(--text)}}
.grid{{max-width:1000px;margin:0 auto;padding:0 20px 90px;display:grid;
grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px}}
.feature{{background:var(--card);border-radius:var(--radius);padding:22px}}
.feature .icon{{font-size:26px;margin-bottom:10px}}
.feature h3{{margin:0 0 6px;font-size:16px}}
.feature p{{margin:0;color:var(--muted);font-size:13px;line-height:1.5}}
.contact{{max-width:720px;margin:0 auto;padding:0 20px 90px;text-align:center}}
.contact .card{{background:var(--card);border-radius:var(--radius);padding:36px 28px}}
.contact h2{{margin:0 0 10px;font-size:24px}}
.contact p{{color:var(--muted);margin:0 0 24px;font-size:14px}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding:24px 20px 40px}}
</style></head><body>
<div class="nav"><div class="brand">🗂️ {bot_username or 'FileStore'}</div>
<a class="btn" href="{add_link}" target="_blank" rel="noopener">Open Bot</a></div>

<section class="hero">
  <h1>Share files on Telegram, the fast way.</h1>
  <p>A production-ready file-store bot with force-subscribe gating, link shortening, multi-channel storage
  and ad-supported unlocks — all configurable from inside Telegram, no dashboard required.</p>
  <div class="cta-row">
    <a class="cta primary" href="https://t.me/{CONTACT_USERNAME}" target="_blank" rel="noopener">💼 Buy This Bot</a>
    <a class="cta ghost" href="https://t.me/{CONTACT_USERNAME}" target="_blank" rel="noopener">🛠️ Hire Me for Work</a>
  </div>
</section>

<section class="grid">
  <div class="feature"><div class="icon">📁</div><h3>Multi-Channel Storage</h3>
    <p>Store files across several database channels with automatic primary/fallback routing.</p></div>
  <div class="feature"><div class="icon">🔗</div><h3>Batch &amp; Single Links</h3>
    <p>Generate shareable links for a single file or an entire batch in one tap.</p></div>
  <div class="feature"><div class="icon">🔐</div><h3>Force-Subscribe</h3>
    <p>Require users to join your channels before unlocking content — no channel names ever exposed.</p></div>
  <div class="feature"><div class="icon">💰</div><h3>Ad-Based Unlocks</h3>
    <p>Configurable ad-verification page (Monetag + native banners) so free users unlock via ads.</p></div>
  <div class="feature"><div class="icon">✂️</div><h3>Link Shortener</h3>
    <p>Built-in URL shortener integration with live status checks from the admin panel.</p></div>
  <div class="feature"><div class="icon">⚙️</div><h3>Fully In-Bot Admin</h3>
    <p>Every setting — ads, channels, texts, premium, even this page's color theme — set from Telegram.</p></div>
</section>

<section class="contact">
  <div class="card">
    <h2>Want a bot like this?</h2>
    <p>I build and customize Telegram bots like this one — file stores, ad monetization, payment integrations
    and more.</p>
    <div class="cta-row" style="margin-bottom:0">
      <a class="cta primary" href="https://t.me/{CONTACT_USERNAME}" target="_blank" rel="noopener">💼 Buy This Bot</a>
      <a class="cta ghost" href="https://t.me/{CONTACT_USERNAME}" target="_blank" rel="noopener">🛠️ Hire Me for Work</a>
    </div>
  </div>
</section>

<footer>Built with Pyrogram &amp; aiohttp · © {bot_username or 'FileStore'}</footer>
</body></html>"""
