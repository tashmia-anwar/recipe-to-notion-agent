from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class IngredientSection:
    label: str | None
    items: list[str]


@dataclass
class InstructionSection:
    label: str | None
    steps: list[str]


@dataclass
class ParsedRecipe:
    name: str
    source_url: str
    image_url: str | None = None
    servings: str | None = None
    ingredient_sections: list[IngredientSection] = field(default_factory=list)
    instruction_sections: list[InstructionSection] = field(default_factory=list)


def _strip_tags(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", html or "")).strip()


def _as_list(x: Any) -> list[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _types(obj: dict[str, Any]) -> list[str]:
    t = obj.get("@type") or obj.get("type")
    if t is None:
        return []
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)]


def _type_is(obj: dict[str, Any], name: str) -> bool:
    n = name.lower()
    for t in _types(obj):
        s = str(t).strip().lower()
        if s == n or s.endswith("/" + n) or s.endswith("#" + n):
            return True
    return False


def _is_recipe(obj: dict[str, Any]) -> bool:
    return any(str(t).strip().lower() == "recipe" for t in _types(obj))


def _iter_ld_json_objects(data: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(data, dict):
        if "@graph" in data:
            for item in _as_list(data["@graph"]):
                if isinstance(item, dict):
                    out.extend(_iter_ld_json_objects(item))
        else:
            out.append(data)
    elif isinstance(data, list):
        for item in data:
            out.extend(_iter_ld_json_objects(item))
    return out


def _pick_image(raw: Any, base_url: str) -> str | None:
    if not raw:
        return None
    if isinstance(raw, str):
        url = raw.strip()
        return urljoin(base_url, url) if url else None
    if isinstance(raw, dict):
        if "url" in raw:
            return _pick_image(raw["url"], base_url)
        if isinstance(raw.get("contentUrl"), str):
            return urljoin(base_url, raw["contentUrl"].strip())
    if isinstance(raw, list) and raw:
        for item in raw:
            u = _pick_image(item, base_url)
            if u:
                return u
    return None


def _normalize_yield(y: Any) -> str | None:
    if y is None:
        return None
    if isinstance(y, (int, float)):
        return str(int(y)) if y == int(y) else str(y)
    if isinstance(y, str):
        s = y.strip()
        return s or None
    if isinstance(y, dict):
        for k in ("name", "text", "value"):
            if k in y and y[k]:
                return _normalize_yield(y[k])
    if isinstance(y, list) and y:
        return _normalize_yield(y[0])
    return None


def _ingredient_strings(raw: Any) -> list[str]:
    items: list[str] = []
    for x in _as_list(raw):
        if isinstance(x, str) and x.strip():
            items.append(re.sub(r"\s+", " ", x.strip()))
        elif isinstance(x, dict):
            t = x.get("text") or x.get("name") or x.get("item")
            if isinstance(t, str) and t.strip():
                items.append(re.sub(r"\s+", " ", t.strip()))
    return items


def _howto_step_text(step: dict[str, Any]) -> str | None:
    if "text" in step:
        t = step["text"]
        if isinstance(t, str) and t.strip():
            return re.sub(r"\s+", " ", t.strip())
        if isinstance(t, list):
            parts: list[str] = []
            for block in t:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(_strip_tags(block.get("text", "")) or str(block))
            joined = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
            return joined or None
    return None


def _parse_instructions(raw: Any) -> list[str]:
    steps: list[str] = []
    if raw is None:
        return steps
    if isinstance(raw, str):
        for line in re.split(r"\n+|(?<=[.!?])\s+", raw):
            line = re.sub(r"^\s*\d+[\).\s]+\s*", "", line.strip())
            if line:
                steps.append(line)
        return steps
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        if _type_is(item, "HowToSection"):
            for sub in _as_list(item.get("itemListElement")):
                if isinstance(sub, dict) and _type_is(sub, "HowToStep"):
                    txt = _howto_step_text(sub)
                    if txt:
                        steps.append(txt)
                elif isinstance(sub, dict):
                    steps.extend(_parse_instructions(sub))
        elif _type_is(item, "HowToStep"):
            txt = _howto_step_text(item)
            if txt:
                steps.append(txt)
        elif "itemListElement" in item:
            steps.extend(_parse_instructions(item["itemListElement"]))
    return steps


def _ingredient_sections_from_recipe(obj: dict[str, Any]) -> list[IngredientSection]:
    flat = _ingredient_strings(obj.get("recipeIngredient"))
    if flat:
        return [IngredientSection(label=None, items=flat)]

    parts = obj.get("recipeIngredientGroup") or obj.get("ingredients")
    sections: list[IngredientSection] = []
    if isinstance(parts, list):
        for p in parts:
            if not isinstance(p, dict):
                continue
            label = p.get("name") or p.get("title")
            label_s = label.strip() if isinstance(label, str) else None
            items = _ingredient_strings(p.get("ingredients") or p.get("recipeIngredient"))
            if items:
                sections.append(IngredientSection(label=label_s, items=items))
    return sections


def _instruction_sections_from_recipe(obj: dict[str, Any]) -> list[InstructionSection]:
    raw = obj.get("recipeInstructions")
    if raw is None:
        return []
    if isinstance(raw, str):
        steps = _parse_instructions(raw)
        return [InstructionSection(label=None, steps=steps)] if steps else []

    out: list[InstructionSection] = []
    flat_fallback: list[str] = []
    for item in _as_list(raw):
        if isinstance(item, dict) and _type_is(item, "HowToSection"):
            name = item.get("name")
            label = name.strip() if isinstance(name, str) and name.strip() else None
            subs = _as_list(item.get("itemListElement"))
            steps: list[str] = []
            for sub in subs:
                if isinstance(sub, dict) and _type_is(sub, "HowToStep"):
                    txt = _howto_step_text(sub)
                    if txt:
                        steps.append(txt)
            if steps:
                out.append(InstructionSection(label=label, steps=steps))
        else:
            flat_fallback.extend(_parse_instructions(item))
    if out:
        return out
    if flat_fallback:
        return [InstructionSection(label=None, steps=flat_fallback)]
    return [InstructionSection(label=None, steps=_parse_instructions(raw))]


def extract_recipe_from_ld_json(
    scripts: list[str], page_url: str
) -> ParsedRecipe | None:
    base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    for raw in scripts:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in _iter_ld_json_objects(data):
            if not isinstance(obj, dict) or not _is_recipe(obj):
                continue
            name = obj.get("name")
            if isinstance(name, list) and name:
                name = name[0]
            if not isinstance(name, str) or not name.strip():
                continue
            image_url = _pick_image(obj.get("image"), base)
            servings = _normalize_yield(obj.get("recipeYield"))
            ing_sections = _ingredient_sections_from_recipe(obj)
            inst_sections = _instruction_sections_from_recipe(obj)
            return ParsedRecipe(
                name=name.strip(),
                source_url=page_url,
                image_url=image_url,
                servings=servings,
                ingredient_sections=ing_sections,
                instruction_sections=inst_sections,
            )
    return None


def _content_root(soup: BeautifulSoup) -> BeautifulSoup:
    """Prefer main/article for text; fall back to body (some sites omit article around the recipe)."""
    return soup.find("article") or soup.find("main") or soup.find("body") or soup


def _find_heading(soup: BeautifulSoup, labels: set[str]) -> Any:
    """First matching heading in document order (not scoped to <article>; many themes omit it)."""
    root = soup.body or soup
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if el.find_parent("nav") or el.find_parent("footer"):
            continue
        if el.get_text(strip=True).lower() in labels:
            return el
    return None


def _next_ol_ul_sibling(tag: Any) -> Any | None:
    s = tag.find_next_sibling()
    while s is not None:
        if s.name in ("ol", "ul"):
            return s
        if s.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return None
        s = s.find_next_sibling()
    return None


def _html_ingredient_sections(soup: BeautifulSoup) -> list[IngredientSection]:
    ing = _find_heading(soup, {"ingredients"})
    inst = _find_heading(soup, {"instructions", "directions", "method", "preparation"})
    if not ing:
        return []
    sections: list[IngredientSection] = []
    label: str | None = None
    for el in ing.find_all_next():
        if inst is not None and el == inst:
            break
        if el.name in ("h1", "h2", "h3", "h4"):
            t = el.get_text(strip=True).lower()
            if el is not ing and t in (
                "instructions",
                "directions",
                "method",
                "preparation",
            ):
                break
        if el.name == "h5":
            label = el.get_text(strip=True)
        elif el.name in ("ul", "ol"):
            items = [
                li.get_text(" ", strip=True)
                for li in el.find_all("li", recursive=False)
                if li.get_text(strip=True)
            ]
            if items:
                sections.append(IngredientSection(label=label, items=items))
                label = None
    return sections


def _list_steps(lst: Any) -> list[str]:
    return [
        li.get_text(" ", strip=True)
        for li in lst.find_all("li", recursive=False)
        if li.get_text(strip=True)
    ]


def _html_instruction_sections(soup: BeautifulSoup) -> list[InstructionSection]:
    ins = _find_heading(soup, {"instructions", "directions", "method", "preparation"})
    if not ins:
        return []
    sections: list[InstructionSection] = []
    for el in ins.find_all_next():
        if el.name == "h4":
            break
        if el.name == "h5":
            label = el.get_text(strip=True)
            lst = _next_ol_ul_sibling(el)
            if lst is None:
                continue
            steps = _list_steps(lst)
            if steps:
                sections.append(InstructionSection(label=label, steps=steps))

    if sections:
        return sections

    # Many blogs use Instructions → <ol> directly (no h5). Grab the first substantive list before the next h4.
    for el in ins.find_all_next():
        if el.name == "h4":
            break
        if el.name in ("ol", "ul"):
            steps = _list_steps(el)
            if len(steps) >= 1:
                return [InstructionSection(label=None, steps=steps)]
    return []


def _wprm_ingredient_fallback(soup: BeautifulSoup) -> list[IngredientSection]:
    lis = soup.select(".wprm-recipe-ingredient")
    if not lis:
        return []
    items = [li.get_text(" ", strip=True) for li in lis if li.get_text(strip=True)]
    return [IngredientSection(label=None, items=items)] if items else []


def _wprm_instruction_fallback(soup: BeautifulSoup) -> list[InstructionSection]:
    lis = soup.select(".wprm-recipe-instruction-text")
    if not lis:
        return []
    steps = [li.get_text(" ", strip=True) for li in lis if li.get_text(strip=True)]
    return [InstructionSection(label=None, steps=steps)] if steps else []


def _meta_og_image(soup: BeautifulSoup, base: str) -> str | None:
    m = soup.find("meta", property="og:image") or soup.find(
        "meta", attrs={"name": "og:image"}
    )
    if m and m.get("content"):
        return urljoin(base, m["content"].strip())
    return None


def _html_servings_guess(soup: BeautifulSoup) -> str | None:
    root = _content_root(soup)
    txt = root.get_text(" ", strip=True)
    m = re.search(
        r"Servings?\s*[:\s]\s*([^\n\r.]+?)(?:\.|\s{2,}|$)",
        txt,
        re.IGNORECASE,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())[:120]
    return None


def enrich_from_html(soup: BeautifulSoup, base: str, recipe: ParsedRecipe) -> None:
    if not recipe.image_url:
        recipe.image_url = _meta_og_image(soup, base)
    if not recipe.servings:
        recipe.servings = _html_servings_guess(soup)
    if not recipe.ingredient_sections:
        recipe.ingredient_sections = _html_ingredient_sections(soup)
    if not recipe.ingredient_sections:
        recipe.ingredient_sections = _wprm_ingredient_fallback(soup)
    if not recipe.instruction_sections:
        recipe.instruction_sections = _html_instruction_sections(soup)
    if not recipe.instruction_sections:
        recipe.instruction_sections = _wprm_instruction_fallback(soup)


def fetch_and_parse_recipe(url: str, timeout: float = 30.0) -> ParsedRecipe:
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout) as client:
        r = client.get(url)
        r.raise_for_status()
        html = r.text
    soup = BeautifulSoup(html, "html.parser")
    scripts: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        if tag.string:
            scripts.append(tag.string)
    parsed = extract_recipe_from_ld_json(scripts, url)
    if parsed:
        enrich_from_html(soup, base, parsed)
        return parsed

    title_tag = soup.find("title")
    name = title_tag.get_text(strip=True) if title_tag else urlparse(url).path or "Recipe"
    name = re.sub(r"\s*[|\-–—].*$", "", name).strip() or name
    out = ParsedRecipe(name=name, source_url=url)
    enrich_from_html(soup, base, out)
    return out
