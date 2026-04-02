from __future__ import annotations

import os
import re
import sys
from typing import Any

from notion_client import Client

from recipe_to_notion.scrape import ParsedRecipe

NOTION_VERSION = "2022-06-28"


_DESSERT_HINTS = (
    "brownie",
    "brownies",
    "cupcake",
    "cookie",
    "cake ",
    " cake",
    "cheesecake",
    "dessert",
    "frosting",
    "ganache",
    "pudding",
    "tiramisu",
    " blondie",
    "blondies",
    "pie ",
    " tart",
    "tart ",
    "ice cream",
    "gelato",
    "sorbet",
    "truffle",
    " macaron",
    "cupcake",
    "muffin",
)

_SALAD_HINTS = (
    "salad",
    "slaw",
    "caesar ",
    "greens",
)


def _recipe_text_blob(recipe: ParsedRecipe) -> str:
    parts: list[str] = [recipe.name]
    for sec in recipe.ingredient_sections:
        if sec.label:
            parts.append(sec.label)
        parts.extend(sec.items)
    for sec in recipe.instruction_sections:
        if sec.label:
            parts.append(sec.label)
        parts.extend(sec.steps)
    return " ".join(parts).lower()


def meal_tag_emoji(meals: list[str], recipe: ParsedRecipe | None = None) -> str:
    """Dessert / salad / plate from Meal Type, with recipe-text fallback (name + ingredients)."""
    tags = {str(m).strip().lower() for m in meals if str(m).strip()}
    blob = _recipe_text_blob(recipe) if recipe else ""

    def dessert_signal() -> bool:
        if "dessert" in tags:
            return True
        return bool(blob) and any(h in blob for h in _DESSERT_HINTS)

    def salad_signal() -> bool:
        if "salad" in tags:
            return True
        return bool(blob) and any(h in blob for h in _SALAD_HINTS)

    if dessert_signal():
        return "🍰"
    if salad_signal():
        return "🥗"
    return "🍽️"


def _rich_text(content: str, *, italic: bool = False) -> list[dict[str, Any]]:
    text_obj: dict[str, Any] = {"content": content[:2000]}
    node: dict[str, Any] = {"type": "text", "text": text_obj}
    if italic:
        node["annotations"] = {"italic": True}
    return [node]


def _paragraph(content: str, *, italic: bool = False) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(content, italic=italic)},
    }


