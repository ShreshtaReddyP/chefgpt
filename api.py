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
<meta name="theme-color" content="#f7f5ef">
<title>ChefGPT</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%231e4637%22/><text x=%2232%22 y=%2246%22 font-size=%2240%22 text-anchor=%22middle%22 fill=%22%23f9f8f4%22 font-family=%22Georgia,serif%22>C</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,500;0,600;1,400&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/photo-scan.css">
<style>
/* =========================================================
   ChefGPT: single consolidated stylesheet
   ========================================================= */
:root {
  --bg: #f7f5ef;
  --surface: #ffffff;
  --surface-2: #eef3ea;
  --ink: #1f2b25;
  --muted: #6f776c;
  --line: #e0e3d9;
  --green: #2f5e4a;
  --green-dark: #224637;
  --accent: #e28a55;
  --accent-soft: #fff3e8;
  --warm: #fff3df;
  --shadow: 0 18px 50px rgba(31, 43, 37, .08);
  --shadow-sm: 0 6px 18px rgba(31, 43, 37, .08);
  --radius: 20px;
  --ease: cubic-bezier(.22, 1, .36, 1);
  --serif: "Newsreader", Georgia, "Times New Roman", serif;
  --sans: "Instrument Sans", system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}

/* Automatic dark mode (follows the device setting) */
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121a16;
    --surface: #1a251f;
    --surface-2: #1f2d26;
    --ink: #eaf0e8;
    --muted: #9aa69c;
    --line: #2d3b33;
    --green: #7fc29f;
    --green-dark: #98d3b3;
    --accent: #f0a070;
    --accent-soft: #2b221c;
    --warm: #2b2619;
    --shadow: 0 18px 50px rgba(0, 0, 0, .35);
    --shadow-sm: 0 6px 18px rgba(0, 0, 0, .3);
  }
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; color: var(--ink); font-family: var(--sans); font-size: 16px; line-height: 1.55;
  -webkit-font-smoothing: antialiased; background: var(--bg); position: relative; overflow-x: hidden;
}
/* Slowly drifting colour glow behind the page */
body::before, body::after {
  content: ""; position: fixed; z-index: -1; width: 46rem; height: 46rem; border-radius: 50%;
  filter: blur(70px); opacity: .5; pointer-events: none;
}
body::before { top: -14rem; left: -12rem; background: radial-gradient(circle, rgba(226,138,85,.35), transparent 65%); animation: drift1 22s ease-in-out infinite alternate; }
body::after  { bottom: -16rem; right: -12rem; background: radial-gradient(circle, rgba(110,170,130,.35), transparent 65%); animation: drift2 26s ease-in-out infinite alternate; }
@keyframes drift1 { to { transform: translate(8rem, 6rem) scale(1.15); } }
@keyframes drift2 { to { transform: translate(-7rem, -5rem) scale(1.1); } }

button { font: inherit; color: inherit; -webkit-tap-highlight-color: transparent; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
::selection { background: var(--accent); color: #fff; }

.page { max-width: 1040px; margin: 0 auto; padding: 0 28px 64px; }

/* ---------- masthead ---------- */
.top {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  padding: 24px 0 18px; border-bottom: 1px solid var(--line);
  animation: fadeDown .7s var(--ease) both;
}
.logo {
  font-family: var(--serif); font-size: 2rem; font-weight: 500; letter-spacing: -.05em; color: var(--green);
  display: inline-flex; align-items: baseline; gap: 4px;
}
.logo::after {
  content: ""; width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
  animation: pulse 2.4s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.6); opacity: .55; } }
.top p { margin: 0; color: var(--muted); font-size: .9rem; text-align: right; }
@media (max-width: 640px) { .top p { display: none; } }

/* ---------- the order card ---------- */
.order {
  margin-top: 30px; padding: clamp(26px, 5vw, 54px);
  background: var(--surface); border: 1px solid var(--line); border-radius: 24px;
  box-shadow: var(--shadow); animation: fadeUp .8s .1s var(--ease) both;
  transition: box-shadow .3s var(--ease), transform .3s var(--ease);
}
.order:focus-within { box-shadow: 0 24px 64px rgba(47, 94, 74, .16); transform: translateY(-2px); }
.sentence {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 14px; margin: 0 0 20px;
  font-family: var(--serif); font-size: clamp(2rem, 4.7vw, 3.8rem); line-height: 1.1; letter-spacing: -.045em;
}
.sentence.small { font-size: clamp(1rem, 2vw, 1.25rem); color: var(--muted); letter-spacing: 0; margin: 0; }
.lead { font: inherit; color: inherit; }
.blank {
  flex: 1; min-width: 12ch; font: inherit; letter-spacing: inherit; color: var(--green);
  background: transparent; border: 0; border-radius: 0; padding: 0 4px 7px; outline: none;
  border-bottom: 2px solid var(--line);
  background-image: linear-gradient(var(--accent), var(--accent));
  background-repeat: no-repeat; background-position: left bottom; background-size: 0% 2px;
  transition: background-size .45s var(--ease);
}
.blank::placeholder { color: var(--muted); opacity: .5; }
.blank:focus, .blank:focus-visible { outline: none; background-size: 100% 2px; }
.sentence.small .blank { color: var(--ink); border-bottom-width: 1px; }

