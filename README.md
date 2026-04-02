# recipe-to-notion-agent

CLI tool that scrapes a recipe URL (JSON-LD when available), prompts for **Meal Type** and **Cuisine** when inference is uncertain, creates a row in your Notion recipes database, fills the page body (image, servings, ingredient checklists, numbered instructions, source link), and opens the page in your browser.

## Notion setup

1. Create an [integration](https://www.notion.so/my-integrations) and copy the API key.
2. In your recipes **database**, use **Share** → invite the integration (must have edit access).
3. Property names and option labels must match what the script sends:
   - **Recipe Name** — Title
   - **Meal Type** — Select *or* multi-select (you can pick several, e.g. lunch and dinner): `lunch`, `dinner`, `breakfast`, `snack`, `dessert`, `appetizer`, `salad` (exact spelling)
   - **Cuisine** — Select *or* multi-select: `Italian`, `Mexican`, `Chinese`, `Indian`, `Japanese`, `Thai`, `Mediterranean`, `American`, `French`, `Greek`, `Middle Eastern`, `British`, `Argentinian`

The integration loads your database schema so **Meal Type** / **Cuisine** work whether each column is a single select or a multi-select.

If your columns are named differently, set `NOTION_PROP_RECIPE_NAME`, `NOTION_PROP_MEAL_TYPE`, and `NOTION_PROP_CUISINE` in `.env`.

## Configure

Copy `.env.example` to `.env` and set `NOTION_API_KEY` and `NOTION_DATABASE_ID` (from the database URL).

## Run

```bash
source venv/bin/activate   # or: ./venv/bin/python -m recipe_to_notion
python -m recipe_to_notion "https://example.com/recipe"
```

Omit the URL to be prompted. Use `python -m recipe_to_notion --no-open "URL"` to skip opening the browser.

## Requirements

Python 3.10+ and dependencies in `requirements.txt` (install with `pip install -r requirements.txt`).