def _blank_paragraph() -> dict[str, Any]:
    """Empty line for spacing between sections in Notion."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": []},
    }


def _subsection_title_case(s: str) -> str:
    """Aa-style capitalization: first letter of each word upper, rest lower (not ALL CAPS)."""
    s = s.strip()
    if not s:
        return s
    suffix = ""
    if s.endswith(":"):
        s = s[:-1].rstrip()
        suffix = ":"
    parts = re.split(r"(\s+)", s)
    out: list[str] = []
    for p in parts:
        if not p or p.isspace():
            out.append(p)
            continue
        low = p.lower()
        out.append(low[0].upper() + low[1:] if low else p)
    return "".join(out).strip() + suffix


def _to_do(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "rich_text": _rich_text(text),
            "checked": False,
        },
    }


def _numbered_step(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": _rich_text(text)},
    }


def _external_image(url: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "image",
        "image": {"type": "external", "external": {"url": url[:2000]}},
    }


def _link_paragraph(label: str, url: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": label, "link": {"url": url[:2000]}},
                }
            ]
        },
    }


def build_page_blocks(recipe: ParsedRecipe) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if recipe.image_url and recipe.image_url.startswith(("http://", "https://")):
        blocks.append(_external_image(recipe.image_url))
    servings = recipe.servings or "—"
    blocks.append(_paragraph(f"Servings: {servings}"))
    blocks.append(_blank_paragraph())
    blocks.append(_paragraph("Ingredients"))
    sections = recipe.ingredient_sections
    if not sections:
        blocks.append(_paragraph("No ingredients found on the page."))
    else:
        multi = len(sections) > 1 or any(s.label for s in sections)
        for sec in sections:
            if multi and sec.label:
                blocks.append(
                    _paragraph(_subsection_title_case(sec.label), italic=True)
                )
            elif multi and not sec.label and len(sections) == 1:
                pass
            for item in sec.items:
                blocks.append(_to_do(item))

    blocks.append(_blank_paragraph())
    blocks.append(_paragraph("Instructions"))
    if not recipe.instruction_sections:
        blocks.append(_paragraph("No instructions found on the page."))
    else:
        multi_inst = len(recipe.instruction_sections) > 1 or any(
            s.label for s in recipe.instruction_sections
        )
        for sec in recipe.instruction_sections:
            if multi_inst and sec.label:
                blocks.append(
                    _paragraph(_subsection_title_case(sec.label), italic=True)
                )
            for step in sec.steps:
                blocks.append(_numbered_step(step))

    blocks.append(_blank_paragraph())
    blocks.append(_paragraph("Reference Links"))
    blocks.append(_link_paragraph(recipe.source_url, recipe.source_url))
    return blocks


def _chunk_blocks(blocks: list[dict[str, Any]], size: int = 100) -> list[list[dict[str, Any]]]:
    return [blocks[i : i + size] for i in range(0, len(blocks), size)]


def fetch_property_types(client: Client, database_id: str) -> dict[str, str]:
    """Map property display name -> Notion property type (e.g. select, multi_select)."""
    db = client.databases.retrieve(database_id=database_id)
    out: dict[str, str] = {}
    for name, meta in (db.get("properties") or {}).items():
        t = meta.get("type")
        if isinstance(t, str):
            out[name] = t
    return out


def _select_like_payload(notion_type: str, value: str, label: str) -> dict[str, Any]:
    """Build property value for select or multi_select (single option)."""
    nt = notion_type.lower()
    if nt == "select":
        return {"select": {"name": value}}
    if nt == "multi_select":
        return {"multi_select": [{"name": value}]}
    raise ValueError(
        f'"{label}" is a {notion_type!r} column; only select and multi_select are supported. '
        f"Change the column type in Notion or use a different property."
    )


def _emoji_column_payload(notion_type: str, emoji: str) -> dict[str, Any] | None:
    """Value for the optional emoji column (e.g. Notion Text / rich_text, or select)."""
    nt = notion_type.lower()
    if nt == "rich_text":
        return {
            "rich_text": [
                {"type": "text", "text": {"content": emoji}},
            ],
        }
    if nt == "select":
        return {"select": {"name": emoji}}
    if nt == "multi_select":
        return {"multi_select": [{"name": emoji}]}
    return None


def _meal_property_payload(
    notion_type: str, meals: list[str], label: str
) -> dict[str, Any]:
    """Meal Type: support multiple tags when the column is multi_select."""
    nt = notion_type.lower()
    deduped: list[str] = list(dict.fromkeys(meals))
    if not deduped:
        raise ValueError(f'"{label}" needs at least one meal type.')
    if nt == "multi_select":
        return {"multi_select": [{"name": m} for m in deduped]}
    if nt == "select":
        if len(deduped) > 1:
            print(
                f'Note: "{label}" is single-select in Notion; using {deduped[0]!r} only '
                f"(ignored: {', '.join(repr(m) for m in deduped[1:])}).",
                file=sys.stderr,
            )
        return {"select": {"name": deduped[0]}}
    raise ValueError(
        f'"{label}" is a {notion_type!r} column; only select and multi_select are supported. '
        f"Change the column type in Notion or use a different property."
    )


def create_recipe_page(
    client: Client,
    database_id: str,
    recipe: ParsedRecipe,
    prop_name: str,
    prop_meal: str,
    prop_cuisine: str,
    meals: list[str],
    cuisine: str,
) -> str:
    types = fetch_property_types(client, database_id)
    meal_t = types.get(prop_meal)
    cuisine_t = types.get(prop_cuisine)
    if meal_t is None:
        raise SystemExit(
            f'No column named "{prop_meal}" in this database. '
            f"Check NOTION_PROP_MEAL_TYPE or share the database with the integration."
        )
    if cuisine_t is None:
        raise SystemExit(
            f'No column named "{prop_cuisine}" in this database. '
            f"Check NOTION_PROP_CUISINE or share the database with the integration."
        )

    properties: dict[str, Any] = {
        prop_name: {
            "title": [{"type": "text", "text": {"content": recipe.name[:2000]}}],
        },
        prop_meal: _meal_property_payload(meal_t, meals, prop_meal),
        prop_cuisine: _select_like_payload(cuisine_t, cuisine, prop_cuisine),
    }

    icon_emoji = meal_tag_emoji(meals, recipe)

    plate_prop = os.environ.get("NOTION_PROP_AA", "Aa").strip()
    if plate_prop and plate_prop != prop_name:
        plate_t = types.get(plate_prop)
        if plate_t is None:
            print(
                f'Note: no column "{plate_prop}" — page icon set to {icon_emoji} instead; add column or set NOTION_PROP_AA.',
                file=sys.stderr,
            )
        else:
            plate_payload = _emoji_column_payload(plate_t, icon_emoji)
            if plate_payload is None:
                print(
                    f'Note: column "{plate_prop}" is {plate_t!r}; use Text or Select (🍽️ 🥗 🍰). Page icon: {icon_emoji}.',
                    file=sys.stderr,
                )
            else:
                properties[plate_prop] = plate_payload

    page = client.pages.create(
        parent={"database_id": database_id},
        properties=properties,
        icon={"type": "emoji", "emoji": icon_emoji},
    )
    page_id = page["id"]
    for batch in _chunk_blocks(build_page_blocks(recipe)):
        client.blocks.children.append(block_id=page_id, children=batch)
    return page_id


def notion_page_url(page_id: str) -> str:
    """Open-in-Notion URL (works when logged in)."""
    clean = page_id.replace("-", "")
    return f"https://www.notion.so/{clean}"


def get_client() -> Client:
    key = os.environ.get("NOTION_API_KEY", "").strip()
    if not key:
        raise SystemExit("Missing NOTION_API_KEY in environment.")
    return Client(auth=key, notion_version=NOTION_VERSION)


def normalize_database_id(raw: str) -> str:
    s = re.sub(r"[^a-fA-F0-9]", "", raw.strip())
    if len(s) != 32:
        return raw.strip()
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"