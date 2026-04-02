from __future__ import annotations

import re
from typing import Callable

from recipe_to_notion.scrape import ParsedRecipe

MEAL_OPTIONS = [
    "lunch",
    "dinner",
    "breakfast",
    "snack",
    "dessert",
    "appetizer",
    "salad",
]

CUISINE_OPTIONS = [
    "Italian",
    "Mexican",
    "Chinese",
    "Indian",
    "Japanese",
    "Thai",
    "Mediterranean",
    "American",
    "French",
    "Greek",
    "Middle Eastern",
    "British",
    "Argentinian",
]

_MEAL_KEYWORDS: list[tuple[str, str]] = [
    ("dessert", "dessert"),
    ("dessert", "cake"),
    ("dessert", "cupcake"),
    ("dessert", "cookie"),
    ("dessert", "brownie"),
    ("dessert", "pie "),
    ("dessert", "tart"),
    ("dessert", "pudding"),
    ("dessert", "ice cream"),
    ("dessert", "gelato"),
    ("dessert", "sorbet"),
    ("dessert", "frosting"),
    ("dessert", "ganache"),
    ("breakfast", "breakfast"),
    ("breakfast", "pancake"),
    ("breakfast", "waffle"),
    ("breakfast", "french toast"),
    ("breakfast", "oatmeal"),
    ("breakfast", "granola"),
    ("breakfast", "cereal"),
    ("breakfast", "smoothie bowl"),
    ("breakfast", "eggs benedict"),
    ("snack", "snack"),
    ("snack", "energy bar"),
    ("snack", "trail mix"),
    ("appetizer", "appetizer"),
    ("appetizer", "appetiser"),
    ("appetizer", "starter"),
    ("appetizer", "dip"),
    ("appetizer", "bruschetta"),
    ("appetizer", "canap"),
    ("salad", "salad"),
    ("salad", "slaw"),
    ("lunch", "sandwich"),
    ("lunch", "wrap"),
    ("lunch", "panini"),
    ("dinner", "casserole"),
    ("dinner", "roast "),
    ("dinner", "steak"),
    ("dinner", "curry"),
    ("dinner", "stew"),
]

_CUISINE_KEYWORDS: list[tuple[str, str]] = [
    ("Italian", "italian"),
    ("Italian", "pasta"),
    ("Italian", "risotto"),
    ("Italian", "parmesan"),
    ("Italian", "pesto"),
    ("Italian", "gnocchi"),
    ("Italian", "marinara"),
    ("Mexican", "mexican"),
    ("Mexican", "taco"),
    ("Mexican", "burrito"),
    ("Mexican", "enchilada"),
    ("Mexican", "quesadilla"),
    ("Mexican", "salsa"),
    ("Mexican", "chipotle"),
    ("Chinese", "chinese"),
    ("Chinese", "sichuan"),
    ("Chinese", "dim sum"),
    ("Chinese", "wok"),
    ("Chinese", "hoisin"),
    ("Indian", "indian"),
    ("Indian", "masala"),
    ("Indian", "tikka"),
    ("Indian", "biryani"),
    ("Indian", "naan"),
    ("Indian", "dal "),
    ("Japanese", "japanese"),
    ("Japanese", "sushi"),
    ("Japanese", "miso"),
    ("Japanese", "teriyaki"),
    ("Japanese", "ramen"),
    ("Japanese", "udon"),
    ("Thai", "thai"),
    ("Thai", "pad thai"),
    ("Thai", "tom yum"),
    ("Thai", "green curry"),
    ("Mediterranean", "mediterranean"),
    ("Mediterranean", "falafel"),
    ("Mediterranean", "hummus"),
    ("Mediterranean", "tzatziki"),
    ("American", "american"),
    ("American", "bbq"),
    ("American", "barbecue"),
    ("American", "burger"),
    ("American", "mac and cheese"),
    ("French", "french"),
    ("French", "coq au vin"),
    ("French", "ratatouille"),
    ("French", "béchamel"),
    ("French", "bechamel"),
    ("Greek", "greek"),
    ("Greek", "gyro"),
    ("Greek", "souvlaki"),
    ("Greek", "feta"),
    ("Middle Eastern", "middle eastern"),
    ("Middle Eastern", "shawarma"),
    ("Middle Eastern", "tahini"),
    ("Middle Eastern", "za'atar"),
    ("British", "british"),
    ("British", "english"),
    ("British", "bangers"),
    ("British", "yorkshire"),
    ("Argentinian", "argentinian"),
    ("Argentinian", "argentine"),
    ("Argentinian", "chimichurri"),
    ("Argentinian", "asado"),
]


