"""Deterministic safety layer: does not trust the LLM to catch everything."""
import re
from .schemas import Constraints, Recipe, Violation

MEAT = ["chicken", "beef", "pork", "lamb", "bacon", "ham", "turkey", "sausage",
        "gelatin", "lard", "anchovy paste", "meat", "veal", "duck"]
FISH = ["fish", "salmon", "tuna", "cod", "anchovy", "anchovies", "sardine",
        "fish sauce", "worcestershire"]
SHELLFISH = ["shrimp", "prawn", "crab", "lobster", "scallop", "clam", "mussel",
             "oyster", "squid"]
DAIRY = ["milk", "butter", "ghee", "cheese", "cream", "yogurt", "yoghurt",
         "paneer", "whey", "casein", "parmesan", "mozzarella", "buttermilk"]
EGGS = ["egg", "eggs", "mayonnaise", "mayo", "meringue"]
GLUTEN = ["wheat", "flour", "bread", "breadcrumbs", "pasta", "noodles", "barley",
          "rye", "couscous", "semolina", "soy sauce", "seitan", "naan", "roti"]
PEANUTS = ["peanut", "peanuts", "peanut butter", "peanut oil"]
TREE_NUTS = ["almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut",
             "macadamia", "marzipan"]
SOY = ["soy", "soya", "tofu", "tempeh", "edamame", "miso", "soy sauce"]
SESAME = ["sesame", "tahini"]

ALLERGEN_KEYWORDS = {
    "peanuts": PEANUTS, "tree_nuts": TREE_NUTS, "dairy": DAIRY, "gluten": GLUTEN,
    "eggs": EGGS, "shellfish": SHELLFISH, "fish": FISH, "soy": SOY, "sesame": SESAME,
}
DIET_FORBIDDEN = {
    "vegan": MEAT + FISH + SHELLFISH + DAIRY + EGGS + ["honey"],
    "vegetarian": MEAT + FISH + SHELLFISH,
    "pescatarian": MEAT,
}
# plant-based phrases that contain a forbidden keyword but are fine
SAFE_PHRASES = ["coconut milk", "almond milk", "oat milk", "soy milk", "cashew cream",
                "coconut cream", "peanut-free", "nut-free", "vegan butter",
                "vegan cheese", "vegan mayo", "eggplant", "butternut", "cocoa butter"]


def _matches(text: str, keywords: list[str]) -> str | None:
    text = text.lower()
    for safe in SAFE_PHRASES:
        text = text.replace(safe, " ")
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return kw
    return None


def rule_check(recipe: Recipe, c: Constraints) -> list[Violation]:
    out: list[Violation] = []
    for ing in recipe.ingredients:
        name = ing.name
        for allergen in c.allergens:
            kw = _matches(name, ALLERGEN_KEYWORDS.get(allergen, []))
            if kw:
                out.append(Violation(ingredient=name, constraint=f"allergen:{allergen}",
                                     reason=f"contains '{kw}'", source="rules"))
        for diet in c.diets:
            kw = _matches(name, DIET_FORBIDDEN.get(diet, []))
            if kw:
                out.append(Violation(ingredient=name, constraint=f"diet:{diet}",
                                     reason=f"'{kw}' not allowed", source="rules"))
        for d in c.dislikes:
            if d.lower() in name.lower():
                out.append(Violation(ingredient=name, constraint=f"dislike:{d}",
                                     reason="user dislikes this", source="rules"))
    if c.calorie_max and recipe.calories_per_serving and recipe.calories_per_serving > c.calorie_max:
        out.append(Violation(ingredient="(recipe)", constraint="calories",
                             reason=f"{recipe.calories_per_serving} > {c.calorie_max} kcal",
                             source="rules"))
    return out
