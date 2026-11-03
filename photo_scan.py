"""Photo scan feature for ChefGPT: upload a photo of your ingredients, get recipe choices.

Add to api.py (see the 4 edits listed in the instructions):
    from photo_scan import router as photo_router
    app.include_router(photo_router)
    <link rel="stylesheet" href="/photo-scan.css">      (inside <head> of PAGE)
    <script src="/photo-scan.js"></script>              (after the main <script> in PAGE)

Picking a recipe fills the existing "I'd like to cook" box and presses "Get recipe",
so the normal pipeline (constraint parsing, recipe, audit, repair loop) runs on it.
"""
import base64
import binascii
import os
import time
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter()

MODEL = os.environ.get(
    "CHEFGPT_MODEL",
    os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
)
FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash").split(",")
    if m.strip()
]
RETRIES_PER_MODEL = 1
# Per-call limit in milliseconds. Photo + recipe suggestions is a heavy request, so 30s was too tight.
TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "60000"))
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 6 * 1024 * 1024


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    image_base64: Optional[str] = None  # photo scan
    mime_type: str = "image/jpeg"
    ingredients: List[str] = Field(default_factory=list)  # refresh without a photo
    constraints: str = ""
    cuisine: str = "Any Cuisine"


class RecipeIdea(BaseModel):
    name: str
    time_min: int = 30
    difficulty: Literal["Easy", "Medium", "Hard"] = "Easy"
    uses: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    why: str = ""


class ScanResult(BaseModel):
    ingredients: List[str] = Field(default_factory=list)
    recipes: List[RecipeIdea] = Field(default_factory=list)
    note: str = ""


# ---------------------------------------------------------------------------
# Gemini call (same google-genai library and GEMINI_API_KEY as the rest of the app)
# ---------------------------------------------------------------------------
def _prompt(constraints: str, cuisine: str, from_photo: bool, ingredients: List[str]) -> str:
    diet = (
        f"Dietary needs: {constraints}. Never suggest a dish or ingredient that breaks these."
        if constraints
        else "No dietary restrictions."
    )
    if from_photo:
        source = (
            "Look at the photo and list every edible ingredient you can clearly identify "
            "(plain common names, no brands, no duplicates). Ignore non-food objects."
        )
    else:
        source = (
            "The user's ingredients are: " + ", ".join(ingredients) + ". "
            'Return exactly this list as "ingredients".'
        )
    cuisine_text = (
        f"Preferred cuisine: {cuisine}. Respect this cuisine as closely as possible."
        if cuisine and cuisine.strip().lower() != "any cuisine"
        else "Any cuisine is acceptable; choose practical variety."
    )
    return "\n".join(
        [
            "You are the pantry scanner for ChefGPT, a recipe app.",
            source,
            cuisine_text,
            "Then suggest exactly 3 clearly different recipes that mostly use those ingredients, "
            "assuming only basic staples (salt, oil, water, common spices) are on hand.",
            '"name" must be a plain dish name that works as a recipe request, like "Tomato egg curry".',
            '"uses" lists which of the identified ingredients the dish uses.',
            '"missing" lists extra non-staple items needed. Keep it short, ideally empty.',
            '"why" is one short sentence on why the dish suits these ingredients.',
            '"time_min" is total minutes. "difficulty" is Easy, Medium or Hard.',
            diet,
            'If the photo shows no food, return empty lists and explain in one line in "note".',
        ]
    )


