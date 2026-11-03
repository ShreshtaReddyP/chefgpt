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
<link rel="stylesheet" href="/photo-scan.css">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f9f8f4">
<title>ChefGPT</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%231e4637%22/><text x=%2232%22 y=%2246%22 font-size=%2240%22 text-anchor=%22middle%22 fill=%22%23f9f8f4%22 font-family=%22Georgia,serif%22>C</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,500;0,600;1,400&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bone: #f9f8f4; --ink: #17201b; --muted: #667068; --line: #dcdfd6;
    --green: #1e4637; --green-dark: #163528; --saffron: #c98a10;
    --serif: "Newsreader", Georgia, "Times New Roman", serif;
    --sans: "Instrument Sans", system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0; background: var(--bone); color: var(--ink);
    font-family: var(--sans); font-size: 16px; line-height: 1.55; -webkit-font-smoothing: antialiased;
  }
  button { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--saffron); outline-offset: 2px; }

  .page { max-width: 880px; margin: 0 auto; padding: 0 24px 72px; }

  /* ---------- masthead ---------- */
  .top {
    display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
    padding: 26px 0 16px; border-bottom: 1px solid var(--ink);
  }
  .logo { font-family: var(--serif); font-size: 1.9rem; font-weight: 500; letter-spacing: -.01em; }
  .top p { margin: 0; color: var(--muted); font-size: .92rem; text-align: right; }
  @media (max-width: 640px) { .top p { display: none; } }

  /* ---------- the order, written as a sentence ---------- */
  .order { padding: 48px 0 30px; border-bottom: 1px solid var(--line); }
  .sentence {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; margin: 0 0 20px;
    font-family: var(--serif); font-size: clamp(1.9rem, 5.5vw, 3rem); line-height: 1.15; letter-spacing: -.015em;
  }
  .sentence.small { font-size: clamp(1.15rem, 3.2vw, 1.5rem); color: var(--muted); letter-spacing: 0; margin-bottom: 0; }
  .lead { font: inherit; color: inherit; }
  .blank {
    flex: 1; min-width: 12ch; font: inherit; letter-spacing: inherit; color: var(--green);
    background: transparent; border: 0; border-bottom: 2px solid var(--ink); border-radius: 0;
    padding: 0 2px 3px; outline: none; transition: border-color .15s;
  }
  .blank::placeholder { color: #b3b9ae; }
  .blank:focus, .blank:focus-visible { border-bottom-color: var(--saffron); outline: none; }
  .sentence.small .blank { color: var(--ink); border-bottom-width: 1px; }

  .row { margin-top: 28px; }
  .go {
    background: var(--green); color: #fff; border: 0; padding: 14px 30px; border-radius: 6px;
    font-weight: 600; font-size: 1rem; cursor: pointer; transition: background .15s;
  }
  .go:hover { background: var(--green-dark); }
  .go:disabled { opacity: .6; cursor: wait; }
  @media (max-width: 640px) { .go { width: 100%; } }

  .chips { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 18px; margin-top: 20px; font-size: .92rem; }
  .chips[hidden] { display: none; }
  .chip-label { color: var(--muted); }
  .chip { background: none; border: 0; border-bottom: 1px solid var(--line); padding: 0; color: var(--green); cursor: pointer; }
  .chip:hover { border-bottom-color: var(--green); }
  .recent-chip { color: var(--ink); }

  /* ---------- animated cooking loader and errors ---------- */
  #out { margin-top: 40px; }
  .loading {
    --loader-cream: #fff4e6; --loader-coral: #ff5b35; --loader-orange: #b9f34a;
    --loader-pink: #ff4fa3; --loader-teal: #7047eb; --loader-ink: #29152e;
    position: relative; overflow: hidden; padding: clamp(22px, 5vw, 42px);
    border: 1px solid #ffb99d; border-radius: 22px;
    background: radial-gradient(circle at 90% 10%, #ff4fa326 0, transparent 32%),
                radial-gradient(circle at 8% 95%, #7047eb1c 0, transparent 34%), var(--loader-cream);
    color: var(--loader-ink); isolation: isolate;
  }
  .loading-scene { width: min(100%, 420px); height: 190px; margin: 0 auto 18px; position: relative; }
  .counter { position: absolute; height: 18px; width: 100%; bottom: 20px; border-radius: 50%; background: #ffdbbd; }
  .pot { position: absolute; z-index: 2; width: 150px; height: 84px; left: 50%; bottom: 37px;
    transform: translateX(-50%); border-radius: 12px 12px 34px 34px;
    background: linear-gradient(110deg, #7047eb, #4d2aa8 65%, #29152e);
    box-shadow: 0 12px 0 #d6a77f, 0 18px 25px #b7795540; }
  .pot::before { content: ""; position: absolute; left: -19px; right: -19px; top: -9px; height: 15px;
    border-radius: 9px; background: #ff5b35; border: 4px solid #fff4e6; }
  .pot::after { content: ""; position: absolute; left: 50%; top: 28px; width: 38px; height: 9px;
    transform: translateX(-50%); border-radius: 50%; background: #f6d98d; opacity: .9; }
  .pot-handle { position: absolute; z-index: 1; width: 55px; height: 25px; left: calc(50% - 102px); bottom: 75px;
    border: 9px solid #ff5b35; border-right: 0; border-radius: 18px 0 0 18px; }
  .pot-handle.right { left: calc(50% + 47px); border: 9px solid #ff5b35; border-left: 0; border-radius: 0 18px 18px 0; }
  .steam { position: absolute; bottom: 115px; left: 50%; width: 15px; height: 42px; border-radius: 50%;
    border-left: 4px solid #ff4fa3; opacity: .75; animation: steam 1.8s ease-in-out infinite; }
  .steam.s2 { margin-left: -22px; height: 30px; animation-delay: -.6s; }
  .steam.s3 { margin-left: 20px; height: 36px; animation-delay: -1.1s; }
  .ingredient { position: absolute; z-index: 3; display: grid; place-items: center; width: 34px; height: 34px;
    border-radius: 50%; font-size: 1.35rem; background: transparent !important; box-shadow: none;
    animation: float 2.8s ease-in-out infinite; filter: drop-shadow(0 3px 3px #29152e20); }
  .ingredient.i1 { left: 18%; top: 54px; background: var(--loader-coral); animation-delay: -.4s; }
  .ingredient.i2 { right: 17%; top: 39px; width: 18px; height: 18px; background: var(--loader-teal); animation-delay: -1.2s; }
  .ingredient.i3 { right: 25%; top: 91px; width: 13px; height: 13px; background: var(--loader-orange); animation-delay: -.8s; }
  .ingredient.i4 { left: 28%; top: 30px; width: 15px; height: 15px; background: var(--loader-pink); animation-delay: -1.7s; }
  .loading-copy { text-align: center; }
  #loadmsg { font-family: var(--serif); font-size: clamp(1.45rem, 4vw, 2rem); color: var(--loader-ink); font-style: italic; margin: 0; }
  .loading small { display: block; margin-top: 7px; color: #776c61; font-size: .9rem; }
  .loading-progress { display: flex; justify-content: center; gap: 8px; margin-top: 20px; }
  .loading-progress span { width: 8px; height: 8px; border-radius: 50%; background: #e4d7f5; transition: transform .25s, background .25s; }
  .loading-progress span.active { background: var(--loader-pink); transform: scale(1.35); }
  @keyframes steam { 0%,100% { transform: translateY(0) scaleX(1); opacity: .2; } 50% { transform: translateY(-14px) scaleX(1.3); opacity: .85; } }
  @keyframes float { 0%,100% { transform: translateY(0) rotate(0); } 50% { transform: translateY(-13px) rotate(12deg); } }
  .error { border-left: 3px solid var(--saffron); padding: 6px 0 6px 18px; }
  .error strong { display: block; font-weight: 600; }
  .error .detail { margin: 6px 0 0; color: var(--muted); font-size: .88rem; word-break: break-word; }
  .ghost { margin-top: 14px; background: none; border: 1px solid var(--ink); padding: 8px 16px; border-radius: 6px; font-weight: 500; cursor: pointer; }
  .ghost:hover { background: var(--ink); color: #fff; }
  @media (max-width: 520px) {
    .loading-scene { height: 165px; transform: scale(.9); transform-origin: center bottom; margin-bottom: 8px; }
    .loading { padding: 22px 16px 28px; border-radius: 16px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .steam, .ingredient { animation: none !important; }
    .loading-progress span { transition: none; }
  }

  .recipe-reveal { animation: recipeReveal .65s cubic-bezier(.2,.75,.25,1) both; }
  @keyframes recipeReveal { from { opacity: 0; transform: translateY(18px) scale(.985); filter: blur(4px); } to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); } }
  /* ---------- recipe ---------- */
  .title {
    font-family: var(--serif); font-weight: 500; font-size: clamp(2.2rem, 6vw, 3.6rem);
    line-height: 1.04; letter-spacing: -.02em; margin: 0 0 12px;
  }
  .desc { font-family: var(--serif); font-size: 1.25rem; line-height: 1.5; color: var(--muted); max-width: 60ch; margin: 0; }
  .photo-wrap {
    display: none; position: relative; margin-top: 28px; height: clamp(220px, 45vw, 420px);
    background: #e7e9e1; overflow: hidden; border-radius: 4px;
  }
  .photo-wrap.show { display: block; animation: fade .7s ease; }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  .photo-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .credit { position: absolute; right: 10px; bottom: 10px; font-size: .72rem; color: #fff; background: rgba(0, 0, 0, .4); padding: 2px 8px; border-radius: 4px; }
  .credit:empty { display: none; }

  .stats { display: flex; flex-wrap: wrap; margin: 28px 0 8px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .stat { padding: 14px 32px 14px 0; margin-right: 32px; border-right: 1px solid var(--line); }
  .stat:last-child { border-right: 0; margin-right: 0; padding-right: 0; }
  .stat-label { font-size: .82rem; color: var(--muted); }
  .stat-val { font-family: var(--serif); font-size: 1.7rem; line-height: 1.2; }

  .safe { margin: 16px 0 0; padding-left: 14px; border-left: 2px solid var(--green); font-size: .94rem; }
  .safe small { display: block; color: var(--muted); margin-top: 2px; }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr); gap: 56px; margin-top: 36px; }
  @media (max-width: 760px) { .cols { grid-template-columns: 1fr; gap: 36px; } }
  h3 { font-family: var(--serif); font-weight: 500; font-size: 1.7rem; letter-spacing: -.01em; margin: 0 0 4px; }
  .hint { margin: 0 0 10px; font-size: .84rem; color: var(--muted); }

  ul.ing { list-style: none; padding: 0; margin: 0; border-top: 1px solid var(--ink); }
  ul.ing li { border-bottom: 1px solid var(--line); }
  ul.ing label { display: flex; gap: 12px; align-items: flex-start; padding: 11px 0; cursor: pointer; }
  ul.ing input { margin-top: 4px; width: 16px; height: 16px; accent-color: var(--green); flex: none; }
  ul.ing li.done span { color: var(--muted); text-decoration: line-through; }

  ol.steps { list-style: none; counter-reset: s; padding: 0; margin: 0; border-top: 1px solid var(--ink); }
  ol.steps li {
    counter-increment: s; position: relative; padding: 16px 0 16px 52px; border-bottom: 1px solid var(--line);
    cursor: pointer; font-family: var(--serif); font-size: 1.15rem; line-height: 1.6; transition: opacity .2s;
  }
  ol.steps li::before { content: counter(s); position: absolute; left: 0; top: 10px; font-family: var(--serif); font-size: 2rem; line-height: 1.2; color: var(--green); }
  ol.steps li.done { opacity: .4; }

  .extra { margin-top: 36px; padding: 18px 20px; background: #f0f1ea; border-radius: 6px; }
  .extra ul { margin: 8px 0 0; padding-left: 18px; }

  .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--line); }
  .act { background: none; border: 1px solid #c5cabd; padding: 9px 16px; border-radius: 6px; font-weight: 500; font-size: .9rem; cursor: pointer; }
  .act:hover { border-color: var(--ink); }

  footer { margin-top: 48px; color: var(--muted); font-size: .82rem; }

  @media print {
    .top, .order, .actions, footer, .hint, .credit { display: none !important; }
    body { background: #fff; }
    #out { margin-top: 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
    html { scroll-behavior: auto; }
  }


/* UI-only refinement: original HTML, JavaScript, and API logic remain unchanged. */
:root {
  --bone: #f5f3ed;
  --ink: #20352b;
  --muted: #737a70;
  --line: #dce0d6;
  --green: #285544;
  --green-dark: #1c4032;
  --saffron: #c87955;
  --serif: "Newsreader", Georgia, "Times New Roman", serif;
  --sans: "Instrument Sans", system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}
body { background: var(--bone); color: var(--ink); }
.page { max-width: 1120px; padding: 0 30px 64px; }
.top { padding: 22px 0 18px; border-bottom-color: var(--line); align-items: center; }
.logo { font-size: 1.85rem; letter-spacing: -.045em; }
.top p { font-size: .88rem; }
.order {
  margin: 30px 0 0; padding: clamp(28px, 5vw, 54px);
  border: 1px solid #e1e4da; border-radius: 20px;
  background: #e9eee5; box-shadow: 0 10px 30px rgba(32,53,43,.045);
}
.sentence { font-size: clamp(2.25rem, 5vw, 4.25rem); line-height: 1.06; letter-spacing: -.05em; gap: 8px 12px; }
.sentence.small { font-size: clamp(1.05rem, 2vw, 1.3rem); color: var(--muted); letter-spacing: 0; }
.blank {
  min-width: 10ch; color: var(--green); padding: 0 4px 8px;
  border-bottom: 1.5px solid #9eaf9f; transition: border-color .18s;
}
.blank::placeholder { color: #9da99d; }
.blank:focus, .blank:focus-visible { border-bottom-color: var(--saffron); }
.sentence.small .blank { border-bottom-width: 1px; }
.row { margin-top: 26px; }
.go { padding: 13px 24px; border-radius: 8px; box-shadow: 0 4px 0 rgba(28,64,50,.12); }
.go:hover { background: var(--green-dark); transform: translateY(-1px); }
.go:disabled { transform: none; }
.chips { gap: 9px; margin-top: 20px; }
.chip { padding: 7px 11px; border: 1px solid #d1dbce; border-radius: 7px; background: #f7f8f3; }
.chip:hover { background: #e0e9dc; border-color: #c4d2c0; }
.recent-chip { background: #eef2e9; }
#out { margin-top: 42px; }
.loading { padding: 10px 0 36px; }
.bar { height: 3px; border-radius: 99px; }
.bar::after { background: var(--saffron); }
#loadmsg { font-size: 1.65rem; }
.error { padding: 20px 22px; background: #fffefa; border: 1px solid var(--line); border-left: 4px solid var(--saffron); border-radius: 10px; }
.ghost { background: var(--green); color: white; border: 0; border-radius: 7px; }
.ghost:hover { background: var(--green-dark); }
.title { font-size: clamp(2.5rem, 5.5vw, 4.6rem); letter-spacing: -.05em; }
.desc { font-size: 1.3rem; }
.photo-wrap { border-radius: 14px; box-shadow: 0 12px 32px rgba(32,53,43,.08); }
.stats { border-color: var(--line); }
.stat { padding-top: 16px; padding-bottom: 16px; }
.stat-label { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; }
.stat-val { color: var(--green); }
.safe { background: #f5eadc; border-left-color: var(--saffron); border-radius: 7px; padding: 14px 16px; }
h3 { font-size: 2rem; }
ul.ing, ol.steps { border-top-color: var(--ink); }
ul.ing li, ol.steps li { border-bottom-color: var(--line); }
ol.steps li::before { color: var(--saffron); }
.extra { background: #f0e5bd; border-radius: 8px; }
.actions { border-top-color: var(--line); }
.act { background: #fffefa; border-color: var(--line); border-radius: 7px; }
.act:hover { background: #e8eee3; border-color: #cbd8c7; }
footer { border-top: 1px solid var(--line); padding-top: 18px; }
@media (max-width: 760px) {
  .page { padding: 0 20px 44px; }
  .order { padding: 30px 24px; }
}
@media (max-width: 640px) {
  .page { padding: 0 15px 36px; }
  .top { padding: 17px 0; }
  .order { margin-top: 18px; padding: 26px 20px; border-radius: 15px; }
  .sentence { font-size: clamp(2.2rem, 10vw, 3.2rem); }
  .blank, .sentence.small .blank { min-width: 100%; }
  .go { width: 100%; }
  .stat { margin-right: 14px; padding-right: 14px; }
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

  const LOADING_MSGS = [
    "Checking your ingredients...",
    "Mixing up some delicious ideas...",
    "Adding a little ChefGPT magic...",
    "Your recipe is almost ready!"
  ];
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
    clearInterval(loadTimer);

    out.innerHTML = `
      <section class="loading" role="status" aria-live="polite" aria-atomic="true">
        <div class="loading-scene" aria-hidden="true">
          <div class="counter"></div>
          <div class="pot-handle"></div>
          <div class="pot-handle right"></div>
          <div class="steam s1"></div>
          <div class="steam s2"></div>
          <div class="steam s3"></div>
          <div class="ingredient i1">🍅</div>
          <div class="ingredient i2">🌿</div>
          <div class="ingredient i3">🧄</div>
          <div class="ingredient i4">🍄</div>
          <div class="pot"></div>
        </div>
        <div class="loading-copy">
          <p id="loadmsg"></p>
          <small id="loadnote"></small>
          <div class="loading-progress" aria-hidden="true">
            <span class="active"></span><span></span><span></span><span></span>
          </div>
        </div>
      </section>`;

    updateLoadingMessage(i);
    setLoadingNote("This can take up to a minute.");

    loadTimer = setInterval(() => {
      i = (i + 1) % LOADING_MSGS.length;
      updateLoadingMessage(i);
    }, 2500);
  }

  function updateLoadingMessage(index) {
    const message = $("loadmsg");
    if (message) message.textContent = LOADING_MSGS[index];

    const dots = out.querySelectorAll(".loading-progress span");
    dots.forEach((dot, i) => dot.classList.toggle("active", i === index));
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

    const card = el("article", "recipe recipe-reveal");

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
      const ol = el("ol", "steps");
      steps.forEach((text) => {
        const li = el("li", "", text);
        li.addEventListener("click", () => li.classList.toggle("done"));
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
