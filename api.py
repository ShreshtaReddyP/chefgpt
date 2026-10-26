from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from chefgpt.pipeline import run

app = FastAPI(title="ChefGPT")


class RecipeRequest(BaseModel):
    request: str
    constraints: str = ""


PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ChefGPT</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Fraunces:wght@600;800&display=swap" rel="stylesheet">
<style>
  :root {
    --cream: #fff8ef; --card: #ffffff; --ink: #2b2118; --muted: #8a7968;
    --accent: #e8590c; --accent-dark: #c2410c; --soft: #ffe8d1; --green: #2f9e44;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--cream); color: var(--ink);
    font-family: "DM Sans", Arial, sans-serif; line-height: 1.55;
  }
  .hero {
    background: linear-gradient(135deg, #ff9f43 0%, #e8590c 100%);
    color: #fff; text-align: center; padding: 56px 20px 90px; position: relative; overflow: hidden;
  }
  .hero h1 { font-family: "Fraunces", Georgia, serif; font-size: 3rem; margin: 0 0 6px; letter-spacing: -1px; }
  .hero p { margin: 0; opacity: .92; font-size: 1.1rem; }
  .float { position: absolute; font-size: 2.6rem; opacity: .25; animation: bob 6s ease-in-out infinite; }
  .float:nth-child(1) { left: 6%; top: 18%; } .float:nth-child(2) { left: 18%; top: 62%; animation-delay: 1s; }
  .float:nth-child(3) { right: 8%; top: 20%; animation-delay: 2s; } .float:nth-child(4) { right: 20%; top: 65%; animation-delay: 3s; }
  @keyframes bob { 0%,100% { transform: translateY(0) rotate(-6deg); } 50% { transform: translateY(-14px) rotate(6deg); } }

  .wrap { max-width: 760px; margin: -56px auto 60px; padding: 0 16px; position: relative; }
  .panel {
    background: var(--card); border-radius: 20px; padding: 24px;
    box-shadow: 0 12px 40px rgba(60, 30, 0, .12);
  }
  label { display: block; font-weight: 700; font-size: .85rem; margin: 0 0 6px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
  input {
    width: 100%; padding: 14px 16px; font: inherit; font-size: 1.05rem; border: 2px solid #f1e3d3;
    border-radius: 12px; background: #fffdfa; margin-bottom: 16px; outline: none; transition: border .15s;
  }
  input:focus { border-color: var(--accent); }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
  .chip {
    border: none; background: var(--soft); color: var(--accent-dark); padding: 7px 14px;
    border-radius: 999px; font: inherit; font-size: .9rem; cursor: pointer; transition: transform .1s, background .15s;
  }
  .chip:hover { background: #ffd8b0; transform: translateY(-1px); }
  .go {
    width: 100%; border: none; background: var(--accent); color: #fff; font: inherit; font-weight: 700;
    font-size: 1.1rem; padding: 15px; border-radius: 12px; cursor: pointer; transition: background .15s, transform .1s;
  }
  .go:hover { background: var(--accent-dark); } .go:active { transform: scale(.99); } .go:disabled { opacity: .6; cursor: wait; }

  #out { margin-top: 28px; }
  .loading { text-align: center; padding: 40px 10px; color: var(--muted); }
  .spinner {
    width: 44px; height: 44px; border: 5px solid var(--soft); border-top-color: var(--accent);
    border-radius: 50%; margin: 0 auto 14px; animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error { background: #fff0f0; color: #b42318; padding: 16px; border-radius: 12px; border: 1px solid #ffd0d0; }

  .recipe { background: var(--card); border-radius: 20px; overflow: hidden; box-shadow: 0 12px 40px rgba(60, 30, 0, .12); animation: rise .5s ease; }
  @keyframes rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
  .photo {
    height: 260px; background: linear-gradient(135deg, #ffd8a8, #ffa94d); display: flex;
    align-items: center; justify-content: center; font-size: 6rem; position: relative; overflow: hidden;
  }
  .photo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .body { padding: 26px; }
  .body h2 { font-family: "Fraunces", Georgia, serif; font-size: 2rem; margin: 0 0 14px; line-height: 1.15; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .pill { background: var(--soft); color: var(--accent-dark); padding: 6px 14px; border-radius: 999px; font-weight: 500; font-size: .9rem; }
  .safe { background: #e6f7ea; color: var(--green); padding: 10px 14px; border-radius: 12px; font-size: .92rem; font-weight: 500; margin-bottom: 8px; }
  .cols { display: grid; grid-template-columns: 1fr 1.4fr; gap: 28px; margin-top: 22px; }
  @media (max-width: 640px) { .cols { grid-template-columns: 1fr; } .hero h1 { font-size: 2.3rem; } }
  h3 { font-family: "Fraunces", Georgia, serif; font-size: 1.3rem; margin: 0 0 12px; }
  ul.ing { list-style: none; padding: 0; margin: 0; }
  ul.ing li { padding: 9px 0; border-bottom: 1px dashed #efdfce; }
  ul.ing li::before { content: "🥄 "; font-size: .85rem; }
  ol.steps { list-style: none; counter-reset: s; padding: 0; margin: 0; }
  ol.steps li { counter-increment: s; position: relative; padding: 0 0 16px 46px; }
  ol.steps li::before {
    content: counter(s); position: absolute; left: 0; top: 0; width: 32px; height: 32px; border-radius: 50%;
    background: var(--accent); color: #fff; font-weight: 700; display: flex; align-items: center; justify-content: center;
  }
  footer { text-align: center; color: var(--muted); font-size: .85rem; margin-top: 30px; }
</style>
</head>
<body>
  <div class="hero">
    <span class="float">🍝</span><span class="float">🥗</span><span class="float">🍕</span><span class="float">🍰</span>
    <h1>ChefGPT</h1>
    <p>Tell me what you're craving. I'll write the recipe.</p>
  </div>

  <div class="wrap">
    <div class="panel">
      <label for="food">What do you want to cook?</label>
      <input id="food" placeholder="e.g. chicken pasta" autocomplete="off">
      <label for="cons">Dietary constraints (optional)</label>
      <input id="cons" placeholder="e.g. no nuts, vegetarian, under 500 calories" autocomplete="off">
      <div class="chips">
        <button class="chip" data-f="Chicken pasta">🍝 Chicken pasta</button>
        <button class="chip" data-f="Veggie curry">🍛 Veggie curry</button>
        <button class="chip" data-f="Fluffy pancakes">🥞 Pancakes</button>
        <button class="chip" data-f="Beef tacos">🌮 Tacos</button>
        <button class="chip" data-f="Margherita pizza">🍕 Pizza</button>
        <button class="chip" data-f="Chocolate cake">🍰 Cake</button>
      </div>
      <button class="go" id="go">Get recipe</button>
    </div>
    <div id="out"></div>
    <footer>Made with ChefGPT · Powered by Gemini</footer>
  </div>

<script>
  var EMOJI = [
    ["pasta","🍝"],["spaghetti","🍝"],["noodle","🍜"],["ramen","🍜"],["pizza","🍕"],["taco","🌮"],["burger","🍔"],
    ["curry","🍛"],["rice","🍚"],["salad","🥗"],["soup","🍲"],["cake","🍰"],["chocolate","🍫"],["pancake","🥞"],
    ["egg","🍳"],["chicken","🍗"],["beef","🥩"],["steak","🥩"],["fish","🐟"],["salmon","🐟"],["sushi","🍣"],
    ["bread","🍞"],["sandwich","🥪"],["cookie","🍪"],["ice cream","🍨"],["shrimp","🍤"],["potato","🥔"]
  ];
  function emojiFor(text) {
    text = text.toLowerCase();
    for (var i = 0; i < EMOJI.length; i++) if (text.indexOf(EMOJI[i][0]) !== -1) return EMOJI[i][1];
    return "🍽️";
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function prettyKey(k) { return k.replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }

  // The recipe object is whichever nested object has an "ingredients" list.
  function findRecipe(o) {
    if (!o || typeof o !== "object" || Array.isArray(o)) return null;
    if (Object.keys(o).some(function (k) { return /ingredient/i.test(k) && Array.isArray(o[k]); })) return o;
    var vals = Object.values(o);
    for (var i = 0; i < vals.length; i++) { var r = findRecipe(vals[i]); if (r) return r; }
    return null;
  }
  function findConstraints(o) {
    if (!o || typeof o !== "object" || Array.isArray(o)) return null;
    if (Array.isArray(o.allergens) || Array.isArray(o.diets)) return o;
    var vals = Object.values(o);
    for (var i = 0; i < vals.length; i++) { var r = findConstraints(vals[i]); if (r) return r; }
    return null;
  }
  function itemText(x) {
    if (typeof x === "string") return x;
    if (x && typeof x === "object") {
      var name = x.name || x.item || x.ingredient;
      if (name) {
        var q = x.quantity !== undefined ? x.quantity : (x.amount !== undefined ? x.amount : x.qty);
        return [q, x.unit, name].filter(function (v) { return v !== undefined && v !== null && v !== ""; }).join(" ");
      }
      var t = x.text || x.step || x.instruction || x.description;
      if (t) return t;
      return Object.values(x).join(" ");
    }
    return String(x);
  }

  function render(data, food) {
    var out = document.getElementById("out");
    out.innerHTML = "";
    var r = findRecipe(data);
    if (!r) {
      var pre = el("pre", "error", JSON.stringify(data, null, 2));
      out.appendChild(pre);
      return;
    }
    var keys = Object.keys(r);
    var titleKey = keys.find(function (k) { return /^(title|name|dish)$/i.test(k); });
    var ingKey = keys.find(function (k) { return /ingredient/i.test(k) && Array.isArray(r[k]); });
    var stepKey = keys.find(function (k) { return /(step|instruction|direction|method)/i.test(k) && Array.isArray(r[k]); });

    var card = el("div", "recipe");

    var photo = el("div", "photo", emojiFor(food + " " + (titleKey ? r[titleKey] : "")));
    var img = document.createElement("img");
    var kw = food.toLowerCase().replace(/[^a-z ]/g, "").trim().split(/\s+/).slice(0, 2).join(",") || "food";
    img.alt = food;
    img.src = "https://loremflickr.com/800/450/" + encodeURIComponent(kw) + ",food?lock=" + Math.floor(Math.random() * 1000);
    img.onerror = function () { img.remove(); };   // falls back to the emoji banner
    photo.appendChild(img);
    card.appendChild(photo);

    var body = el("div", "body");
    body.appendChild(el("h2", "", titleKey ? r[titleKey] : food));

    var meta = el("div", "meta");
    keys.forEach(function (k) {
      var v = r[k];
      if (k === titleKey) return;
      if (typeof v === "string" || typeof v === "number") meta.appendChild(el("span", "pill", prettyKey(k) + ": " + v));
    });
    if (meta.children.length) body.appendChild(meta);

    var c = findConstraints(data);
    if (c) {
      var bits = [];
      if (c.allergens && c.allergens.length) bits.push("free of " + c.allergens.join(", ").replace(/_/g, " "));
      if (c.diets && c.diets.length) bits.push(c.diets.join(", "));
      if (bits.length) body.appendChild(el("div", "safe", "✅ Checked against your constraints: " + bits.join(" · ")));
    }

    var cols = el("div", "cols");
    if (ingKey) {
      var left = el("div");
      left.appendChild(el("h3", "", "Ingredients"));
      var ul = el("ul", "ing");
      r[ingKey].forEach(function (x) { ul.appendChild(el("li", "", itemText(x))); });
      left.appendChild(ul);
      cols.appendChild(left);
    }
    if (stepKey) {
      var right = el("div");
      right.appendChild(el("h3", "", "Method"));
      var ol = el("ol", "steps");
      r[stepKey].forEach(function (x) { ol.appendChild(el("li", "", itemText(x))); });
      right.appendChild(ol);
      cols.appendChild(right);
    }
    body.appendChild(cols);
    card.appendChild(body);
    out.appendChild(card);
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function go() {
    var food = document.getElementById("food").value.trim();
    var out = document.getElementById("out");
    var btn = document.getElementById("go");
    if (!food) { document.getElementById("food").focus(); return; }
    out.innerHTML = '<div class="loading"><div class="spinner"></div>Cooking up your recipe... this can take up to 30 seconds</div>';
    btn.disabled = true;
    try {
      var res = await fetch("/recipe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: food, constraints: document.getElementById("cons").value })
      });
      var data = await res.json();
      if (res.ok) render(data, food);
      else out.innerHTML = '<div class="error">😕 ' + (data.detail || "Something went wrong") + "</div>";
    } catch (e) {
      out.innerHTML = '<div class="error">😕 ' + e + "</div>";
    }
    btn.disabled = false;
  }

  document.getElementById("go").addEventListener("click", go);
  document.getElementById("food").addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
  document.getElementById("cons").addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
  document.querySelectorAll(".chip").forEach(function (b) {
    b.addEventListener("click", function () { document.getElementById("food").value = b.dataset.f; document.getElementById("food").focus(); });
  });
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