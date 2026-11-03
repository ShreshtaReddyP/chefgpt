import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import List
from photo_scan import router as photo_router

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from chefgpt.pipeline import run

app = FastAPI(title="ChefGPT")
app.include_router(photo_router)


class RecipeRequest(BaseModel):
    request: str
    constraints: str = ""


# ---------------------------------------------------------------------------
# Food photos (Pixabay). The key stays on the server, never in the web page.
# ---------------------------------------------------------------------------
PHOTO_CACHE = {}
CACHE_SECONDS = 24 * 60 * 60


SYNONYMS = {
    "prawn": {"prawn", "shrimp"},
    "shrimp": {"prawn", "shrimp"},
    "chickpea": {"chickpea", "garbanzo", "chana", "chole"},
    "eggplant": {"eggplant", "aubergine", "brinjal"},
    "aubergine": {"eggplant", "aubergine", "brinjal"},
    "brinjal": {"eggplant", "aubergine", "brinjal"},
}
VEG_WORDS = {"vegetarian", "vegan", "veg", "veggie", "vegetable"}
MEAT_WORDS = {
    "chicken", "mutton", "lamb", "beef", "pork", "meat", "fish", "salmon", "tuna",
    "prawn", "shrimp", "crab", "bacon", "sausage", "turkey", "duck",
}
# Words in a dish name that a photo must really show. Other words, like "fluffy"
# or "andhra", are ignored because stock photos are never tagged with them.
MAIN_INGREDIENTS = MEAT_WORDS | {
    "chickpea", "paneer", "egg", "mushroom", "potato", "lentil", "dal", "tofu",
    "cauliflower", "spinach", "eggplant", "aubergine", "brinjal", "okra", "corn",
    "pea", "bean", "cheese", "tomato", "mango", "coconut", "chocolate", "banana",
}


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _words(text):
    return [_stem(w) for w in re.findall(r"[a-z]+", text.lower())]


def _accepts(query, tags):
    """Does a photo's tag list fit the search? Dish word AND main ingredient must match."""
    words = _words(query)
    if not words:
        return False
    tokens = set(_words(tags))

    def has(word):
        return bool(tokens & SYNONYMS.get(word, {word}))

    head, others = words[-1], words[:-1]
    if not has(head):
        return False
    wants_veg = any(w in VEG_WORDS for w in others)
    main = [w for w in others if w in MAIN_INGREDIENTS]
    if main and not any(has(w) for w in main):
        return False
    if wants_veg and tokens & MEAT_WORDS:
        return False
    return True


