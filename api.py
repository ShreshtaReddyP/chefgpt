import json
import os
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


def _pixabay_search(key, query):
    params = urllib.parse.urlencode(
        {
            "key": key,
            "q": query[:100],
            "image_type": "photo",
            "category": "food",
            "orientation": "horizontal",
            "safesearch": "true",
            "per_page": 5,
        }
    )
    req = urllib.request.Request(
        "https://pixabay.com/api/?" + params, headers={"User-Agent": "ChefGPT"}
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    hits = data.get("hits") or []
    if hits:
        return hits[0].get("largeImageURL") or hits[0].get("webformatURL")
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
<meta name="theme-color" content="#e8590c">
<title>ChefGPT</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🍳</text></svg>">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Fraunces:wght@600;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #fbf6ee; --card: #ffffff; --ink: #241a12; --muted: #85735f; --line: #eee1d0;
    --accent: #e8590c; --accent-dark: #c2410c; --soft: #ffeadb; --ok: #2f9e44;
    --radius: 20px; --shadow: 0 10px 40px rgba(70, 35, 5, .10);
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: "DM Sans", system-ui, Arial, sans-serif; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  button { font: inherit; }

  /* ---------- header ---------- */
  .hero {
    background:
      radial-gradient(900px 360px at 85% -30%, rgba(255, 255, 255, .30), transparent 60%),
      linear-gradient(135deg, #ff9a3c 0%, #e8590c 100%);
    color: #fff; text-align: center; padding: 46px 20px 100px;
  }
  .hero h1 {
    font-family: "Fraunces", Georgia, serif; font-weight: 800; letter-spacing: -1px;
    font-size: clamp(2.3rem, 6vw, 3.3rem); margin: 0 0 6px;
  }
  .hero p { margin: 0; opacity: .95; font-size: 1.08rem; }

  .wrap { max-width: 860px; margin: -64px auto 56px; padding: 0 16px; }

  /* ---------- search panel ---------- */
  .panel { background: var(--card); border-radius: var(--radius); padding: 24px; box-shadow: var(--shadow); }
  .fields { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 14px; }
  @media (max-width: 640px) { .fields { grid-template-columns: 1fr; } }
  label {
    display: block; font-weight: 700; font-size: .78rem; margin: 0 0 6px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .6px;
  }
  .field {
    width: 100%; padding: 14px 16px; font: inherit; font-size: 1.02rem; color: var(--ink);
    border: 2px solid var(--line); border-radius: 12px; background: #fffdfa; outline: none;
    transition: border-color .15s, box-shadow .15s;
  }
  .field:focus { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(232, 89, 12, .12); }
  .chips { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
  .chips[hidden] { display: none; }
  .chip-label { font-size: .78rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .6px; margin-right: 2px; }
  .chip {
    border: none; background: var(--soft); color: var(--accent-dark); padding: 7px 14px;
    border-radius: 999px; font-size: .9rem; cursor: pointer; transition: transform .1s, background .15s;
  }
  .chip:hover { background: #ffd8b0; transform: translateY(-1px); }
  .recent-chip { background: #f3ece2; color: var(--ink); }
  .recent-chip:hover { background: #eadfce; }
  .go {
    width: 100%; margin-top: 6px; border: none; background: var(--accent); color: #fff; font-weight: 700;
    font-size: 1.1rem; padding: 15px; border-radius: 12px; cursor: pointer;
    transition: background .15s, transform .1s;
  }
  .go:hover { background: var(--accent-dark); }
  .go:active { transform: scale(.99); }
  .go:disabled { opacity: .65; cursor: wait; }

  /* ---------- loading and errors ---------- */
  #out { margin-top: 28px; }
  .loading { text-align: center; padding: 44px 10px; color: var(--muted); }
  .loading small { display: block; margin-top: 4px; opacity: .8; }
  .spinner {
    width: 44px; height: 44px; border: 5px solid var(--soft); border-top-color: var(--accent);
    border-radius: 50%; margin: 0 auto 14px; animation: spin .9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error { background: #fff0f0; color: #b42318; padding: 18px; border-radius: 14px; border: 1px solid #ffd0d0; }
  .error .detail { margin: 6px 0 0; font-size: .85rem; opacity: .75; word-break: break-word; }
  .ghost {
    margin-top: 12px; background: #fff; color: var(--accent-dark); border: 2px solid var(--accent);
    padding: 8px 16px; border-radius: 10px; font-weight: 700; cursor: pointer;
  }
  .ghost:hover { background: var(--soft); }

  /* ---------- recipe card ---------- */
  .recipe { background: var(--card); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); animation: rise .5s ease; }
  @keyframes rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
  .head {
    position: relative; height: 300px; overflow: hidden; display: flex; align-items: flex-end;
    background: linear-gradient(135deg, #ffd8a8, #ffa94d);
  }
  .emoji { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 7rem; opacity: .55; }
  .photo-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; transition: opacity .6s; }
  .photo-img.show { opacity: 1; }
  .shade { position: absolute; inset: 0; background: linear-gradient(to top, rgba(20, 10, 0, .75) 0%, rgba(20, 10, 0, .15) 55%, transparent 100%); }
  .title {
    position: relative; color: #fff; margin: 0; padding: 24px 26px; line-height: 1.15;
    font-family: "Fraunces", Georgia, serif; font-size: clamp(1.6rem, 4.5vw, 2.3rem);
    text-shadow: 0 2px 12px rgba(0, 0, 0, .35);
  }
  .credit {
    position: absolute; right: 12px; top: 10px; font-size: .72rem; color: #fff;
    background: rgba(0, 0, 0, .35); padding: 2px 9px; border-radius: 999px;
  }
  .credit:empty { display: none; }

  .body { padding: 24px 26px 28px; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .pill { background: var(--soft); color: var(--accent-dark); padding: 6px 14px; border-radius: 999px; font-weight: 500; font-size: .92rem; }
  .desc { margin: 0 0 14px; color: var(--muted); }
  .safe { background: #eef7f0; color: #276738; padding: 10px 14px; border-radius: 12px; font-size: .9rem; margin-bottom: 6px; }
  .safe small { display: block; opacity: .8; margin-top: 2px; }
  .cols { display: grid; grid-template-columns: 1fr 1.4fr; gap: 30px; margin-top: 22px; }
  @media (max-width: 700px) { .cols { grid-template-columns: 1fr; } }
  h3 { font-family: "Fraunces", Georgia, serif; font-size: 1.3rem; margin: 0 0 12px; }

  ul.ing { list-style: none; padding: 0; margin: 0; }
  ul.ing li { border-bottom: 1px dashed var(--line); }
  ul.ing label {
    display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; margin: 0; cursor: pointer;
    font-size: 1rem; font-weight: 400; color: var(--ink); text-transform: none; letter-spacing: 0;
  }
  ul.ing input { margin-top: 5px; accent-color: var(--accent); width: 17px; height: 17px; flex: none; }
  ul.ing li.done span { text-decoration: line-through; color: var(--muted); }

  ol.steps { list-style: none; counter-reset: s; padding: 0; margin: 0; }
  ol.steps li { counter-increment: s; position: relative; padding: 0 0 18px 48px; cursor: pointer; transition: opacity .2s; }
  ol.steps li::before {
    content: counter(s); position: absolute; left: 0; top: 0; width: 32px; height: 32px; border-radius: 50%;
    background: var(--accent); color: #fff; font-weight: 700; display: flex; align-items: center; justify-content: center;
  }
  ol.steps li.done { opacity: .45; }
  ol.steps li.done::before { background: var(--ok); content: "✓"; }
  .hint { font-size: .8rem; color: var(--muted); margin: -4px 0 12px; }

  .extra { margin-top: 22px; background: #fffaf3; border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; }
  .extra ul { margin: 0; padding-left: 20px; }

  .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; padding-top: 20px; border-top: 1px solid var(--line); }
  .act {
    background: #fff; color: var(--ink); border: 2px solid var(--line); padding: 10px 16px; border-radius: 12px;
    font-weight: 500; cursor: pointer; transition: border-color .15s, background .15s;
  }
  .act:hover { border-color: var(--accent); background: #fffaf3; }

  footer { text-align: center; color: var(--muted); font-size: .85rem; margin-top: 30px; }

  @media print {
    .hero, .panel, .actions, footer, .hint, .credit { display: none !important; }
    body { background: #fff; }
    .wrap { margin: 0; }
    .recipe { box-shadow: none; }
  }
</style>
</head>
<body>
  <div class="hero">
    <h1>👨‍🍳 ChefGPT</h1>
    <p>Tell me what you're craving. I'll write the recipe.</p>
  </div>

  <div class="wrap">
    <div class="panel">
      <div class="fields">
        <div>
          <label for="food">What do you want to cook?</label>
          <input class="field" id="food" placeholder="e.g. chicken biryani" autocomplete="off">
        </div>
        <div>
          <label for="cons">Dietary constraints (optional)</label>
          <input class="field" id="cons" placeholder="e.g. no nuts, vegetarian" autocomplete="off">
        </div>
      </div>
      <div class="chips">
        <button type="button" class="chip" data-f="Chicken pasta">🍝 Chicken pasta</button>
        <button type="button" class="chip" data-f="Veggie curry">🍛 Veggie curry</button>
        <button type="button" class="chip" data-f="Fluffy pancakes">🥞 Pancakes</button>
        <button type="button" class="chip" data-f="Beef tacos">🌮 Tacos</button>
        <button type="button" class="chip" data-f="Margherita pizza">🍕 Pizza</button>
        <button type="button" class="chip" data-f="Chocolate cake">🍰 Cake</button>
      </div>
      <div class="chips" id="recent" hidden></div>
      <button type="button" class="go" id="go">Get recipe</button>
    </div>
    <div id="out" aria-live="polite"></div>
    <footer>Made with ChefGPT · Powered by Gemini</footer>
  </div>

<script>
  const $ = (id) => document.getElementById(id);
  const out = $("out");

  const EMOJI = [
    ["pasta","🍝"],["spaghetti","🍝"],["noodle","🍜"],["ramen","🍜"],["pizza","🍕"],["taco","🌮"],["burger","🍔"],
    ["biryani","🍛"],["curry","🍛"],["rice","🍚"],["salad","🥗"],["soup","🍲"],["cake","🍰"],["chocolate","🍫"],
    ["pancake","🥞"],["egg","🍳"],["chicken","🍗"],["beef","🥩"],["steak","🥩"],["fish","🐟"],["salmon","🐟"],
    ["prawn","🍤"],["shrimp","🍤"],["sushi","🍣"],["bread","🍞"],["sandwich","🥪"],["cookie","🍪"],
    ["ice cream","🍨"],["potato","🥔"]
  ];
  const LOADING_MSGS = ["Chopping the onions…", "Heating up the pan…", "Tasting for salt…", "Plating it up…"];
  const RECENT_KEY = "chefgpt_recent";
  const EXTRA_RE = /tip|note|substitut/i;
  let loadTimer = null;

  function emojiFor(text) {
    text = text.toLowerCase();
    for (let i = 0; i < EMOJI.length; i++) if (text.indexOf(EMOJI[i][0]) !== -1) return EMOJI[i][1];
    return "🍽️";
  }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function prettyKey(k) { return k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()); }

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
  function metaPill(k, v) {
    const key = k.toLowerCase();
    const num = typeof v === "number";
    if (/calorie|kcal/.test(key)) return "🔥 " + v + " kcal" + (/per/.test(key) ? " / serving" : "");
    if (/serv/.test(key)) return "👥 " + v + (num ? " servings" : "");
    if (/time|minute/.test(key)) return "⏱ " + v + (num ? " min" : "");
    return prettyKey(k) + ": " + v;
  }

  // ---------- photo ----------
  function photoQueries(title, food) {
    const t = (title || "").trim();
    const paren = t.match(/\(([^)]+)\)/);
    const base = t.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").trim();
    const list = [base];
    if (paren) list.push(paren[1].trim());
    list.push(food);
    const words = (paren ? paren[1] : (base || food)).split(/\s+/).filter(Boolean);
    if (words.length > 2) list.push(words.slice(-2).join(" "));
    const seen = {};
    return list.filter((q) => {
      const k = (q || "").toLowerCase().trim();
      if (!k || seen[k]) return false;
      seen[k] = true;
      return true;
    }).slice(0, 4);
  }
  function loadPhoto(title, food, img, credit) {
    const params = new URLSearchParams();
    photoQueries(title, food).forEach((q) => params.append("q", q));
    fetch("/photo?" + params.toString())
      .then((r) => r.json())
      .then((d) => {
        if (!d || !d.url) return;
        img.onload = () => { img.classList.add("show"); credit.textContent = "Photo: Pixabay"; };
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
      const b = el("button", "chip recent-chip", "↺ " + f);
      b.type = "button";
      b.addEventListener("click", () => { $("food").value = f; $("food").focus(); });
      box.appendChild(b);
    });
  }

  // ---------- loading and errors ----------
  function showLoading() {
    let i = 0;
    out.innerHTML = '<div class="loading"><div class="spinner"></div><div id="loadmsg"></div><small>This can take up to a minute</small></div>';
    $("loadmsg").textContent = LOADING_MSGS[0];
    clearInterval(loadTimer);
    loadTimer = setInterval(() => {
      i = (i + 1) % LOADING_MSGS.length;
      const n = $("loadmsg");
      if (n) n.textContent = LOADING_MSGS[i];
    }, 2500);
  }
  function showError(msg, detail) {
    out.innerHTML = "";
    const box = el("div", "error");
    box.appendChild(el("strong", "", "😕 " + msg));
    if (detail) box.appendChild(el("p", "detail", String(detail).slice(0, 200)));
    const retry = el("button", "ghost", "Try again");
    retry.type = "button";
    retry.addEventListener("click", go);
    box.appendChild(retry);
    out.appendChild(box);
  }

  // ---------- recipe card ----------
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

    const card = el("article", "recipe");

    // header: emoji placeholder, then the photo fades in over it
    const head = el("div", "head");
    head.appendChild(el("div", "emoji", emojiFor(food + " " + title)));
    const img = document.createElement("img");
    img.className = "photo-img";
    img.alt = title;
    head.appendChild(img);
    head.appendChild(el("div", "shade"));
    head.appendChild(el("h2", "title", title));
    const credit = el("span", "credit", "");
    head.appendChild(credit);
    card.appendChild(head);
    loadPhoto(title, food, img, credit);

    const body = el("div", "body");

    // quick facts
    const meta = el("div", "meta");
    const metaTexts = [];
    let desc = "";
    keys.forEach((k) => {
      const v = r[k];
      if (k === titleKey || EXTRA_RE.test(k)) return;
      if (typeof v === "number" || (typeof v === "string" && v.length <= 40)) {
        const t = metaPill(k, v);
        metaTexts.push(t);
        meta.appendChild(el("span", "pill", t));
      } else if (typeof v === "string" && !desc) {
        desc = v;
      }
    });
    if (meta.children.length) body.appendChild(meta);
    if (desc) body.appendChild(el("p", "desc", desc));

    // constraints
    const c = findConstraints(data);
    if (c) {
      const bits = [];
      if (c.allergens && c.allergens.length) bits.push("avoiding " + c.allergens.join(", ").replace(/_/g, " "));
      if (c.diets && c.diets.length) bits.push(c.diets.join(", ").replace(/_/g, " "));
      if (bits.length) {
        const safe = el("div", "safe", "Your constraints: " + bits.join(" · "));
        safe.appendChild(el("small", "", "Always double-check ingredient labels if you have an allergy."));
        body.appendChild(safe);
      }
    }

    // ingredients + method
    const ings = ingKey ? r[ingKey].map(itemText) : [];
    const steps = stepKey ? r[stepKey].map(itemText) : [];
    const cols = el("div", "cols");
    if (ings.length) {
      const left = el("div");
      left.appendChild(el("h3", "", "Ingredients"));
      left.appendChild(el("p", "hint", "Tick items off as you gather them"));
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
      right.appendChild(el("p", "hint", "Tap a step to mark it done"));
      const ol = el("ol", "steps");
      steps.forEach((text) => {
        const li = el("li", "", text);
        li.addEventListener("click", () => li.classList.toggle("done"));
        ol.appendChild(li);
      });
      right.appendChild(ol);
      cols.appendChild(right);
    }
    body.appendChild(cols);

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
      body.appendChild(box);
    });

    // actions
    const actions = el("div", "actions");
    const copyBtn = el("button", "act", "📋 Copy recipe");
    const printBtn = el("button", "act", "🖨 Print");
    const againBtn = el("button", "act", "🍳 Cook something else");
    [copyBtn, printBtn, againBtn].forEach((b) => { b.type = "button"; actions.appendChild(b); });
    copyBtn.addEventListener("click", async () => {
      const text = [title, metaTexts.join(" · "), "", "INGREDIENTS"]
        .concat(ings.map((x) => "- " + x), ["", "METHOD"], steps.map((x, i) => (i + 1) + ". " + x))
        .join("\n");
      try { await navigator.clipboard.writeText(text); copyBtn.textContent = "✅ Copied!"; }
      catch (e) { copyBtn.textContent = "Couldn't copy"; }
      setTimeout(() => { copyBtn.textContent = "📋 Copy recipe"; }, 2000);
    });
    printBtn.addEventListener("click", () => window.print());
    againBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
      $("food").focus();
      $("food").select();
    });
    body.appendChild(actions);

    card.appendChild(body);
    out.appendChild(card);
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- go! ----------
  async function go() {
    const food = $("food").value.trim();
    const btn = $("go");
    if (!food) { $("food").focus(); return; }
    showLoading();
    btn.disabled = true;
    btn.textContent = "Cooking…";
    try {
      const res = await fetch("/recipe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: food, constraints: $("cons").value })
      });
      let data = null;
      try { data = await res.json(); } catch (e) {}
      clearInterval(loadTimer);
      if (res.ok && data) {
        saveRecent(food);
        render(data, food);
      } else {
        showError("ChefGPT couldn't make that recipe right now. The AI service may be busy, so please try again in a moment.", data && data.detail);
      }
    } catch (e) {
      clearInterval(loadTimer);
      showError("Couldn't reach the server. Check your connection and try again.", e);
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