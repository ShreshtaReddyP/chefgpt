from typing import Optional
from pydantic import BaseModel, Field


class Constraints(BaseModel):
    diets: list[str] = Field(default_factory=list)       # vegan | vegetarian | pescatarian
    allergens: list[str] = Field(default_factory=list)   # peanuts, tree_nuts, dairy, gluten, eggs, shellfish, fish, soy, sesame
    dislikes: list[str] = Field(default_factory=list)
    calorie_max: Optional[int] = None                    # per serving


class Ingredient(BaseModel):
    name: str
    quantity: str = ""


class Recipe(BaseModel):
    title: str
    servings: int = 2
    time_minutes: int = 30
    calories_per_serving: Optional[int] = None
    ingredients: list[Ingredient]
    steps: list[str]


class Violation(BaseModel):
    ingredient: str
    constraint: str
    reason: str
    source: str = "llm"  # "llm" or "rules"