def _pixabay_search(key, query):
    params = urllib.parse.urlencode(
        {
            "key": key,
            "q": query[:100],
            "image_type": "photo",
            "category": "food",
            "orientation": "horizontal",
            "safesearch": "true",
            "per_page": 50,
        }
    )
    req = urllib.request.Request(
        "https://pixabay.com/api/?" + params, headers={"User-Agent": "ChefGPT"}
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    hits = data.get("hits") or []
    # No photo is better than a wrong photo: only accept one whose tags fit the search.
    for hit in hits:
        if _accepts(query, hit.get("tags") or ""):
            return hit.get("largeImageURL") or hit.get("webformatURL")
    return None


@app.get("/photo")
def photo(q: List[str] = Query(default=[])):
    """Try each search phrase in order and return the first photo found."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return {"url": None}
    if len(PHOTO_CACHE) > 500:
        PHOTO_CACHE.clear()
    for query in q[:4]:
        query = " ".join(query.split())
        if not query:
            continue
        cached = PHOTO_CACHE.get(query.lower())
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            url = cached[1]
        else:
            try:
                url = _pixabay_search(key, query)
            except Exception:
                continue
            PHOTO_CACHE[query.lower()] = (time.time(), url)
        if url:
            return {"url": url}
    return {"url": None}


PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f2f5ee">
<title>ChefGPT</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%231e4637%22/><text x=%2232%22 y=%2246%22 font-size=%2240%22 text-anchor=%22middle%22 fill=%22%23f9f8f4%22 font-family=%22Georgia,serif%22>C</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/photo-scan.css">
<style>
/* =========================================================
   ChefGPT: redesigned stylesheet
   Idea: a herb-garden kitchen. Deep basil green for trust and
   action, saffron yellow for warmth and highlights, chili red
   only for problems. Fraunces (soft, characterful serif) for
   dishes and headlines, Hanken Grotesk (clean sans) for
   everything you actually need to read while cooking.
   ========================================================= */

/* ---------- 1. Design tokens (colours, fonts, sizes) ---------- */
:root {
  color-scheme: light dark;            /* tells the browser to draw its own controls in the matching theme */
  --bg: #f2f5ee;
  --surface: #fcfdf9;
  --surface-2: #e8efe2;
  --field: #ffffff;                    /* background of text boxes */
  --ink: #14241b;                      /* main text */
  --muted: #55645a;                    /* secondary text (still passes contrast) */
  --line: #d2dcc8;
  --green: #1f5a40;
  --green-dark: #143d2c;
  --on-green: #ffffff;                 /* text that sits on a green button */
  --accent: #eaa51a;                   /* saffron */
  --accent-soft: #fff3d1;
  --warm: #fff3d1;
  --chili: #c24a2b;
  --shadow: 0 30px 60px -34px rgba(20, 36, 27, .45);
  --shadow-sm: 0 10px 22px -14px rgba(20, 36, 27, .5);
  --radius: 18px;
  --ease: cubic-bezier(.22, 1, .36, 1);
  --serif: "Fraunces", Georgia, "Times New Roman", serif;
  --sans: "Hanken Grotesk", system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}

/* Automatic dark mode (follows the device setting). Every colour pair below is chosen
   so that text stays easy to read on its background. */
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1712;
    --surface: #15211a;
    --surface-2: #1d2c23;
    --field: #101b15;
    --ink: #eef3ea;
    --muted: #a6b5aa;
    --line: #2d4036;
    --green: #8fd1a9;
    --green-dark: #aee3c4;
    --on-green: #0c1610;
    --accent: #f2b84b;
    --accent-soft: #2b2515;
    --warm: #2b2515;
    --chili: #ef8a6c;
    --shadow: 0 30px 60px -30px rgba(0, 0, 0, .7);
    --shadow-sm: 0 10px 22px -12px rgba(0, 0, 0, .7);
  }
}

/* ---------- 2. Base ---------- */
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; color: var(--ink); font-family: var(--sans); font-size: 16px; line-height: 1.6;
  -webkit-font-smoothing: antialiased; overflow-x: hidden; min-height: 100vh;
  background-color: var(--bg);
  /* two soft pools of colour, fixed in place so the page feels calm */
  background-image:
    radial-gradient(48rem 26rem at 90% -8%, rgba(234, 165, 26, .16), transparent 65%),
    radial-gradient(44rem 28rem at -8% 6%, rgba(47, 120, 84, .16), transparent 65%);
  background-repeat: no-repeat;
  background-attachment: fixed;
}
button { font: inherit; color: inherit; -webkit-tap-highlight-color: transparent; }
input, select, textarea { font-family: var(--sans); }
input::placeholder, textarea::placeholder { color: var(--muted); opacity: .8; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; border-radius: 6px; }
::selection { background: var(--accent); color: #14241b; }

.page { max-width: 1040px; margin: 0 auto; padding: 0 28px 72px; }

/* ---------- 3. Masthead ---------- */
.top {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  padding: 26px 0 20px;
  animation: fadeDown .7s var(--ease) both;
}
.logo {
  font-family: var(--serif); font-size: 2.05rem; font-weight: 600; letter-spacing: -.04em; color: var(--green);
  display: inline-flex; align-items: baseline; gap: 5px; line-height: 1;
}
.logo::after {
  content: ""; width: 10px; height: 10px; border-radius: 50%; background: var(--accent);
  animation: pulse 2.6s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.5); opacity: .6; } }
.top p { margin: 0; color: var(--muted); font-size: .95rem; text-align: right; }
@media (max-width: 640px) { .top p { display: none; } }

/* ---------- 4. The order card (where you type) ---------- */
.order {
  margin-top: 8px; padding: clamp(24px, 5vw, 52px);
  background: var(--surface); border: 1px solid var(--line); border-radius: 28px;
  box-shadow: var(--shadow); position: relative;
  animation: fadeUp .8s .1s var(--ease) both;
  transition: border-color .3s var(--ease);
}
.order:focus-within { border-color: var(--green); }

.sentence {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 16px; margin: 0 0 22px;
  font-family: var(--serif); font-weight: 500;
  font-size: clamp(1.9rem, 4.2vw, 3.1rem); line-height: 1.12; letter-spacing: -.03em;
}
.lead { font: inherit; color: var(--ink); }

/* the big "I'd like to cook ____" line */
.blank {
  flex: 1 1 14ch; min-width: 0; font: inherit; letter-spacing: inherit; font-weight: 600; color: var(--green);
  background-color: transparent; border: 0; border-radius: 0; padding: 0 2px 8px; outline: none;
  border-bottom: 2px solid var(--line);
  text-overflow: ellipsis;
  background-image: linear-gradient(var(--accent), var(--accent));
  background-repeat: no-repeat; background-position: left bottom; background-size: 0% 3px;
  transition: background-size .5s var(--ease);
}
.blank::placeholder { color: var(--muted); opacity: .55; font-weight: 500; }
.blank:focus, .blank:focus-visible { outline: none; background-size: 100% 3px; }

/* the smaller "Dietary needs" row: a proper boxed input so text is always readable */
.sentence.small {
  align-items: center; gap: 10px 14px; margin: 0;
  font-family: var(--sans); font-weight: 500; font-size: 1rem; letter-spacing: 0; color: var(--muted);
}
.sentence.small .lead { flex: none; color: var(--muted); font-weight: 600; font-size: .95rem; }
.sentence.small .blank {
  flex: 1 1 260px; font-weight: 500; font-size: 1rem; color: var(--ink);
  background-color: var(--field); background-image: none;
  border: 1.5px solid var(--line); border-radius: 12px; padding: 13px 16px;
  transition: border-color .2s, box-shadow .2s;
}
.sentence.small .blank::placeholder { opacity: .8; }
.sentence.small .blank:focus, .sentence.small .blank:focus-visible {
  border-color: var(--green); box-shadow: 0 0 0 4px rgba(234, 165, 26, .25);
}

.row { margin-top: 26px; }
.go {
  position: relative; overflow: hidden; background: var(--green); color: var(--on-green); border: 0;
  padding: 15px 34px; border-radius: 999px; font-weight: 700; font-size: 1.02rem; cursor: pointer;
  box-shadow: 0 12px 24px -12px var(--green);
  transition: transform .2s var(--ease), box-shadow .2s var(--ease), background .2s;
}
.go::after { /* a quick shine that sweeps across on hover */
  content: ""; position: absolute; top: 0; bottom: 0; left: -60%; width: 40%;
  background: linear-gradient(100deg, transparent, rgba(255, 255, 255, .35), transparent);
  transform: skewX(-20deg); transition: left .6s var(--ease);
}
.go:hover { background: var(--green-dark); transform: translateY(-2px); box-shadow: 0 16px 28px -12px var(--green); }
.go:hover::after { left: 130%; }
.go:active { transform: translateY(0) scale(.97); }
.go:disabled { opacity: .8; cursor: wait; transform: none; animation: breathe 1.4s ease-in-out infinite; }
@keyframes breathe { 50% { opacity: .55; } }
@media (max-width: 640px) { .go { width: 100%; } }

/* ---------- 5. Suggestion chips ---------- */
.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 22px; font-size: .92rem; }
.chips[hidden] { display: none; }
.chip-label { color: var(--muted); margin-right: 4px; font-weight: 500; }
.chip {
  padding: 8px 15px; border: 1.5px solid var(--line); border-radius: 999px; background: transparent;
  color: var(--ink); font-weight: 500; cursor: pointer;
  transition: transform .2s var(--ease), background .2s, border-color .2s, color .2s;
}
.chip:hover { transform: translateY(-2px); border-color: var(--green); background: var(--surface-2); color: var(--green); }
.chip:active { transform: scale(.94); }
.recent-chip {
  background: var(--surface-2); border-color: transparent;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  animation: pop .4s var(--ease) both;
}
@keyframes pop { from { opacity: 0; transform: scale(.85); } to { opacity: 1; transform: scale(1); } }

/* ---------- 6. Loading and errors ---------- */
#out { margin-top: 48px; }
.loading { padding: 20px 0 44px; color: var(--muted); animation: fadeUp .4s var(--ease) both; }
.bar { position: relative; height: 6px; border-radius: 999px; background: var(--line); overflow: hidden; margin-bottom: 24px; }
.bar::after {
  content: ""; position: absolute; top: 0; bottom: 0; left: 0; width: 28%; border-radius: 999px;
  background: linear-gradient(90deg, var(--green), var(--accent));
  animation: slide 1.3s cubic-bezier(.4, 0, .2, 1) infinite;
}
@keyframes slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(360%); } }
#loadmsg { font-family: var(--serif); font-style: italic; font-size: clamp(1.5rem, 3vw, 2rem); color: var(--green); animation: msg .6s var(--ease); }
@keyframes msg { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.loading small { display: block; margin-top: 8px; font-size: .92rem; }

.error {
  padding: 20px 22px; background: var(--surface); border: 1px solid var(--line); color: var(--ink);
  border-left: 5px solid var(--chili); border-radius: 12px; animation: shake .5s var(--ease);
}
pre.error { white-space: pre-wrap; overflow-x: auto; font-size: .85rem; }
.error strong { display: block; font-weight: 600; }
.error .detail { margin: 8px 0 0; color: var(--muted); font-size: .9rem; word-break: break-word; }
@keyframes shake { 0%, 100% { transform: none; } 20% { transform: translateX(-7px); } 40% { transform: translateX(6px); } 60% { transform: translateX(-4px); } 80% { transform: translateX(2px); } }
.ghost {
  margin-top: 14px; background: var(--green); color: var(--on-green); border: 0; padding: 10px 20px; border-radius: 999px;
  font-weight: 600; cursor: pointer; transition: transform .2s var(--ease), background .2s;
}
.ghost:hover { background: var(--green-dark); transform: translateY(-1px); }
.ghost:active { transform: scale(.96); }

/* ---------- 7. The recipe ---------- */
.recipe > * { animation: fadeUp .7s var(--ease) both; }
.recipe > :nth-child(1) { animation-delay: .00s; }
.recipe > :nth-child(2) { animation-delay: .08s; }
.recipe > :nth-child(3) { animation-delay: .16s; }
.recipe > :nth-child(4) { animation-delay: .24s; }
.recipe > :nth-child(5) { animation-delay: .32s; }
.recipe > :nth-child(6) { animation-delay: .40s; }
.recipe > :nth-child(n+7) { animation-delay: .48s; }

.title {
  font-family: var(--serif); font-weight: 600; font-size: clamp(2.3rem, 5.4vw, 4.2rem); line-height: 1.04;
  letter-spacing: -.045em; margin: 0 0 14px; text-wrap: balance;
}
.desc { font-family: var(--serif); font-size: 1.2rem; line-height: 1.6; color: var(--muted); max-width: 62ch; margin: 0; }

.photo-wrap {
  display: none; position: relative; margin-top: 30px; height: clamp(220px, 45vw, 420px);
  background: var(--surface-2); overflow: hidden; border-radius: 26px; border: 1px solid var(--line); box-shadow: var(--shadow);
}
.photo-wrap.show { display: block; animation: photoIn 1s var(--ease) both; }
.photo-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 1.2s var(--ease); }
.photo-wrap:hover img { transform: scale(1.04); }
@keyframes photoIn { from { opacity: 0; transform: scale(.97); filter: blur(8px); } to { opacity: 1; transform: none; filter: none; } }
.credit { position: absolute; right: 14px; bottom: 14px; font-size: .74rem; color: #fff; background: rgba(0, 0, 0, .55); backdrop-filter: blur(4px); padding: 4px 11px; border-radius: 999px; }
.credit:empty { display: none; }

/* quick facts: one clean strip, no boxes */
.stats {
  display: flex; flex-wrap: wrap; margin: 30px 0 8px; padding: 0;
  border-top: 2px solid var(--ink); border-bottom: 1px solid var(--line);
}
.stat { padding: 16px 28px 16px 0; margin-right: 28px; border-right: 1px solid var(--line); }
.stat:last-child { border-right: 0; margin-right: 0; padding-right: 0; }
.stat-label { font-size: .82rem; color: var(--muted); font-weight: 500; }
.stat-val { font-family: var(--serif); font-size: 1.7rem; font-weight: 600; line-height: 1.2; color: var(--green); }

.safe {
  margin: 18px 0 0; padding: 15px 18px; font-size: .96rem; color: var(--ink);
  background: var(--accent-soft); border-left: 5px solid var(--accent); border-radius: 4px 14px 14px 4px;
}
.safe small { display: block; color: var(--muted); margin-top: 3px; }

/* ---------- 8. Ingredients and method ---------- */
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.7fr); gap: clamp(28px, 5vw, 60px); margin-top: 38px; align-items: start; }
@media (min-width: 761px) { .cols > :first-child { position: sticky; top: 20px; } } /* ingredients stay in view while you scroll the method */
@media (max-width: 760px) { .cols { grid-template-columns: 1fr; gap: 38px; } }
h3 { font-family: var(--serif); font-weight: 600; font-size: 1.75rem; letter-spacing: -.02em; margin: 0 0 4px; color: var(--ink); }
.hint { margin: 0 0 14px; font-size: .88rem; color: var(--muted); }

ul.ing {
  list-style: none; padding: 4px 18px; margin: 0;
  background: var(--surface); border: 1px solid var(--line); border-radius: 18px;
}
ul.ing li { border-bottom: 1px solid var(--line); animation: slideIn .6s var(--ease) both; }
ul.ing li:last-child { border-bottom: 0; }
ul.ing li:nth-child(1) { animation-delay: .30s; } ul.ing li:nth-child(2) { animation-delay: .36s; }
ul.ing li:nth-child(3) { animation-delay: .42s; } ul.ing li:nth-child(4) { animation-delay: .48s; }
ul.ing li:nth-child(5) { animation-delay: .54s; } ul.ing li:nth-child(6) { animation-delay: .60s; }
ul.ing li:nth-child(7) { animation-delay: .66s; } ul.ing li:nth-child(8) { animation-delay: .72s; }
ul.ing li:nth-child(n+9) { animation-delay: .78s; }
ul.ing label { display: flex; gap: 13px; align-items: flex-start; padding: 13px 0; cursor: pointer; line-height: 1.45; }
/* custom checkbox */
ul.ing input {
  appearance: none; -webkit-appearance: none; flex: none; margin: 2px 0 0; width: 22px; height: 22px;
  border: 2px solid var(--muted); border-radius: 7px; background: transparent; cursor: pointer; position: relative;
  transition: background .2s, border-color .2s, transform .2s var(--ease);
}
ul.ing input:hover { border-color: var(--green); transform: scale(1.1); }
ul.ing input:checked { background: var(--green); border-color: var(--green); animation: tick .35s var(--ease); }
ul.ing input:checked::after {
  content: ""; position: absolute; left: 6px; top: 2px; width: 5px; height: 10px;
  border: solid var(--on-green); border-width: 0 2.5px 2.5px 0; transform: rotate(45deg);
}
@keyframes tick { 50% { transform: scale(1.3); } }
ul.ing li span { transition: color .25s, opacity .25s; }
ul.ing li.done span { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--accent); text-decoration-thickness: 2px; opacity: .75; }

ol.steps { list-style: none; counter-reset: s; padding: 0; margin: 0; border-top: 2px solid var(--ink); }
ol.steps li {
  counter-increment: s; position: relative; padding: 20px 14px 20px 64px; border-bottom: 1px solid var(--line);
  cursor: pointer; font-family: var(--sans); font-size: 1.08rem; line-height: 1.7; max-width: 68ch;
  animation: slideIn .6s var(--ease) both;
  transition: opacity .3s, background .2s;
}
ol.steps li:nth-child(1) { animation-delay: .35s; } ol.steps li:nth-child(2) { animation-delay: .43s; }
ol.steps li:nth-child(3) { animation-delay: .51s; } ol.steps li:nth-child(4) { animation-delay: .59s; }
ol.steps li:nth-child(5) { animation-delay: .67s; } ol.steps li:nth-child(n+6) { animation-delay: .75s; }
ol.steps li:hover { background: var(--surface-2); }
ol.steps li::before {
  content: counter(s); position: absolute; left: 10px; top: 18px; width: 36px; height: 36px;
  display: grid; place-items: center; border-radius: 50%;
  font-family: var(--serif); font-weight: 600; font-size: 1.15rem; line-height: 1;
  color: var(--green); border: 2px solid var(--green);
  transition: background .25s, color .25s, transform .3s var(--ease);
}
ol.steps li.done { opacity: .5; }
ol.steps li.done::before { content: "✓"; background: var(--green); border-color: var(--green); color: var(--on-green); transform: rotate(360deg); }

/* voice cooking */
.voice-cook { margin: 12px 0 20px; padding: 18px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 18px; }
.voice-cook strong { color: var(--ink); }
.voice-cook p { margin: 2px 0 14px; color: var(--muted); font-size: .92rem; }
.voice-controls { display: flex; flex-wrap: wrap; gap: 8px; }
.voice-controls button {
  border: 1.5px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 999px;
  padding: 10px 16px; font-weight: 500; cursor: pointer;
  transition: transform .2s var(--ease), background .2s, border-color .2s;
}
.voice-controls button:hover { transform: translateY(-2px); border-color: var(--green); }
.voice-controls button:active { transform: scale(.94); }
.voice-controls button.primary { background: var(--green); color: var(--on-green); border-color: var(--green); font-weight: 600; }
.voice-status { display: block; margin-top: 12px; font-size: .88rem; color: var(--green); font-weight: 500; }

.extra { margin-top: 40px; padding: 20px 24px; background: var(--warm); color: var(--ink); border-left: 5px solid var(--accent); border-radius: 4px 18px 18px 4px; }
.extra ul { margin: 8px 0 0; padding-left: 20px; }
.extra li { margin-bottom: 6px; }

.actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 40px; padding-top: 24px; border-top: 1px solid var(--line); }
.act {
  background: transparent; color: var(--ink); border: 1.5px solid var(--line); padding: 11px 20px; border-radius: 999px;
  font-weight: 600; font-size: .92rem; cursor: pointer;
  transition: transform .2s var(--ease), background .2s, border-color .2s;
}
.act:hover { transform: translateY(-2px); border-color: var(--green); background: var(--surface-2); }
.act:active { transform: scale(.95); }

footer { margin-top: 52px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: .85rem; }

/* ---------- 9. Shared keyframes ---------- */
@keyframes fadeUp   { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
@keyframes fadeDown { from { opacity: 0; transform: translateY(-14px); } to { opacity: 1; transform: none; } }
@keyframes slideIn  { from { opacity: 0; transform: translateX(-14px); } to { opacity: 1; transform: none; } }

/* ---------- 10. Photo-scan area: readability safety net ----------
   photo-scan.css is a separate file with its own colours. In dark mode some of its
   boxes stayed light while the text turned light too, so the text vanished. These rules
   (loaded after it, and marked !important) force dark boxes with light text in dark mode. */
@media (prefers-color-scheme: dark) {
  input:not([type="checkbox"]):not([type="radio"]):not([type="file"]):not(.blank),
  select, textarea {
    background-color: var(--field) !important; color: var(--ink) !important; border-color: var(--line) !important;
  }
  select option { background: var(--surface); color: var(--ink); }

  /* the dashed upload box */
  [class*="drop"], [class*="zone"], [class*="upload"] {
    background: var(--surface-2) !important; border-color: var(--green) !important; color: var(--ink) !important;
  }
  /* outline buttons such as "Change photo" (main green buttons are left alone) */
  :is([class*="scan"], [id*="scan"], [class*="drop"], [class*="upload"]) button:not([class*="primary"]):not([class*="find"]):not([class*="submit"]):not([class*="cta"]):not([class*="solid"]) {
    background-color: transparent !important; color: var(--ink) !important; border-color: var(--line) !important;
  }
  /* the little ingredient tags such as "Eggs x" */
  :is([class*="scan"], [id*="scan"], [class*="ingredient"]) :is([class*="chip"], [class*="tag"], [class*="pill"]):not(.chip):not(.recent-chip):not(.chip-label):not(.chips) {
    background-color: var(--surface-2) !important; color: var(--ink) !important; border-color: var(--line) !important;
  }
  :is([class*="chip"], [class*="tag"], [class*="pill"]):not(.chip):not(.recent-chip):not(.chip-label):not(.chips) button {
    color: var(--ink) !important; background: transparent !important;
  }
}

/* ---------- 11. Mobile ---------- */
@media (max-width: 640px) {
  .page { padding: 0 16px 40px; }
  .top { padding: 18px 0 14px; }
  .order { padding: 24px 20px; border-radius: 22px; }
  .sentence { font-size: clamp(1.8rem, 8vw, 2.6rem); }
  .blank { flex-basis: 100%; }
  .sentence.small .blank { flex-basis: 100%; }
  .stat { margin-right: 14px; padding-right: 14px; }
  ol.steps li { padding-left: 58px; }
}

/* ---------- 12. Print ---------- */
@media print {
  .top, .order, .actions, footer, .hint, .credit, .voice-cook { display: none !important; }
  body { background: #fff !important; color: #000; }
  #out { margin-top: 0; }
  .cols > :first-child { position: static; }
  .recipe > *, ul.ing li, ol.steps li { animation: none !important; }
}

/* ---------- 13. Accessibility: respect "reduce motion" ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  html { scroll-behavior: auto; }
}
</style>
</head>
<body>
  <div class="page">
    <header class="top">
      <div class="logo">ChefGPT</div>
      <p>Tell me what you're craving. I'll write the recipe.</p>
    </header>

    <section class="order">
      <div class="sentence">
        <label class="lead" for="food">I'd like to cook</label>
        <input class="blank" id="food" placeholder="chicken biryani" autocomplete="off">
      </div>
      <div class="sentence small">
        <label class="lead" for="cons">Dietary needs</label>
        <input class="blank" id="cons" placeholder="optional, e.g. no nuts, vegetarian" autocomplete="off">
      </div>
      <div class="row"><button type="button" class="go" id="go">Get recipe</button></div>
      <div class="chips">
        <span class="chip-label">Try</span>
        <button type="button" class="chip" data-f="Chicken pasta">Chicken pasta</button>
        <button type="button" class="chip" data-f="Veggie curry">Veggie curry</button>
        <button type="button" class="chip" data-f="Fluffy pancakes">Pancakes</button>
        <button type="button" class="chip" data-f="Beef tacos">Tacos</button>
        <button type="button" class="chip" data-f="Margherita pizza">Pizza</button>
        <button type="button" class="chip" data-f="Chocolate cake">Chocolate cake</button>
      </div>
      <div class="chips" id="recent" hidden></div>
    </section>

    <main id="out" aria-live="polite"></main>
    <footer>ChefGPT · Powered by Gemini · Photos from Pixabay</footer>
  </div>

<script>
  const $ = (id) => document.getElementById(id);
  const out = $("out");

  const LOADING_MSGS = ["Chopping the onions…", "Heating up the pan…", "Tasting for salt…", "Plating it up…"];
  const RECENT_KEY = "chefgpt_recent";
  const EXTRA_RE = /tip|note|substitut/i;
  let loadTimer = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function prettyKey(k) { return k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()); }
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // The recipe object is whichever nested object has an "ingredients" list.
  function findRecipe(o) {
    if (!o || typeof o !== "object" || Array.isArray(o)) return null;
    if (Object.keys(o).some((k) => /ingredient/i.test(k) && Array.isArray(o[k]))) return o;
    const vals = Object.values(o);
    for (let i = 0; i < vals.length; i++) { const r = findRecipe(vals[i]); if (r) return r; }
    return null;
  }
  function findConstraints(o) {
    if (!o || typeof o !== "object" || Array.isArray(o)) return null;
    if (Array.isArray(o.allergens) || Array.isArray(o.diets)) return o;
    const vals = Object.values(o);
    for (let i = 0; i < vals.length; i++) { const r = findConstraints(vals[i]); if (r) return r; }
    return null;
  }
  function itemText(x) {
    if (typeof x === "string") return x;
    if (x && typeof x === "object") {
      const name = x.name || x.item || x.ingredient;
      if (name) {
        const q = x.quantity !== undefined ? x.quantity : (x.amount !== undefined ? x.amount : x.qty);
        return [q, x.unit, name].filter((v) => v !== undefined && v !== null && v !== "").join(" ");
      }
      const t = x.text || x.step || x.instruction || x.description;
      if (t) return t;
      return Object.values(x).join(" ");
    }
    return String(x);
  }
  function metaStat(k, v) {
    const key = k.toLowerCase();
    const num = typeof v === "number";
    if (/calorie|kcal/.test(key)) return [/per/.test(key) ? "Calories per serving" : "Calories", v + " kcal"];
    if (/serv/.test(key)) return ["Serves", String(v)];
    if (/prep/.test(key)) return ["Prep time", v + (num ? " min" : "")];
    if (/cook/.test(key)) return ["Cook time", v + (num ? " min" : "")];
    if (/time|minute/.test(key)) return ["Time", v + (num ? " min" : "")];
    return [prettyKey(k), String(v)];
  }

  // ---------- photo ----------
  function photoQueries(title, food) {
    const t = (title || "").trim();
    const paren = t.match(/\(([^)]+)\)/);
    const base = t.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").trim();
    const english = paren ? paren[1].trim() : (base || food);
    const list = [english];
    if (paren) list.push(base);
    const words = english.split(/\s+/).filter(Boolean);
    if (words.length > 2) list.push(words.slice(-2).join(" "));
    list.push(food);
    const seen = {};
    return list.filter((q) => {
      const k = (q || "").toLowerCase().trim();
      if (!k || seen[k]) return false;
      seen[k] = true;
      return true;
    }).slice(0, 4);
  }
  function loadPhoto(title, food, img, wrap, credit) {
    const params = new URLSearchParams();
    photoQueries(title, food).forEach((q) => params.append("q", q));
    fetch("/photo?" + params.toString())
      .then((r) => r.json())
      .then((d) => {
        if (!d || !d.url) return;
        img.onload = () => { wrap.classList.add("show"); credit.textContent = "Stock photo: Pixabay"; };
        img.onerror = () => img.remove();
        img.src = d.url;
      })
      .catch(() => {});
  }

  // ---------- recent searches ----------
  function loadRecent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch (e) { return []; }
  }
  function saveRecent(food) {
    try {
      const list = loadRecent().filter((x) => x.toLowerCase() !== food.toLowerCase());
      list.unshift(food);
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 5)));
    } catch (e) {}
    renderRecent();
  }
  function renderRecent() {
    const box = $("recent");
    box.innerHTML = "";
    const list = loadRecent();
    if (!list.length) { box.hidden = true; return; }
    box.hidden = false;
    box.appendChild(el("span", "chip-label", "Recent"));
    list.forEach((f) => {
      const b = el("button", "chip recent-chip", f);
      b.type = "button";
      b.addEventListener("click", () => { $("food").value = f; $("food").focus(); });
      box.appendChild(b);
    });
  }

  // ---------- loading and errors ----------
  function showLoading() {
    let i = 0;
    out.innerHTML = '<div class="loading"><div class="bar"></div><div id="loadmsg"></div><small id="loadnote"></small></div>';
    $("loadmsg").textContent = LOADING_MSGS[0];
    setLoadingNote("This can take up to a minute.");
    clearInterval(loadTimer);
    loadTimer = setInterval(() => {
      i = (i + 1) % LOADING_MSGS.length;
      const n = $("loadmsg");
      if (n) n.textContent = LOADING_MSGS[i];
    }, 2500);
  }
  function setLoadingNote(text) {
    const n = $("loadnote");
    if (n) n.textContent = text;
  }
  function showError(msg, detail) {
    out.innerHTML = "";
    const box = el("div", "error");
    box.appendChild(el("strong", "", msg));
    if (detail) box.appendChild(el("p", "detail", String(detail).slice(0, 200)));
    const retry = el("button", "ghost", "Try again");
    retry.type = "button";
    retry.addEventListener("click", go);
    box.appendChild(retry);
    out.appendChild(box);
  }

  // ---------- recipe ----------
  function render(data, food) {
    out.innerHTML = "";
    const r = findRecipe(data);
    if (!r) {
      out.appendChild(el("pre", "error", JSON.stringify(data, null, 2)));
      return;
    }
    const keys = Object.keys(r);
    const titleKey = keys.find((k) => /^(title|name|dish)$/i.test(k));
    const ingKey = keys.find((k) => /ingredient/i.test(k) && Array.isArray(r[k]));
    const stepKey = keys.find((k) => /(step|instruction|direction|method)/i.test(k) && Array.isArray(r[k]));
    const title = titleKey ? String(r[titleKey]) : food.charAt(0).toUpperCase() + food.slice(1);

    // quick facts and an optional description
    const stats = el("div", "stats");
    const metaTexts = [];
    let desc = "";
    keys.forEach((k) => {
      const v = r[k];
      if (k === titleKey || EXTRA_RE.test(k)) return;
      if (typeof v === "number" || (typeof v === "string" && v.length <= 40)) {
        const s = metaStat(k, v);
        metaTexts.push(s[0] + ": " + s[1]);
        const box = el("div", "stat");
        box.appendChild(el("div", "stat-label", s[0]));
        box.appendChild(el("div", "stat-val", s[1]));
        stats.appendChild(box);
      } else if (typeof v === "string" && !desc) {
        desc = v;
      }
    });

    const card = el("article", "recipe");

    const head = el("div", "recipe-head");
    head.appendChild(el("h2", "title", title));
    if (desc) head.appendChild(el("p", "desc", desc));
    card.appendChild(head);

    // photo stays hidden until it has loaded
    const wrap = el("div", "photo-wrap");
    const img = document.createElement("img");
    img.alt = title;
    wrap.appendChild(img);
    const credit = el("span", "credit", "");
    wrap.appendChild(credit);
    card.appendChild(wrap);
    loadPhoto(title, food, img, wrap, credit);

    if (stats.children.length) card.appendChild(stats);

    // constraints
    const c = findConstraints(data);
    if (c) {
      const bits = [];
      if (c.allergens && c.allergens.length) bits.push("avoiding " + c.allergens.join(", ").replace(/_/g, " "));
      if (c.diets && c.diets.length) bits.push(c.diets.join(", ").replace(/_/g, " "));
      if (bits.length) {
        const safe = el("div", "safe");
        safe.appendChild(el("strong", "", "Your dietary needs: "));
        safe.appendChild(document.createTextNode(bits.join(" · ")));
        safe.appendChild(el("small", "", "Always double-check ingredient labels if you have an allergy."));
        card.appendChild(safe);
      }
    }

    // ingredients + method
    const ings = ingKey ? r[ingKey].map(itemText) : [];
    const steps = stepKey ? r[stepKey].map(itemText) : [];
    const cols = el("div", "cols");
    if (ings.length) {
      const left = el("div");
      left.appendChild(el("h3", "", "Ingredients"));
      left.appendChild(el("p", "hint", "Tick items off as you gather them."));
      const ul = el("ul", "ing");
      ings.forEach((text) => {
        const li = el("li");
        const lab = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.addEventListener("change", () => li.classList.toggle("done", cb.checked));
        lab.appendChild(cb);
        lab.appendChild(el("span", "", text));
        li.appendChild(lab);
        ul.appendChild(li);
      });
      left.appendChild(ul);
      cols.appendChild(left);
    }
    if (steps.length) {
      const right = el("div");
      right.appendChild(el("h3", "", "Method"));
      right.appendChild(el("p", "hint", "Tap a step to mark it done."));

      // Hands-free voice cooking. Uses the browser's built-in speech synthesis.
      const voiceBox = el("section", "voice-cook");
      voiceBox.appendChild(el("strong", "", "Voice cooking"));
      voiceBox.appendChild(el("p", "", "Listen to each instruction while you cook."));
      const voiceControls = el("div", "voice-controls");
      const startVoice = el("button", "primary", "▶ Read step");
      const prevVoice = el("button", "", "← Previous");
      const pauseVoice = el("button", "", "Ⅱ Pause");
      const nextVoice = el("button", "", "Next →");
      [startVoice, prevVoice, pauseVoice, nextVoice].forEach((b) => {
        b.type = "button";
        voiceControls.appendChild(b);
      });
      const voiceStatus = el("span", "voice-status", "Ready to start.");
      voiceBox.appendChild(voiceControls);
      voiceBox.appendChild(voiceStatus);
      right.appendChild(voiceBox);

      let activeVoiceStep = 0;
      function stopSpeaking() {
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      }
      function speakVoiceStep() {
        if (!("speechSynthesis" in window)) {
          voiceStatus.textContent = "Voice playback isn't supported in this browser.";
          return;
        }
        if (!steps.length) return;
        stopSpeaking();
        const spokenText = "Step " + (activeVoiceStep + 1) + ". " + steps[activeVoiceStep];
        const utterance = new SpeechSynthesisUtterance(spokenText);
        utterance.rate = 0.92;
        utterance.onstart = () => {
          voiceStatus.textContent = "Speaking step " + (activeVoiceStep + 1) + " of " + steps.length + ".";
          startVoice.textContent = "▶ Read again";
        };
        utterance.onend = () => {
          voiceStatus.textContent = "Finished step " + (activeVoiceStep + 1) + ". Say or tap Next when ready.";
        };
        utterance.onerror = () => {
          voiceStatus.textContent = "Couldn't play this step. Try Read step again.";
        };
        window.speechSynthesis.speak(utterance);
      }
      startVoice.addEventListener("click", speakVoiceStep);
      prevVoice.addEventListener("click", () => {
        activeVoiceStep = Math.max(0, activeVoiceStep - 1);
        speakVoiceStep();
      });
      nextVoice.addEventListener("click", () => {
        activeVoiceStep = Math.min(steps.length - 1, activeVoiceStep + 1);
        speakVoiceStep();
      });
      pauseVoice.addEventListener("click", () => {
        if (!("speechSynthesis" in window)) {
          voiceStatus.textContent = "Voice playback isn't supported in this browser.";
          return;
        }
        if (window.speechSynthesis.paused) {
          window.speechSynthesis.resume();
          pauseVoice.textContent = "Ⅱ Pause";
          voiceStatus.textContent = "Resuming voice playback.";
        } else if (window.speechSynthesis.speaking) {
          window.speechSynthesis.pause();
          pauseVoice.textContent = "▶ Resume";
          voiceStatus.textContent = "Paused.";
        } else {
          speakVoiceStep();
        }
      });

      const ol = el("ol", "steps");
      steps.forEach((text, index) => {
        const li = el("li", "", text);
        li.addEventListener("click", () => {
          li.classList.toggle("done");
          activeVoiceStep = index;
          voiceStatus.textContent = "Selected step " + (index + 1) + ". Tap Read step to hear it.";
        });
        ol.appendChild(li);
      });
      right.appendChild(ol);
      cols.appendChild(right);
    }
    card.appendChild(cols);

    // tips / notes if the recipe has them
    keys.forEach((k) => {
      if (!EXTRA_RE.test(k)) return;
      const v = r[k];
      const items = Array.isArray(v) ? v.map(itemText) : (typeof v === "string" ? [v] : []);
      if (!items.length) return;
      const box = el("div", "extra");
      box.appendChild(el("h3", "", prettyKey(k)));
      const ul = el("ul");
      items.forEach((t) => ul.appendChild(el("li", "", t)));
      box.appendChild(ul);
      card.appendChild(box);
    });

    // actions
    const actions = el("div", "actions");
    const copyBtn = el("button", "act", "Copy recipe");
    const printBtn = el("button", "act", "Print");
    const againBtn = el("button", "act", "New recipe");
    [copyBtn, printBtn, againBtn].forEach((b) => { b.type = "button"; actions.appendChild(b); });
    copyBtn.addEventListener("click", async () => {
      const text = [title, metaTexts.join(" · "), "", "INGREDIENTS"]
        .concat(ings.map((x) => "- " + x), ["", "METHOD"], steps.map((x, i) => (i + 1) + ". " + x))
        .join("\n");
      try { await navigator.clipboard.writeText(text); copyBtn.textContent = "Copied"; }
      catch (e) { copyBtn.textContent = "Couldn't copy"; }
      setTimeout(() => { copyBtn.textContent = "Copy recipe"; }, 2000);
    });
    printBtn.addEventListener("click", () => window.print());
    againBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
      $("food").focus();
      $("food").select();
    });
    card.appendChild(actions);

    out.appendChild(card);
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- ask the server (retries if it is waking up or busy) ----------
  async function requestRecipe(food, constraints) {
    let lastError = "";
    for (let attempt = 1; attempt <= 3; attempt++) {
      let note = "The server is waking up. Trying again…";
      try {
        const res = await fetch("/recipe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request: food, constraints: constraints })
        });
        let data = null;
        try { data = await res.json(); } catch (e) {}
        if (res.ok && data) return { data: data };
        lastError = (data && typeof data.detail === "string") ? data.detail : "";
        if (data && res.status < 500) return { error: lastError };
        if (data) note = "The AI service is busy. Trying again…";
      } catch (e) {
        lastError = String(e);
        note = "Lost the connection. Trying again…";
      }
      if (attempt === 3) break;
      setLoadingNote(note);
      await wait(8000);
    }
    return { error: lastError };
  }

  async function go() {
    const food = $("food").value.trim();
    const btn = $("go");
    if (!food) { $("food").focus(); return; }
    showLoading();
    btn.disabled = true;
    btn.textContent = "Cooking…";
    const result = await requestRecipe(food, $("cons").value);
    clearInterval(loadTimer);
    if (result.data) {
      saveRecent(food);
      render(result.data, food);
    } else {
      showError("Couldn't get a recipe right now. The AI service may be busy, so try again in a moment.", result.error);
    }
    btn.disabled = false;
    btn.textContent = "Get recipe";
  }

  $("go").addEventListener("click", go);
  $("food").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  $("cons").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  document.querySelectorAll(".chip[data-f]").forEach((b) => {
    b.addEventListener("click", () => { $("food").value = b.dataset.f; $("food").focus(); });
  });
  renderRecent();
</script>
<script src="/photo-scan.js"></script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


@app.post("/recipe")
def make_recipe(body: RecipeRequest):
    try:
        result = run(body.request, body.constraints)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    return jsonable_encoder(result)
