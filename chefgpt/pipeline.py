from dataclasses import dataclass, field
from .llm import call_json
from .prompts import PARSER_SYSTEM, GENERATOR_SYSTEM, AUDITOR_SYSTEM, REPAIR_TEMPLATE
from .rules import rule_check
from .schemas import Constraints, Recipe, Violation


@dataclass
class Result:
    constraints: Constraints
    recipe: Recipe
    passed: bool
    attempts: int
    violations: list[Violation] = field(default_factory=list)
    rule_only_catches: int = 0  # violations the LLM auditor missed but rules caught


def parse_constraints(text: str) -> Constraints:
    return Constraints(**call_json(PARSER_SYSTEM, [{"role": "user", "content": text}], 300))


def audit(recipe: Recipe, c: Constraints) -> tuple[list[Violation], int]:
    payload = f"Constraints: {c.model_dump_json()}\nIngredients: " + \
              ", ".join(i.name for i in recipe.ingredients)
    if c.calorie_max:
        payload += f"\nCalories per serving: {recipe.calories_per_serving}"
    llm = [Violation(**v, source="llm")
           for v in call_json(AUDITOR_SYSTEM, [{"role": "user", "content": payload}], 800)["violations"]]
    rules = rule_check(recipe, c)
    llm_ings = {v.ingredient.lower() for v in llm}
    rule_only = [v for v in rules if v.ingredient.lower() not in llm_ings]
    return llm + rule_only, len(rule_only)


def run(request: str, constraint_text: str, max_attempts: int = 3) -> Result:
    c = parse_constraints(constraint_text)
    messages = [{"role": "user",
                 "content": f"Constraints: {c.model_dump_json()}\nRequest: {request}"}]
    missed = 0
    for attempt in range(1, max_attempts + 1):
        raw = call_json(GENERATOR_SYSTEM, messages, 1800)
        recipe = Recipe(**raw)
        violations, rule_only = audit(recipe, c)
        missed += rule_only
        if not violations or attempt == max_attempts:
            return Result(c, recipe, not violations, attempt, violations, missed)
        listing = "\n".join(f"- {v.ingredient}: {v.constraint} ({v.reason})" for v in violations)
        messages += [{"role": "assistant", "content": recipe.model_dump_json()},
                     {"role": "user", "content": REPAIR_TEMPLATE.format(violations=listing)}]