def _norm_blob(recipe: ParsedRecipe) -> str:
    parts = [recipe.name, recipe.source_url]
    for sec in recipe.ingredient_sections:
        if sec.label:
            parts.append(sec.label)
        parts.extend(sec.items)
    for sec in recipe.instruction_sections:
        if sec.label:
            parts.append(sec.label)
        parts.extend(sec.steps)
    return " ".join(parts).lower()


def _score_keywords(text: str, pairs: list[tuple[str, str]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for label, kw in pairs:
        if kw in text:
            scores[label] = scores.get(label, 0.0) + float(len(kw))
    return scores


def infer_meal(recipe: ParsedRecipe) -> tuple[str | None, bool]:
    """Returns (meal_option or None, ambiguous)."""
    text = _norm_blob(recipe)
    scores = _score_keywords(text, _MEAL_KEYWORDS)
    if not scores:
        return None, True
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best = ranked[0]
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return None, True
    if best[1] < 5:
        return None, True
    return best[0], False


def infer_cuisine(recipe: ParsedRecipe) -> tuple[str | None, bool]:
    text = _norm_blob(recipe)
    scores = _score_keywords(text, _CUISINE_KEYWORDS)
    if not scores:
        return None, True
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best = ranked[0]
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return None, True
    if best[1] < 4:
        return None, True
    return best[0], False


def _match_meal_token(token: str) -> str | None:
    t = token.strip()
    if not t:
        return None
    if t.isdigit():
        idx = int(t)
        if 1 <= idx <= len(MEAL_OPTIONS):
            return MEAL_OPTIONS[idx - 1]
    for opt in MEAL_OPTIONS:
        if t.lower() == opt.lower():
            return opt
    return None


def parse_meal_list(raw: str) -> list[str]:
    """Parse comma-/space-separated meal names or 1-based indices into unique options (order preserved)."""
    raw = raw.strip()
    if not raw:
        return []
    out: list[str] = []
    segments = re.split(r"[,;]+", raw)
    items = segments if len([s for s in segments if s.strip()]) > 1 else re.split(r"[\s,;]+", raw)
    for seg in items:
        m = _match_meal_token(seg)
        if m and m not in out:
            out.append(m)
    return out


def prompt_choice(
    label: str,
    options: list[str],
    input_fn: Callable[[str], str] = input,
) -> str:
    print(f"\n{label}")
    for i, opt in enumerate(options, start=1):
        print(f"  {i}. {opt}")
    while True:
        raw = input_fn("Enter number or exact option name: ").strip()
        if not raw:
            continue
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        for opt in options:
            if raw.lower() == opt.lower():
                return opt
        m = re.match(r"^(\d+)", raw)
        if m:
            idx = int(m.group(1))
            if 1 <= idx <= len(options):
                return options[idx - 1]
        print("Invalid choice; try again.")


def resolve_meals(
    recipe: ParsedRecipe,
    input_fn: Callable[[str], str] = input,
) -> list[str]:
    """Return one or more meal tags (for Notion multi-select)."""
    guess, ambiguous = infer_meal(recipe)
    if guess and not ambiguous:
        print(f"\nMeal type (inferred): {guess}")
        extra = input_fn(
            "Press Enter to use only this, or add more (comma-separated numbers or names, e.g. 2, dinner): "
        ).strip()
        if not extra:
            return [guess]
        chosen: list[str] = [guess]
        for m in parse_meal_list(extra):
            if m not in chosen:
                chosen.append(m)
        return chosen
    if guess:
        print(f"\nPossible meal type: {guess} (low confidence)")
    print("\nChoose one or more meal types:")
    for i, opt in enumerate(MEAL_OPTIONS, start=1):
        print(f"  {i}. {opt}")
    hint = f" Press Enter to use only {guess!r}." if guess else ""
    while True:
        raw = input_fn(
            f"Numbers or names, comma-separated (e.g. 1, 2 or lunch, dinner).{hint} "
        ).strip()
        if not raw and guess:
            return [guess]
        parsed = parse_meal_list(raw)
        if parsed:
            return parsed
        print("Pick at least one valid option.")


def resolve_cuisine(
    recipe: ParsedRecipe,
    input_fn: Callable[[str], str] = input,
) -> str:
    guess, ambiguous = infer_cuisine(recipe)
    if guess and not ambiguous:
        print(f"\nCuisine (inferred): {guess}")
        confirm = input_fn("Press Enter to accept, or type a cuisine to override: ").strip()
        if not confirm:
            return guess
        for opt in CUISINE_OPTIONS:
            if confirm.lower() == opt.lower():
                return opt
        return prompt_choice("Choose cuisine:", CUISINE_OPTIONS, input_fn=input_fn)
    if guess:
        print(f"\nPossible cuisine: {guess} (low confidence)")
    return prompt_choice("Choose cuisine:", CUISINE_OPTIONS, input_fn=input_fn)
