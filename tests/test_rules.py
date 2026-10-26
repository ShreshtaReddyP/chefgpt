from chefgpt.rules import rule_check
from chefgpt.schemas import Constraints, Recipe, Ingredient


def mk(*names):
    return Recipe(title="t", ingredients=[Ingredient(name=n) for n in names], steps=[])


def test_vegan_catches_hidden_animal_products():
    v = rule_check(mk("ghee", "honey", "rice"), Constraints(diets=["vegan"]))
    assert {x.ingredient for x in v} == {"ghee", "honey"}


def test_plant_milks_are_ok():
    assert rule_check(mk("coconut milk", "almond milk"), Constraints(diets=["vegan"])) == []


def test_gluten_soy_sauce():
    v = rule_check(mk("soy sauce"), Constraints(allergens=["gluten"]))
    assert len(v) == 1


def test_calorie_limit():
    r = mk("rice"); r.calories_per_serving = 900
    assert rule_check(r, Constraints(calorie_max=600))[0].constraint == "calories"