.row { margin-top: 28px; }
.go {
  position: relative; overflow: hidden; background: var(--green); color: #fff; border: 0;
  padding: 14px 30px; border-radius: 999px; font-weight: 600; font-size: 1rem; cursor: pointer;
  box-shadow: 0 8px 20px rgba(47, 94, 74, .25);
  transition: transform .2s var(--ease), box-shadow .2s var(--ease), background .2s;
}
@media (prefers-color-scheme: dark) { .go { color: #0f1813; } }
.go::after { /* shine sweep on hover */
  content: ""; position: absolute; top: 0; bottom: 0; left: -60%; width: 40%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,.35), transparent);
  transform: skewX(-20deg); transition: left .6s var(--ease);
}
.go:hover { background: var(--green-dark); transform: translateY(-2px); box-shadow: 0 12px 26px rgba(47, 94, 74, .3); }
.go:hover::after { left: 130%; }
.go:active { transform: translateY(0) scale(.97); }
.go:disabled { opacity: .75; cursor: wait; transform: none; animation: breathe 1.4s ease-in-out infinite; }
@keyframes breathe { 50% { opacity: .5; } }
@media (max-width: 640px) { .go { width: 100%; } }

/* ---------- chips ---------- */
.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 22px; font-size: .92rem; }
.chips[hidden] { display: none; }
.chip-label { color: var(--muted); margin-right: 4px; }
.chip {
  padding: 7px 14px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface-2);
  color: var(--green); cursor: pointer;
  transition: transform .2s var(--ease), background .2s, border-color .2s, box-shadow .2s;
}
.chip:hover { transform: translateY(-2px); border-color: var(--green); box-shadow: var(--shadow-sm); }
.chip:active { transform: scale(.94); }
.recent-chip { color: var(--ink); background: var(--surface); animation: pop .4s var(--ease) both; }
@keyframes pop { from { opacity: 0; transform: scale(.8); } to { opacity: 1; transform: scale(1); } }