def _scan(req: ScanRequest) -> ScanResult:
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not set on the server.")

    constraints = " ".join(req.constraints.split())[:300]
    contents: list = []
    if req.image_base64:
        if req.mime_type not in ALLOWED_MIME:
            raise HTTPException(status_code=422, detail="Please upload a JPG, PNG or WebP photo.")
        try:
            raw = base64.b64decode(req.image_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="The photo could not be read. Try another one.")
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="That photo is too large. Try a smaller one.")
        contents.append(types.Part.from_bytes(data=raw, mime_type=req.mime_type))
        contents.append(_prompt(constraints, req.cuisine, True, []))
    else:
        items = [" ".join(i.split())[:60] for i in req.ingredients if i.strip()][:30]
        if not items:
            raise HTTPException(status_code=422, detail="Add a photo or at least one ingredient.")
        contents.append(_prompt(constraints, req.cuisine, False, items))

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ScanResult,
        temperature=0.7,
    )

    last_err: Exception = RuntimeError("No model available")
    for model in [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]:
        for attempt in range(RETRIES_PER_MODEL + 1):
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                return ScanResult.model_validate_json(resp.text)
            except Exception as e:
                last_err = e
                text = str(e)
                busy = any(c in text for c in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
                gone = "404" in text or "NOT_FOUND" in text
                timed_out = (
                    "timed out" in text.lower()
                    or "timeout" in text.lower()
                    or "deadline_exceeded" in text.lower()
                )
                if gone or timed_out:  # move on to the next model instead of waiting again
                    break
                if not busy:
                    raise
                if attempt < RETRIES_PER_MODEL:
                    time.sleep(1.5 * (attempt + 1))
    raise last_err


@router.post("/scan")
def scan(body: ScanRequest):
    try:
        result = _scan(body)
    except HTTPException:
        raise
    except Exception as e:  # network, quota, bad model output
        text = str(e)
        # Log the underlying Gemini error in Render so the generic UI message
        # does not hide whether this is overload, quota, timeout, or another issue.
        print(f"[PHOTO SCAN GEMINI ERROR] {type(e).__name__}: {text}", flush=True)
        lowered = text.lower()
        if "429" in text or "resource_exhausted" in lowered:
            detail = "Gemini API quota or rate limit reached. Check your Google AI Studio quota and try again later."
        elif "503" in text or "unavailable" in lowered:
            detail = "Gemini is temporarily unavailable or overloaded. Please try again shortly."
        elif "timed out" in lowered or "timeout" in lowered or "deadline_exceeded" in lowered:
            detail = "Gemini took too long to respond. Please try again with a smaller photo."
        else:
            detail = text[:300] or "The scan failed. Please try again."
        raise HTTPException(status_code=503, detail=detail)
    result.recipes = result.recipes[:3]
    return result


# ---------------------------------------------------------------------------
# Front-end assets. They reuse the page's own CSS variables and button classes,
# so the panel looks like part of ChefGPT.
# ---------------------------------------------------------------------------
CSS = r"""
/* ChefGPT: playful pantry-game visual system */
.pk {
  --pk-night: #171326; --pk-panel: #211b36; --pk-panel-2: #2b2343;
  --pk-peach: #ffb58e; --pk-coral: #ff7f78; --pk-mint: #a7f0cf;
  --pk-lilac: #c7b7ff; --pk-cream: #fff5e9; --pk-dim: #bcb3ce;
  position: relative; isolation: isolate; overflow: hidden;
  padding: clamp(22px, 4vw, 38px); margin: 0 0 26px;
  border: 1px solid rgba(199,183,255,.25); border-radius: 28px;
  color: var(--pk-cream); background: radial-gradient(ellipse at 8% 0%, #44335d 0, transparent 38%), linear-gradient(145deg,var(--pk-panel),var(--pk-night) 75%);
  box-shadow: 0 24px 70px rgba(12,8,25,.3);
}
.pk:before { content:"✦"; position:absolute; right:5%; top:2%; color:var(--pk-peach); font-size:clamp(45px,7vw,90px); opacity:.45; transform:rotate(12deg); pointer-events:none; }
.pk-title { font-family:var(--serif); font-size:clamp(1.6rem,3vw,2.25rem); line-height:1.12; letter-spacing:-.035em; margin:0 0 8px; color:var(--pk-cream); }
.pk-sub { color:var(--pk-dim); font-size:.92rem; margin:0 0 22px; }
.pk-row { display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:14px; }
.pk-file { position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }
.pk-drop { position:relative; border:1.5px dashed rgba(167,240,207,.6); border-radius:22px; padding:clamp(24px,4vw,42px) 18px; text-align:center; background:linear-gradient(135deg,rgba(167,240,207,.08),rgba(199,183,255,.09)); transition:transform .25s,border-color .25s,background .25s; }
.pk-drop:after { content:"✧  ✦  ✧"; display:block; margin-top:14px; color:var(--pk-lilac); letter-spacing:12px; opacity:.65; }
.pk-drop.over { border-color:var(--pk-peach); background:rgba(255,181,142,.16); transform:scale(1.01); }
.pk-pick { display:inline-block; cursor:pointer; color:var(--pk-cream); background:var(--pk-panel-2); border:1px solid rgba(255,245,233,.16); border-radius:999px; padding:12px 19px; font-weight:700; transition:transform .2s,filter .2s; }
.pk-pick:hover { transform:translateY(-2px); filter:brightness(1.15); }
.pk-file:focus-visible + .pk-pick { outline:2px solid var(--pk-peach); outline-offset:3px; }
.pk-pick.pk-primary { color:#261b35; background:linear-gradient(135deg,var(--pk-peach),var(--pk-coral)); border:0; box-shadow:0 8px 25px rgba(255,127,120,.22); }
.pk-thumb { width:84px; height:84px; object-fit:cover; border-radius:18px; border:2px solid var(--pk-mint); box-shadow:0 0 0 5px rgba(167,240,207,.1); }
.pk .go { border:0; border-radius:999px; padding:12px 22px; color:#21152d; background:var(--pk-mint); font-weight:800; box-shadow:0 8px 25px rgba(167,240,207,.18); }
.pk .go:hover { transform:translateY(-2px); filter:brightness(1.05); }
.pk .go:disabled { opacity:.55; }
.pk-remove { color:var(--pk-dim); background:transparent; border:0; cursor:pointer; font:inherit; text-decoration:underline; padding:8px; }
.pk-hint { color:var(--pk-dim); margin:14px 0 0; font-size:.82rem; }
.pk-diet { display:flex; flex-wrap:wrap; align-items:center; gap:12px; margin-top:16px; }
.pk-diet-label { color:var(--pk-dim); font-size:.88rem; font-weight:650; }
.pk-diet-input,.pk-cuisine { font:inherit; font-size:.9rem; flex:1 1 14rem; max-width:25rem; padding:12px 15px; border-radius:14px; color:var(--pk-cream); background:#171326; border:1px solid rgba(199,183,255,.25); outline:none; }
.pk-diet-input::placeholder { color:#857b9d; }
.pk-diet-input:focus,.pk-cuisine:focus { border-color:var(--pk-mint); box-shadow:0 0 0 3px rgba(167,240,207,.1); }
.pk-cuisine option { color:var(--pk-cream); background:var(--pk-night); }
.pk-label { margin:24px 0 11px; color:var(--pk-peach); font-size:.78rem; font-weight:800; text-transform:uppercase; letter-spacing:.12em; }
.pk-chips { display:flex; flex-wrap:wrap; align-items:center; gap:9px; }
.pk-chip { display:inline-flex; align-items:center; gap:7px; padding:8px 9px 8px 13px; color:#e8e0ff; background:rgba(199,183,255,.12); border:1px solid rgba(199,183,255,.24); border-radius:999px; font-size:.86rem; animation:pk-pop .35s both; }
.pk-chip button { color:var(--pk-peach); border:0; background:none; cursor:pointer; font-size:1.15rem; line-height:1; padding:0 4px; }
.pk-add { width:12rem; padding:9px 5px; font:inherit; color:var(--pk-cream); background:transparent; border:0; border-bottom:1px dashed var(--pk-lilac); outline:none; }
.pk-add::placeholder { color:var(--pk-dim); }
.pk-add:focus { border-bottom-color:var(--pk-mint); }
.pk-refresh { margin-top:16px; }
.pk-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
.pk-card { min-width:0; display:flex; flex-direction:column; gap:10px; padding:20px; border:1px solid rgba(199,183,255,.22); border-radius:22px; background:linear-gradient(150deg,rgba(255,255,255,.07),rgba(255,255,255,.025)); box-shadow:0 12px 28px rgba(8,5,18,.16); transition:transform .25s,border-color .25s,box-shadow .25s; animation:pk-rise .5s both; }
.pk-card:nth-child(2) { animation-delay:.08s; } .pk-card:nth-child(3) { animation-delay:.16s; }
.pk-card:hover { transform:translateY(-6px) rotate(-.4deg); border-color:rgba(167,240,207,.55); box-shadow:0 20px 40px rgba(8,5,18,.25); }
.pk-card h4 { margin:0; color:var(--pk-cream); font-family:var(--serif); font-size:1.25rem; line-height:1.2; letter-spacing:-.02em; }
.pk-facts { display:flex; gap:8px; flex-wrap:wrap; color:var(--pk-mint); font-size:.8rem; font-weight:750; }
.pk-facts span { padding:5px 9px; border-radius:999px; background:rgba(167,240,207,.09); }
.pk-why { margin:0; color:var(--pk-dim); font-size:.88rem; line-height:1.5; }
.pk-uses,.pk-need { margin:0; font-size:.78rem; line-height:1.5; color:#d4c9eb; }
.pk-need { color:var(--pk-peach); }
.pk-card .act { margin-top:auto; align-self:flex-start; color:#21152d; background:var(--pk-peach); border:0; border-radius:999px; padding:10px 14px; font-weight:800; cursor:pointer; }
.pk-card .act:hover { filter:brightness(1.08); transform:translateY(-1px); }
.pk-msg { color:var(--pk-dim); font-size:.9rem; margin:14px 0 0; }
.pk-msg.err { color:#ffb5a8; border-left:3px solid var(--pk-coral); padding-left:12px; }
.pk-wait { display:grid; place-items:center; gap:14px; padding:28px 16px 22px; text-align:center; border-radius:22px; background:rgba(199,183,255,.07); border:1px solid rgba(199,183,255,.15); }
.pk-wait .bar { width:100%; max-width:320px; height:7px; border-radius:99px; overflow:hidden; background:rgba(255,255,255,.1); margin:0; }
.pk-wait .bar:after { content:""; display:block; width:42%; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--pk-peach),var(--pk-coral),var(--pk-mint)); animation:pk-progress 1.4s ease-in-out infinite; }
.pk-cook-scene { position:relative; width:120px; height:96px; display:grid; place-items:center; }
.pk-pot { position:absolute; bottom:8px; width:84px; height:44px; border-radius:10px 10px 22px 22px; background:linear-gradient(145deg,#ffb58e,#ff7f78); border:3px solid #ffe0c9; box-shadow:inset -8px -5px 0 rgba(105,39,69,.13),0 10px 20px rgba(0,0,0,.18); animation:pk-bob 1.1s ease-in-out infinite; }
.pk-pot:before { content:""; position:absolute; left:-13px; right:-13px; top:-7px; height:10px; border-radius:9px; background:#ffe0c9; }
.pk-pot:after { content:""; position:absolute; width:20px; height:7px; border-radius:8px; right:-21px; top:10px; background:#ffb58e; }
.pk-steam { position:absolute; top:2px; color:var(--pk-mint); font-size:24px; animation:pk-steam 1.4s ease-in-out infinite; }
.pk-steam.s2 { left:28px; animation-delay:.35s; color:var(--pk-lilac); } .pk-steam.s3 { right:27px; animation-delay:.7s; color:var(--pk-peach); }
.pk-spark { position:absolute; color:var(--pk-peach); font-size:18px; animation:pk-twinkle 1s ease-in-out infinite alternate; }
.pk-spark.a { left:7px; top:25px; } .pk-spark.b { right:6px; top:34px; animation-delay:.5s; }
.pk-alt { padding-top:20px; border-top:1px solid rgba(199,183,255,.18); }
.pk-alt-title { color:var(--pk-cream); font-family:var(--serif); font-size:1.2rem; margin:0 0 5px; }
@keyframes pk-pop { from { opacity:0; transform:scale(.75) translateY(8px); } to { opacity:1; transform:scale(1) translateY(0); } }
@keyframes pk-rise { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
@keyframes pk-bob { 0%,100% { transform:translateY(0) rotate(-1deg); } 50% { transform:translateY(-5px) rotate(1deg); } }
@keyframes pk-steam { 0% { opacity:0; transform:translateY(12px) scale(.7); } 45% { opacity:1; } 100% { opacity:0; transform:translateY(-15px) scale(1.15); } }
@keyframes pk-twinkle { from { opacity:.35; transform:scale(.75) rotate(0); } to { opacity:1; transform:scale(1.2) rotate(20deg); } }
@keyframes pk-progress { 0% { transform:translateX(-120%); } 100% { transform:translateX(340%); } }
@media(max-width:850px) { .pk-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:600px) { .pk { border-radius:20px; padding:20px 15px; } .pk-grid { grid-template-columns:1fr; } .pk-drop { padding:22px 12px; } .pk-row { gap:10px; } .pk-thumb { width:68px;height:68px; } }
@media(prefers-reduced-motion:reduce) { .pk *, .pk *:before, .pk *:after { animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important; } }
"""

JS = r"""
(function () {
  const order = document.querySelector(".order");
  const food = document.getElementById("food");
  const cons = document.getElementById("cons");
  const goBtn = document.getElementById("go");
  if (!order || !food || !goBtn) return;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  const state = { b64: null, ingredients: [], busy: false };

  // ---------- photo panel first (main feature), dish-name form second ----------
  const box = el("div", "pk");
  box.appendChild(el("h2", "pk-title", "Your ingredients"));
  box.appendChild(el("p", "pk-sub", "Scan ingredients"));

  const drop = el("div", "pk-drop");
  const row = el("div", "pk-row");
  const file = el("input", "pk-file");
  file.type = "file";
  file.id = "pk-file";
  file.accept = "image/jpeg,image/png,image/webp,image/*";
  const pick = el("label", "pk-pick pk-primary", "Upload a photo");
  pick.setAttribute("for", "pk-file");
  const thumb = el("img", "pk-thumb");
  thumb.alt = "Your ingredients";
  thumb.hidden = true;
  const find = el("button", "go", "Find recipes");
  find.type = "button";
  find.hidden = true;
  const remove = el("button", "pk-remove", "Remove");
  remove.type = "button";
  remove.hidden = true;
  row.append(file, pick, thumb, find, remove);
  const hint = el("p", "pk-hint", "JPG, PNG or WebP");
  drop.append(row, hint);

  // dietary needs for the photo flow (starts with whatever is in the dish-name form)
  const dietWrap = el("div", "pk-diet");
  const dietLabel = el("label", "pk-diet-label", "Dietary needs");
  dietLabel.setAttribute("for", "pk-diet");
  const diet = el("input", "pk-diet-input");
  diet.id = "pk-diet";
  diet.placeholder = "e.g. vegetarian, no nuts";
  diet.value = cons ? cons.value : "";
  dietWrap.append(dietLabel, diet);
  function dietText() { return diet.value.trim() || (cons ? cons.value : ""); }

  const cuisineWrap = el("div", "pk-diet");
  const cuisineLabel = el("label", "pk-diet-label", "Cuisine");
  cuisineLabel.setAttribute("for", "pk-cuisine");
  const cuisine = el("select", "pk-cuisine");
  cuisine.id = "pk-cuisine";
  [
    "Any Cuisine", "Indian", "Italian", "Chinese", "Japanese", "Korean",
    "Mexican", "Thai", "Mediterranean", "American", "Continental"
  ].forEach((name) => {
    const option = el("option", "", name);
    option.value = name;
    cuisine.appendChild(option);
  });
  cuisineWrap.append(cuisineLabel, cuisine);

  const msg = el("p", "pk-msg");
  const chipsBox = el("div");
  const results = el("div");
  box.append(drop, dietWrap, cuisineWrap, msg, chipsBox, results);

  // The existing "I'd like to cook" form moves into a secondary section under the photo panel.
  const alt = el("div", "pk-alt");
  alt.appendChild(el("h3", "pk-alt-title", "Or enter a dish"));
  alt.appendChild(el("p", "pk-sub", ""));
  Array.from(order.childNodes).forEach((n) => alt.appendChild(n));
  order.replaceChildren(box, alt);

  // Best-effort: update the headline above the card to match the new main feature.
  document.querySelectorAll("h1, h2, p").forEach((n) => {
    if (!box.contains(n) && n.children.length === 0 && /craving/i.test(n.textContent)) {
      n.textContent = "Show me your ingredients. I'll tell you what to cook.";
    }
  });

  function say(text, isError) {
    msg.textContent = text || "";
    msg.className = "pk-msg" + (isError ? " err" : "");
  }

  // ---------- shrink the photo so uploads are quick ----------
  function shrink(f, maxSide) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(f);
      const img = new Image();
      img.onload = () => {
        const s = Math.min(1, maxSide / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * s);
        c.height = Math.round(img.height * s);
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL("image/jpeg", 0.85));
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file isn't a photo we can read.")); };
      img.src = url;
    });
  }

  async function handleFile(f) {
    if (!f) return;
    if (!/^image\//.test(f.type)) {
      say("Please upload a JPG, PNG or WebP photo.", true);
      return;
    }
    try {
      const dataUrl = await shrink(f, 1024);
      state.b64 = dataUrl.split(",")[1];
      thumb.src = dataUrl;
      thumb.hidden = false;
      find.hidden = false;
      remove.hidden = false;
      hint.hidden = true;
      pick.textContent = "Change photo";
      pick.classList.remove("pk-primary");
      chipsBox.replaceChildren();
      results.replaceChildren();
      say("");
    } catch (e) {
      say(e.message, true);
    }
  }

  file.addEventListener("change", () => handleFile(file.files && file.files[0]));

  remove.addEventListener("click", () => {
    state.b64 = null;
    state.ingredients = [];
    file.value = "";
    thumb.hidden = true;
    thumb.removeAttribute("src");
    find.hidden = true;
    remove.hidden = true;
    hint.hidden = false;
    pick.textContent = "Upload a photo";
    pick.classList.add("pk-primary");
    chipsBox.replaceChildren();
    results.replaceChildren();
    say("");
  });

  // drag and drop onto the dashed area
  ["dragenter", "dragover"].forEach((t) =>
    drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); })
  );
  ["dragleave", "drop"].forEach((t) =>
    drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); })
  );
  drop.addEventListener("drop", (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) handleFile(f);
  });

  // ---------- render ----------
  function renderChips() {
    chipsBox.replaceChildren();
    if (!state.ingredients.length) return;
    chipsBox.appendChild(el("p", "pk-label", "Ingredients found"));
    const wrap = el("div", "pk-chips");
    state.ingredients.forEach((name, i) => {
      const chip = el("span", "pk-chip", name);
      const x = el("button", "", "\u00d7");
      x.type = "button";
      x.setAttribute("aria-label", "Remove " + name);
      x.addEventListener("click", () => { state.ingredients.splice(i, 1); renderChips(); });
      chip.appendChild(x);
      wrap.appendChild(chip);
    });
    const add = el("input", "pk-add");
    add.placeholder = "Add an ingredient";
    add.setAttribute("aria-label", "Add an ingredient");
    add.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && add.value.trim()) {
        state.ingredients.push(add.value.trim());
        renderChips();
        const again = chipsBox.querySelector(".pk-add");
        if (again) again.focus();
      }
    });
    wrap.appendChild(add);
    chipsBox.appendChild(wrap);
    const refresh = el("button", "act pk-refresh", "Update ideas");
    refresh.type = "button";
    refresh.addEventListener("click", () => run(false));
    chipsBox.appendChild(refresh);
  }

  function renderRecipes(list) {
    results.replaceChildren();
    results.appendChild(el("p", "pk-label", "Recipe ideas"));
    const grid = el("div", "pk-grid");
    list.forEach((r) => {
      const card = el("article", "pk-card");
      card.appendChild(el("h4", "", r.name));
      const facts = el("div", "pk-facts");
      facts.appendChild(el("span", "", (r.time_min || "?") + " min"));
      facts.appendChild(el("span", "", r.difficulty || "Easy"));
      card.appendChild(facts);
      if (r.why) card.appendChild(el("p", "pk-why", r.why));
      if (r.uses && r.uses.length) card.appendChild(el("p", "pk-uses", "Uses " + r.uses.join(", ")));
      if (r.missing && r.missing.length) card.appendChild(el("p", "pk-need", "You'll also need " + r.missing.join(", ")));
      const choose = el("button", "act", "Get this recipe");
      choose.type = "button";
      // Hand the choice to the existing ChefGPT flow
      choose.addEventListener("click", () => {
        if (cons && diet.value.trim()) cons.value = diet.value.trim();
        food.value = r.name;
        goBtn.click();
        food.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      card.appendChild(choose);
      grid.appendChild(card);
    });
    results.appendChild(grid);
  }

  function waiting(text) {
    results.replaceChildren();
    const w = el("div", "pk-wait");
    const scene = el("div", "pk-cook-scene");
    scene.append(el("span", "pk-steam s1", "〰"), el("span", "pk-steam s2", "〰"), el("span", "pk-steam s3", "〰"));
    scene.appendChild(el("span", "pk-spark a", "✦"));
    scene.appendChild(el("span", "pk-spark b", "✧"));
    scene.appendChild(el("div", "pk-pot"));
    w.appendChild(scene);
    w.appendChild(el("div", "bar"));
    w.appendChild(el("p", "pk-msg", text));
    results.appendChild(w);
  }

  // ---------- talk to the server ----------
  async function run(fromPhoto) {
    if (state.busy) return;
    state.busy = true;
    find.disabled = true;
    say("");
    waiting(fromPhoto ? "Looking at your photo\u2026" : "Updating the ideas\u2026");
    try {
      const body = { constraints: dietText(), cuisine: cuisine.value };
      if (fromPhoto) body.image_base64 = state.b64; else body.ingredients = state.ingredients;
      const res = await fetch("/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      let data = null;
      try { data = await res.json(); } catch (e) {}
      if (!res.ok || !data) {
        throw new Error((data && typeof data.detail === "string" && data.detail) || "Couldn't scan right now. Please try again.");
      }
      if (fromPhoto) state.ingredients = (data.ingredients || []).filter(Boolean);
      if (!state.ingredients.length || !(data.recipes || []).length) {
        chipsBox.replaceChildren();
        results.replaceChildren();
        say(data.note || "I couldn't find food in that photo. Try a closer, well-lit shot of your ingredients.", true);
        return;
      }
      renderChips();
      renderRecipes(data.recipes);
    } catch (e) {
      results.replaceChildren();
      say(e.message || "Something went wrong. Please try again.", true);
    } finally {
      state.busy = false;
      find.disabled = false;
    }
  }

  find.addEventListener("click", () => run(true));
})();
"""


@router.get("/photo-scan.css")
def photo_scan_css():
    return Response(CSS, media_type="text/css")


@router.get("/photo-scan.js")
def photo_scan_js():
    return Response(JS, media_type="application/javascript")
