import json

import os

import re

import time

import urllib.parse

import urllib.request

from typing import List

from fastapi import FastAPI, HTTPException, Query

from fastapi.encoders import jsonable_encoder

from fastapi.responses import HTMLResponse

from pydantic import BaseModel

from chefgpt.pipeline import run

app = FastAPI(title="ChefGPT")

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

        "https\://pixabay.com/api/?" + params, headers={"User-Agent": "ChefGPT"}

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

<meta name="theme-color" content="#f9f8f4">

<title>ChefGPT</title>

<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http\://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22><rect width=%2264%22 height=%2264%22 rx=%2212%22 fill=%22%231e4637%22/><text x=%2232%22 y=%2246%22 font-size=%2240%22 text-anchor=%22middle%22 fill=%22%23f9f8f4%22 font-family=%22Georgia,serif%22>C</text></svg>">

<link rel="preconnect" href="https\://fonts.googleapis.com">

<link rel="preconnect" href="https\://fonts.gstatic.com" crossorigin>

<link href="https\://fonts.googleapis.com/css2?family=Newsreader:ital,wght\@0,400;0,500;0,600;1,400&family=Instrument+Sans:wght\@400;500;600&display=swap" rel="stylesheet">

<style>
:root{--cream:#f7f4ec;--paper:#fffefa;--ink:#182f28;--green:#254d3d;--green-light:#e2eadf;--tomato:#c95f45;--peach:#f0c7b6;--yellow:#f0d889;--muted:#73796f;--line:#d8d9ce;--serif:"Newsreader",Georgia,serif;--sans:"Instrument Sans",system-ui,sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--cream);color:var(--ink);font:16px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
button,input{font:inherit}button{color:inherit}:focus-visible{outline:3px solid var(--tomato);outline-offset:3px}
.page{max-width:1320px;margin:0 auto;padding:0 5.2vw 80px}
.top{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:24px 0;border-bottom:1px solid var(--ink)}
.logo{font:600 2rem var(--serif);letter-spacing:-.065em}.top p{margin:0;color:var(--muted);font-size:.83rem;letter-spacing:.02em}
.order{position:relative;isolation:isolate;overflow:hidden;margin:34px 0 0;padding:clamp(32px,6vw,78px);border-radius:30px;background:#e6ecdf;border:1px solid #d4dfd0}
.order:after{content:"";position:absolute;z-index:-1;width:380px;height:380px;right:-90px;top:-160px;border:1px solid #c3d2bd;border-radius:50%;box-shadow:0 0 0 35px #e0e8d9,0 0 0 70px #dbe5d5;opacity:.8}
.order:before{content:"A LITTLE INSPIRATION, A LOT OF FLAVOUR";display:block;margin-bottom:22px;color:var(--tomato);font-size:.68rem;font-weight:700;letter-spacing:.18em}
.sentence{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;margin:0 0 20px;font:500 clamp(2.7rem,7.5vw,6.8rem)/.98 var(--serif);letter-spacing:-.065em}
.sentence.small{font:400 clamp(1rem,2vw,1.25rem)/1.4 var(--sans);color:var(--muted);letter-spacing:0;margin:26px 0 0;max-width:900px}.lead{font:inherit;color:inherit}
.blank{flex:1;min-width:12ch;font:inherit;letter-spacing:inherit;color:var(--green);background:transparent;border:0;border-bottom:2px solid #8aa18c;border-radius:0;padding:0 4px 10px;outline:none;transition:border-color .2s}
.blank::placeholder{color:#9aa99a}.blank:focus,.blank:focus-visible{border-bottom-color:var(--tomato);outline:none}.sentence.small .blank{color:var(--ink);border-bottom-width:1px;min-width:18ch}
.row{margin-top:32px}.go{background:var(--green);color:#fff;border:1px solid var(--green);padding:16px 30px;border-radius:7px;font-weight:600;cursor:pointer;box-shadow:5px 5px 0 #c2d0bd;transition:transform .2s,box-shadow .2s,background .2s}
.go:hover{background:var(--tomato);border-color:var(--tomato);transform:translate(2px,2px);box-shadow:2px 2px 0 #c2d0bd}.go:disabled{opacity:.6;cursor:wait;transform:none}
.chips{display:flex;flex-wrap:wrap;align-items:center;gap:9px;margin-top:24px;font-size:.85rem}.chips[hidden]{display:none}.chip-label{color:var(--muted);margin-right:5px}
.chip{background:rgba(255,254,250,.68);border:1px solid #cbd7c7;border-radius:4px;padding:8px 13px;color:var(--green);cursor:pointer;transition:background .2s,transform .2s}
.chip:hover{background:var(--yellow);border-color:var(--yellow);transform:translateY(-2px)}.recent-chip{background:var(--green-light)}
#out{margin-top:clamp(38px,6vw,76px)}.loading{padding:8px 0 40px;color:var(--muted)}.bar{position:relative;height:4px;background:var(--line);overflow:hidden;margin-bottom:20px;border-radius:99px}
.bar:after{content:"";position:absolute;top:0;bottom:0;left:0;width:30%;background:var(--tomato);animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(340%)}}#loadmsg{font:italic 1.7rem var(--serif);color:var(--ink)}.loading small{display:block;margin-top:4px;font-size:.88rem}
.error{background:var(--paper);border:1px solid var(--line);border-left:5px solid var(--tomato);border-radius:12px;padding:24px}.error strong{display:block;font-size:1.05rem;font-weight:600}.error .detail{margin:8px 0 0;color:var(--muted);font-size:.88rem;word-break:break-word}
.ghost{margin-top:16px;background:var(--green);color:#fff;border:0;padding:10px 20px;border-radius:5px;font-weight:600;cursor:pointer}.ghost:hover{background:var(--tomato)}
.recipe{animation:fade .5s ease}@keyframes fade{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.recipe-head{max-width:900px}.title{font:600 clamp(2.8rem,7vw,6rem)/.96 var(--serif);letter-spacing:-.065em;margin:0 0 16px}.desc{font:italic clamp(1.15rem,2vw,1.45rem)/1.5 var(--serif);color:var(--muted);max-width:62ch;margin:0}
.photo-wrap{display:none;position:relative;margin-top:30px;height:clamp(280px,48vw,570px);background:var(--peach);overflow:hidden;border-radius:18px;border:0;box-shadow:0 18px 40px #263c2a18}
.photo-wrap.show{display:block;animation:fade .7s ease}.photo-wrap img{width:100%;height:100%;object-fit:cover;display:block}.credit{position:absolute;right:14px;bottom:14px;font-size:.72rem;color:#fff;background:rgba(24,47,40,.78);padding:5px 10px;border-radius:3px}.credit:empty{display:none}
.stats{display:flex;flex-wrap:wrap;gap:0;margin:28px 0 8px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.stat{min-width:130px;flex:1;padding:16px 20px 16px 0;background:transparent;border-right:1px solid var(--line);border-radius:0}.stat:not(:first-child){padding-left:20px}.stat:last-child{border-right:0}
.stat-label{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}.stat-val{font:500 1.65rem/1.2 var(--serif)}
.safe{margin:20px 0 0;padding:16px 18px;background:#f8ead9;border-left:3px solid var(--tomato);border-radius:5px;font-size:.94rem}.safe small{display:block;color:var(--muted);margin-top:4px}
.cols{display:grid;grid-template-columns:minmax(0,.78fr) minmax(0,1.45fr);gap:clamp(30px,6vw,90px);margin-top:52px}
h3{font:600 clamp(1.8rem,3vw,2.5rem)/1.1 var(--serif);letter-spacing:-.045em;margin:0 0 5px}.hint{margin:0 0 18px;font-size:.8rem;color:var(--muted)}
ul.ing{list-style:none;padding:0;margin:0;border-top:1px solid var(--ink)}ul.ing li{border-bottom:1px solid var(--line)}ul.ing label{display:flex;gap:12px;align-items:flex-start;padding:13px 0;cursor:pointer}
ul.ing input{margin-top:5px;width:17px;height:17px;accent-color:var(--green);flex:none}ul.ing li.done span{color:var(--muted);text-decoration:line-through}
ol.steps{list-style:none;counter-reset:s;padding:0;margin:0;border-top:1px solid var(--ink)}ol.steps li{counter-increment:s;position:relative;padding:18px 0 18px 58px;border-bottom:1px solid var(--line);cursor:pointer;font:400 1.2rem/1.6 var(--serif);transition:opacity .2s}
ol.steps li:before{content:counter(s,decimal-leading-zero);position:absolute;left:0;top:19px;font:700 .75rem var(--sans);letter-spacing:.08em;color:var(--tomato)}ol.steps li.done{opacity:.4}
.extra{margin-top:36px;padding:24px 28px;background:#f0e1ad;border-radius:8px}.extra ul{margin:8px 0 0;padding-left:18px}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:40px;padding-top:22px;border-top:1px solid var(--line)}.act{background:var(--paper);border:1px solid var(--line);padding:11px 18px;border-radius:5px;font-weight:500;font-size:.88rem;cursor:pointer;transition:background .2s}.act:hover{background:var(--yellow);border-color:var(--yellow)}
footer{margin-top:54px;color:var(--muted);font-size:.78rem;border-top:1px solid var(--line);padding-top:20px}
@media(max-width:760px){.cols{grid-template-columns:1fr;gap:34px}.order{padding:34px 26px}.order:after{right:-240px}.stat{min-width:50%}}
@media(max-width:640px){.page{padding:0 16px 44px}.top{align-items:flex-start;padding:19px 0}.logo{font-size:1.75rem}.top p{display:none}.order{margin-top:18px;border-radius:18px;padding:32px 20px}.sentence{font-size:clamp(2.5rem,11vw,3.6rem)}.blank{min-width:100%}.sentence.small .blank{min-width:100%}.go{width:100%}.photo-wrap{border-radius:12px}.stat{flex:1;padding:12px 10px 12px 0}.stat:not(:first-child){padding-left:10px}}
@media print{.top,.order,.actions,footer,.hint,.credit{display:none!important}body{background:#fff}#out{margin-top:0}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}html{scroll-behavior:auto}}

/* Refined layout: compact, editorial, less oversized */
:root{--cream:#f5f3ed;--paper:#fffefa;--ink:#1d3028;--green:#285544;--green-light:#e7ede5;--tomato:#b85b43;--muted:#747970;--line:#dcded5;--serif:"Newsreader",Georgia,serif;--sans:"Instrument Sans",system-ui,sans-serif}
body{background:var(--cream);font-size:15px}
.page{max-width:1180px;padding:0 34px 64px}
.top{padding:20px 0;border-bottom-color:#d7d9d0}
.logo{font-size:1.8rem;letter-spacing:-.055em}
.top p{font-size:.9rem}
.order{max-width:1040px;margin:30px auto 0;padding:44px 52px;border-radius:22px;background:var(--paper);border:1px solid #e3e3da;box-shadow:0 12px 35px rgba(30,48,39,.045)}
.order:after{width:240px;height:240px;right:-105px;top:-125px;border-color:#dce4d8;box-shadow:0 0 0 24px #f0f3ec;opacity:.75}
.order:before{font-size:.65rem;letter-spacing:.15em;margin-bottom:16px}
.sentence{position:relative;z-index:1;gap:8px 12px;margin-bottom:14px;font-size:clamp(2.5rem,5.1vw,4.35rem);line-height:1.03;letter-spacing:-.055em}
.blank{min-width:10ch;padding:0 2px 7px;border-bottom:1.5px solid #a8b7a8;color:var(--ink)}
.blank::placeholder{color:#a0aaa0}
.sentence.small{font-size:1rem;gap:10px;margin:20px 0 0;max-width:760px}
.sentence.small .blank{min-width:15ch;border-bottom:1px solid #c8cec3}
.row{margin-top:24px}
.go{padding:13px 24px;border-radius:8px;box-shadow:none;font-size:.92rem}
.go:hover{transform:translateY(-1px);box-shadow:0 5px 12px rgba(40,85,68,.15)}
.chips{gap:8px;margin-top:18px;font-size:.82rem}
.chip{background:#f7f8f3;border-color:#dce2d8;border-radius:7px;padding:7px 11px}
.chip:hover{background:#e9efe5;border-color:#d1ddce;transform:translateY(-1px)}
#out{max-width:1040px;margin:48px auto 0}
.recipe-head{max-width:760px}.title{font-size:clamp(2.5rem,5.5vw,4.6rem)}
.photo-wrap{height:clamp(240px,38vw,460px);border-radius:16px}
.stats{margin-top:24px}
.cols{gap:clamp(28px,5vw,64px);margin-top:42px}
@media(max-width:760px){.page{padding:0 20px 44px}.order{padding:34px 28px}.order:after{right:-180px}.cols{gap:30px}}
@media(max-width:640px){.page{padding:0 15px 36px}.top{padding:17px 0}.logo{font-size:1.6rem}.order{margin-top:18px;padding:28px 20px;border-radius:16px}.sentence{font-size:clamp(2.35rem,10vw,3.3rem)}.blank,.sentence.small .blank{min-width:100%}.sentence.small{align-items:flex-start;flex-direction:column;gap:5px}.go{width:auto;min-width:145px}.chips{gap:7px}.chip{padding:7px 9px}#out{margin-top:34px}}

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

        <label class="lead" for="food">What’s cooking?</label>

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

    const paren = t.match(/****\(****([^)]+)****\)****/);

    const base = t.replace(/****\(****[^)]*****\)****/g, "").replace(/\s+/g, " ").trim();

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

        .join("****\n****");

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
