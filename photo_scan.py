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

    for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.8-flash").split(",")
FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",")
    if m.strip()
]
RETRIES_PER_MODEL = 1
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
def _prompt(constraints: str, from_photo: bool, ingredients: List[str]) -> str:
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
    return "\n".join(
        [
            "You are the pantry scanner for ChefGPT, a recipe app.",
            source,
            "Then suggest 4 clearly different recipes (different cuisine or style) that mostly use "
            "those ingredients, assuming only basic staples (salt, oil, water, common spices) are on hand.",
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
        contents.append(_prompt(constraints, True, []))
    else:
        items = [" ".join(i.split())[:60] for i in req.ingredients if i.strip()][:30]
        if not items:
            raise HTTPException(status_code=422, detail="Add a photo or at least one ingredient.")
        contents.append(_prompt(constraints, False, items))

       client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=30000),  # 30 seconds
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
                if gone:
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
        if "503" in text or "UNAVAILABLE" in text or "429" in text:
            detail = "The AI is very busy right now. Please try again in a minute."
        else:
            detail = text[:200]
        raise HTTPException(status_code=503, detail=detail)
    result.recipes = result.recipes[:4]
    return result


# ---------------------------------------------------------------------------
# Front-end assets. They reuse the page's own CSS variables and button classes,
# so the panel looks like part of ChefGPT.
# ---------------------------------------------------------------------------
CSS = r"""
.pk { margin-top: 34px; padding-top: 26px; border-top: 1px solid var(--line); }
.pk-title { font-family: var(--serif); font-size: clamp(1.15rem, 2.4vw, 1.45rem); letter-spacing: -.02em; margin: 0 0 4px; }
.pk-sub { margin: 0 0 16px; color: var(--muted); font-size: .92rem; }
.pk-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.pk-file { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.pk-pick { display: inline-block; cursor: pointer; background: #fffefa; border: 1px solid var(--line); border-radius: 8px; padding: 12px 18px; font-weight: 600; }
.pk-pick:hover { background: #e0e9dc; border-color: #c4d2c0; }
.pk-file:focus-visible + .pk-pick { outline: 2px solid var(--saffron); outline-offset: 2px; }
.pk-thumb { height: 84px; width: 84px; object-fit: cover; border-radius: 10px; border: 1px solid var(--line); }
.pk .go { padding: 12px 22px; }
.pk-msg { margin: 16px 0 0; font-size: .92rem; color: var(--muted); }
.pk-msg.err { color: #9b4a2a; border-left: 3px solid var(--saffron); padding-left: 12px; }
.pk-wait .bar { margin: 18px 0 10px; }
.pk-label { margin: 22px 0 8px; font-size: .88rem; color: var(--muted); }
.pk-chips { display: flex; flex-wrap: wrap; gap: 9px; align-items: center; }
.pk-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 6px 6px 11px; border: 1px solid #d1dbce; border-radius: 7px; background: #f7f8f3; font-size: .92rem; }
.pk-chip button { border: 0; background: none; cursor: pointer; color: var(--muted); font-size: 1.1rem; line-height: 1; padding: 0 5px; }
.pk-chip button:hover { color: var(--ink); }
.pk-add { font: inherit; font-size: .92rem; width: 11.5rem; padding: 6px 4px; background: transparent; border: 0; border-bottom: 1px solid #9eaf9f; color: var(--ink); outline: none; }
.pk-add:focus { border-bottom-color: var(--saffron); }
.pk-refresh { margin-top: 14px; }
.pk-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 640px) { .pk-grid { grid-template-columns: 1fr; } }
.pk-card { display: flex; flex-direction: column; gap: 6px; padding: 18px 20px; background: #fffefa; border: 1px solid var(--line); border-radius: 12px; }
.pk-card h4 { margin: 0; font-family: var(--serif); font-weight: 500; font-size: 1.45rem; letter-spacing: -.02em; line-height: 1.15; }
.pk-facts { display: flex; gap: 18px; color: var(--green); font-family: var(--serif); font-size: 1.05rem; }
.pk-why { margin: 0; font-family: var(--serif); font-size: 1.05rem; line-height: 1.45; color: var(--muted); }
.pk-uses { margin: 0; font-size: .86rem; color: var(--muted); }
.pk-need { margin: 0; font-size: .86rem; color: #9b4a2a; }
.pk-card .act { margin-top: auto; align-self: flex-start; }
.pk-card { transition: border-color .15s; }
.pk-card:hover { border-color: #c4d2c0; }
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

  // ---------- build the panel inside the existing order card ----------
  const box = el("div", "pk");
  box.appendChild(el("h3", "pk-title", "Not sure what to cook? Show me your ingredients."));
  box.appendChild(el("p", "pk-sub", "Upload a photo and I'll spot what you have and suggest a few recipes to choose from."));

  const row = el("div", "pk-row");
  const file = el("input", "pk-file");
  file.type = "file";
  file.id = "pk-file";
  file.accept = "image/jpeg,image/png,image/webp,image/*";
  const pick = el("label", "pk-pick", "Upload a photo");
  pick.setAttribute("for", "pk-file");
  const thumb = el("img", "pk-thumb");
  thumb.alt = "Your ingredients";
  thumb.hidden = true;
  const find = el("button", "go", "Find recipes");
  find.type = "button";
  find.hidden = true;
  row.append(file, pick, thumb, find);

  const msg = el("p", "pk-msg");
  const chipsBox = el("div");
  const results = el("div");
  box.append(row, msg, chipsBox, results);
  order.appendChild(box);

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

  file.addEventListener("change", async () => {
    const f = file.files && file.files[0];
    if (!f) return;
    try {
      const dataUrl = await shrink(f, 1024);
      state.b64 = dataUrl.split(",")[1];
      thumb.src = dataUrl;
      thumb.hidden = false;
      find.hidden = false;
      pick.textContent = "Change photo";
      chipsBox.replaceChildren();
      results.replaceChildren();
      say("");
    } catch (e) {
      say(e.message, true);
    }
  });

  // ---------- render ----------
  function renderChips() {
    chipsBox.replaceChildren();
    if (!state.ingredients.length) return;
    chipsBox.appendChild(el("p", "pk-label", "Here is what I found. Remove anything wrong or add what I missed."));
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
    results.appendChild(el("p", "pk-label", "Pick one and I'll write the full recipe."));
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
      choose.addEventListener("click", () => { food.value = r.name; goBtn.click(); });
      card.appendChild(choose);
      grid.appendChild(card);
    });
    results.appendChild(grid);
  }

  function waiting(text) {
    results.replaceChildren();
    const w = el("div", "pk-wait");
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
      const body = { constraints: cons ? cons.value : "" };
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
