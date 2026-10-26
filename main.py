import sys
from chefgpt.pipeline import run


def show(r):
    rec = r.recipe
    print(f"\n=== {rec.title} ({rec.servings} servings, {rec.time_minutes} min, "
          f"~{rec.calories_per_serving} kcal) ===")
    for i in rec.ingredients:
        print(f"  - {i.quantity} {i.name}".replace("  ", " ", 1))
    for n, s in enumerate(rec.steps, 1):
        print(f"{n}. {s}")
    status = "PASSED" if r.passed else "FAILED"
    print(f"\nDietary check: {status} after {r.attempts} attempt(s); "
          f"constraints = {r.constraints.model_dump()}")
    for v in r.violations:
        print(f"  ! {v.ingredient}: {v.constraint} - {v.reason} [{v.source}]")


if __name__ == "__main__":
    request = sys.argv[1] if len(sys.argv) > 1 else input("What do you want to cook? ")
    constraints = sys.argv[2] if len(sys.argv) > 2 else input("Dietary constraints? ")
    show(run(request, constraints))