/* ---------- loading and errors ---------- */
#out { margin-top: 46px; }
.loading { padding: 20px 0 44px; color: var(--muted); animation: fadeUp .4s var(--ease) both; }
.bar { position: relative; height: 5px; border-radius: 999px; background: var(--line); overflow: hidden; margin-bottom: 22px; }
.bar::after {
  content: ""; position: absolute; top: 0; bottom: 0; left: 0; width: 28%; border-radius: 999px;
  background: linear-gradient(90deg, var(--green), var(--accent));
  animation: slide 1.3s cubic-bezier(.4, 0, .2, 1) infinite;
}
@keyframes slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(360%); } }
#loadmsg { font-family: var(--serif); font-style: italic; font-size: clamp(1.4rem, 3vw, 1.9rem); color: var(--green); animation: msg .6s var(--ease); }
@keyframes msg { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.loading small { display: block; margin-top: 6px; font-size: .88rem; }

.error {
  padding: 20px 22px; background: var(--surface); border: 1px solid var(--line);
  border-left: 4px solid var(--accent); border-radius: 12px; animation: shake .5s var(--ease);
}
pre.error { white-space: pre-wrap; overflow-x: auto; font-size: .85rem; }
.error strong { display: block; font-weight: 600; }
.error .detail { margin: 6px 0 0; color: var(--muted); font-size: .88rem; word-break: break-word; }
@keyframes shake { 0%, 100% { transform: none; } 20% { transform: translateX(-7px); } 40% { transform: translateX(6px); } 60% { transform: translateX(-4px); } 80% { transform: translateX(2px); } }
.ghost {
  margin-top: 14px; background: var(--green); color: #fff; border: 0; padding: 9px 18px; border-radius: 999px;
  font-weight: 500; cursor: pointer; transition: transform .2s var(--ease), background .2s;
}
@media (prefers-color-scheme: dark) { .ghost { color: #0f1813; } }
.ghost:hover { background: var(--green-dark); transform: translateY(-1px); }
.ghost:active { transform: scale(.96); }

/* ---------- recipe: staggered entrance ---------- */
.recipe > * { animation: fadeUp .7s var(--ease) both; }
.recipe > :nth-child(1) { animation-delay: .00s; }
.recipe > :nth-child(2) { animation-delay: .08s; }
.recipe > :nth-child(3) { animation-delay: .16s; }
.recipe > :nth-child(4) { animation-delay: .24s; }
.recipe > :nth-child(5) { animation-delay: .32s; }
.recipe > :nth-child(6) { animation-delay: .40s; }
.recipe > :nth-child(n+7) { animation-delay: .48s; }

.title { font-family: var(--serif); font-weight: 500; font-size: clamp(2.4rem, 5.4vw, 4.4rem); line-height: 1.04; letter-spacing: -.055em; margin: 0 0 12px; }
.desc { font-family: var(--serif); font-size: 1.22rem; line-height: 1.5; color: var(--muted); max-width: 60ch; margin: 0; }

.photo-wrap {
  display: none; position: relative; margin-top: 28px; height: clamp(220px, 45vw, 420px);
  background: var(--surface-2); overflow: hidden; border-radius: var(--radius); box-shadow: var(--shadow);
}
.photo-wrap.show { display: block; animation: photoIn 1s var(--ease) both; }
.photo-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 1.2s var(--ease); }
.photo-wrap:hover img { transform: scale(1.05); }
@keyframes photoIn { from { opacity: 0; transform: scale(.97); filter: blur(8px); } to { opacity: 1; transform: none; filter: none; } }
.credit { position: absolute; right: 12px; bottom: 12px; font-size: .72rem; color: #fff; background: rgba(0, 0, 0, .45); backdrop-filter: blur(4px); padding: 3px 10px; border-radius: 999px; }
.credit:empty { display: none; }

/* ---------- quick facts ---------- */
.stats {
  display: flex; flex-wrap: wrap; margin: 28px 0 8px; padding: 0 18px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 16px;
}
.stat { padding: 15px 24px 15px 0; margin-right: 24px; border-right: 1px solid var(--line); transition: transform .25s var(--ease); }
.stat:hover { transform: translateY(-2px); }
.stat:last-child { border-right: 0; margin-right: 0; padding-right: 0; }
.stat-label { font-size: .7rem; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); }
.stat-val { font-family: var(--serif); font-size: 1.6rem; line-height: 1.2; color: var(--green); }

.safe {
  margin: 16px 0 0; padding: 14px 16px; font-size: .94rem;
  background: var(--accent-soft); border: 1px solid rgba(226, 138, 85, .3); border-left: 4px solid var(--accent); border-radius: 12px;
}
.safe small { display: block; color: var(--muted); margin-top: 2px; }

/* ---------- ingredients + method ---------- */
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr); gap: clamp(28px, 5vw, 56px); margin-top: 36px; }
@media (max-width: 760px) { .cols { grid-template-columns: 1fr; gap: 36px; } }
h3 { font-family: var(--serif); font-weight: 500; font-size: 1.8rem; letter-spacing: -.01em; margin: 0 0 4px; }
.hint { margin: 0 0 12px; font-size: .84rem; color: var(--muted); }

ul.ing { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--ink); }
ul.ing li { border-bottom: 1px solid var(--line); animation: slideIn .6s var(--ease) both; transition: background .2s, padding .25s var(--ease); }
ul.ing li:hover { background: var(--surface-2); padding-left: 8px; }
ul.ing li:nth-child(1) { animation-delay: .30s; } ul.ing li:nth-child(2) { animation-delay: .36s; }
ul.ing li:nth-child(3) { animation-delay: .42s; } ul.ing li:nth-child(4) { animation-delay: .48s; }
ul.ing li:nth-child(5) { animation-delay: .54s; } ul.ing li:nth-child(6) { animation-delay: .60s; }
ul.ing li:nth-child(7) { animation-delay: .66s; } ul.ing li:nth-child(8) { animation-delay: .72s; }
ul.ing li:nth-child(n+9) { animation-delay: .78s; }
ul.ing label { display: flex; gap: 12px; align-items: flex-start; padding: 13px 0; cursor: pointer; }
/* custom checkbox */
ul.ing input {
  appearance: none; -webkit-appearance: none; flex: none; margin: 3px 0 0; width: 20px; height: 20px;
  border: 2px solid var(--muted); border-radius: 6px; background: transparent; cursor: pointer; position: relative;
  transition: background .2s, border-color .2s, transform .2s var(--ease);
}
ul.ing input:hover { border-color: var(--green); transform: scale(1.1); }
ul.ing input:checked { background: var(--green); border-color: var(--green); animation: tick .35s var(--ease); }
ul.ing input:checked::after {
  content: ""; position: absolute; left: 5px; top: 1px; width: 5px; height: 10px;
  border: solid var(--surface); border-width: 0 2.5px 2.5px 0; transform: rotate(45deg);
}
@keyframes tick { 50% { transform: scale(1.3); } }
ul.ing li span { transition: color .25s, opacity .25s; }
ul.ing li.done span { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--accent); opacity: .7; }

