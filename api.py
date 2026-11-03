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
