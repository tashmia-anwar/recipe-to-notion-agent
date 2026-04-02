# Recipe to Notion Agent

A personal CLI tool I built to save recipes I enjoy to my personal Notion.

Paste in a recipe URL and it automatically scrapes the ingredients and 
instructions, then creates a formatted page in my Notion recipe database — 
complete with servings, an ingredient checklist, numbered steps, and a 
link back to the source.

## What it does

- Scrapes recipe data from any URL (uses JSON-LD structured data when available)
- Prompts for Meal Type and Cuisine if it can't figure them out automatically
- Creates a new row in my Notion database with the recipe details
- Fills the page body with the image, servings, ingredients, and instructions
- Opens the new Notion page in my browser automatically

## How to set it up

1. Create a [Notion integration](https://www.notion.so/my-integrations) and copy the API key
2. Invite the integration to your recipes database via **Share**
3. Make sure your database has these properties:
   - **Recipe Name** — Title
   - **Meal Type** — Select or multi-select: `lunch`, `dinner`, `breakfast`, `snack`, `dessert`, `appetizer`, `salad`
   - **Cuisine** — Select or multi-select: `Italian`, `Mexican`, `Chinese`, `Indian`, `Japanese`, `Thai`, `Mediterranean`, `American`, `French`, `Greek`, `Middle Eastern`, `British`, `Argentinian`

## Configure

Copy `.env.example` to `.env` and fill in your `NOTION_API_KEY` and `NOTION_DATABASE_ID`.

## Run
```bash
source venv/bin/activate
python -m recipe_to_notion "https://example.com/recipe"
```

Omit the URL to be prompted instead. Add `--no-open` to skip opening the browser.

## Requirements

Python 3.10+ — install dependencies with:
```bash
pip install -r requirements.txt
```

## Notes
Built with the assistance of Cursor and Claude as a hands-on learning 
project exploring agentic AI and API integrations.

**What I learned:**
- How to structure and use prompts to generate working Python scripts
- How APIs (like Notion’s) can be used to automate real tasks
- How to troubleshoot and iterate on AI-generated code

**Next steps for me:**
- Learn more about Python scripting and data handling
- Understand how the generated code works under the hood