from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from dotenv import load_dotenv

from recipe_to_notion.classify import resolve_cuisine, resolve_meals
from recipe_to_notion.notion_ops import (
    create_recipe_page,
    get_client,
    normalize_database_id,
    notion_page_url,
)
from recipe_to_notion.scrape import fetch_and_parse_recipe


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Scrape a recipe URL and add it to your Notion recipes database.",
    )
    parser.add_argument("url", nargs="?", help="Recipe page URL")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the new Notion page in a browser.",
    )
    args = parser.parse_args()
    url = (args.url or "").strip()
    if not url:
        url = input("Recipe URL: ").strip()
    if not url:
        print("No URL provided.", file=sys.stderr)
        sys.exit(1)

    db_raw = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not db_raw:
        print("Missing NOTION_DATABASE_ID in environment.", file=sys.stderr)
        sys.exit(1)
    database_id = normalize_database_id(db_raw)

    prop_name = os.environ.get("NOTION_PROP_RECIPE_NAME", "Recipe Name").strip()
    prop_meal = os.environ.get("NOTION_PROP_MEAL_TYPE", "Meal Type").strip()
    prop_cuisine = os.environ.get("NOTION_PROP_CUISINE", "Cuisine").strip()

    print("Fetching recipe…")
    recipe = fetch_and_parse_recipe(url)
    print(f"Found: {recipe.name!r}")

    meals = resolve_meals(recipe)
    cuisine = resolve_cuisine(recipe)

    print("\nCreating Notion page…")
    client = get_client()
    page_id = create_recipe_page(
        client,
        database_id,
        recipe,
        prop_name,
        prop_meal,
        prop_cuisine,
        meals,
        cuisine,
    )
    page_url = notion_page_url(page_id)
    print(f"Done: {page_url}")
    if not args.no_open:
        webbrowser.open(page_url)


if __name__ == "__main__":
    main()