ol.steps { list-style: none; counter-reset: s; padding: 0; margin: 0; border-top: 1px solid var(--ink); }
ol.steps li {
  counter-increment: s; position: relative; padding: 18px 12px 18px 56px; border-bottom: 1px solid var(--line);
  cursor: pointer; font-family: var(--serif); font-size: 1.15rem; line-height: 1.6; border-radius: 10px;
  animation: slideIn .6s var(--ease) both;
  transition: opacity .3s, background .2s, transform .25s var(--ease);
}
ol.steps li:nth-child(1) { animation-delay: .35s; } ol.steps li:nth-child(2) { animation-delay: .43s; }
ol.steps li:nth-child(3) { animation-delay: .51s; } ol.steps li:nth-child(4) { animation-delay: .59s; }
ol.steps li:nth-child(5) { animation-delay: .67s; } ol.steps li:nth-child(n+6) { animation-delay: .75s; }
ol.steps li:hover { background: var(--surface-2); transform: translateX(4px); }
ol.steps li:active { transform: scale(.99); }
ol.steps li::before {
  content: counter(s); position: absolute; left: 8px; top: 12px; width: 34px; height: 34px;
  display: grid; place-items: center; border-radius: 50%; font-size: 1.15rem; line-height: 1;
  color: var(--accent); border: 1.5px solid var(--accent);
  transition: background .25s, color .25s, transform .3s var(--ease);
}
ol.steps li.done { opacity: .45; }
ol.steps li.done::before { content: "✓"; background: var(--green); border-color: var(--green); color: var(--surface); transform: rotate(360deg); }

/* voice cooking */
.voice-cook { margin: 12px 0 18px; padding: 16px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 16px; }
.voice-cook p { margin: 2px 0 12px; color: var(--muted); font-size: .9rem; }
.voice-controls { display: flex; flex-wrap: wrap; gap: 8px; }
.voice-controls button {
  border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 9px 15px; cursor: pointer;
  transition: transform .2s var(--ease), background .2s, border-color .2s;
}
.voice-controls button:hover { transform: translateY(-2px); border-color: var(--green); }
.voice-controls button:active { transform: scale(.94); }
.voice-controls button.primary { background: var(--green); color: #fff; border-color: var(--green); }
@media (prefers-color-scheme: dark) { .voice-controls button.primary { color: #0f1813; } }
.voice-status { display: block; margin-top: 10px; font-size: .85rem; color: var(--green); }

.extra { margin-top: 36px; padding: 18px 22px; background: var(--warm); border: 1px solid rgba(226, 138, 85, .25); border-radius: 16px; }
.extra ul { margin: 8px 0 0; padding-left: 18px; }
.extra li { margin-bottom: 4px; }

.actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 36px; padding-top: 22px; border-top: 1px solid var(--line); }
.act {
  background: var(--surface); border: 1px solid var(--line); padding: 10px 18px; border-radius: 999px;
  font-weight: 500; font-size: .9rem; cursor: pointer;
  transition: transform .2s var(--ease), background .2s, border-color .2s, box-shadow .2s;
}
.act:hover { transform: translateY(-2px); border-color: var(--green); box-shadow: var(--shadow-sm); }
.act:active { transform: scale(.95); }

footer { margin-top: 48px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: .82rem; }

/* ---------- shared keyframes ---------- */
@keyframes fadeUp   { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
@keyframes fadeDown { from { opacity: 0; transform: translateY(-14px); } to { opacity: 1; transform: none; } }
@keyframes slideIn  { from { opacity: 0; transform: translateX(-14px); } to { opacity: 1; transform: none; } }

/* ---------- mobile ---------- */
@media (max-width: 640px) {
  .page { padding: 0 16px 38px; }
  .top { padding: 18px 0; }
  .order { margin-top: 18px; padding: 26px 20px; border-radius: 18px; }
  .sentence { font-size: clamp(2rem, 9vw, 3rem); }
  .blank, .sentence.small .blank { min-width: 100%; }
  .stats { padding: 0 12px; }
  .stat { margin-right: 12px; padding-right: 12px; }
}

/* ---------- print ---------- */
@media print {
  .top, .order, .actions, footer, .hint, .credit, .voice-cook, body::before, body::after { display: none !important; }
  body { background: #fff; color: #000; }
  #out { margin-top: 0; }
  .recipe > *, ul.ing li, ol.steps li { animation: none !important; }
}

/* ---------- accessibility ---------- */
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
