"""
tools.py

The FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
    compare_price(item)                             → str
    load_style_profile(user_id)                     → dict
    save_style_profile(user_id, session)            → str
    check_trending_styles(size)                     → str
"""

import json
import os
import urllib.request
import urllib.error
import xml.etree.ElementTree as _ET
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

class _SearchResults(list):
    """list[dict] subclass that carries an optional fallback note."""
    fallback_note = None  # set when constraints were loosened on retry


def search_listings(
    description: str,
    size: Optional[str] = None,
    max_price: Optional[float] = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    If the initial search returns no results and a size was specified, retries
    automatically without the size filter. The returned list's `.fallback_note`
    attribute (str or None) describes any constraint that was loosened.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A _SearchResults (list subclass) of matching listing dicts, sorted by
        relevance (best match first). Returns an empty list if nothing matches
        — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    def _run(size_filter):
        listings = load_listings()
        if max_price is not None:
            listings = [l for l in listings if l["price"] <= max_price]
        if size_filter is not None:
            sz = size_filter.lower()
            listings = [l for l in listings if sz in l["size"].lower()]
        keywords = set(description.lower().split())

        def score(listing):
            searchable = " ".join([
                listing["title"],
                listing["description"],
                listing["category"],
                " ".join(listing["style_tags"]),
                " ".join(listing["colors"]),
                listing["brand"] or "",
            ]).lower()
            return sum(1 for kw in keywords if kw in searchable)

        scored = [(score(l), l) for l in listings]
        scored = [(s, l) for s, l in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [l for _, l in scored]

    results = _run(size)
    if results:
        return _SearchResults(results)

    # Retry without size filter when the first pass comes up empty
    if size is not None:
        fallback = _run(None)
        if fallback:
            out = _SearchResults(fallback)
            out.fallback_note = (
                f"No results found for size {size} — size filter removed. "
                f"Showing {len(fallback)} result(s) without size restriction."
            )
            return out

    return _SearchResults()


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict, profile_context: str = "") -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    client = _get_groq_client()

    item_desc = (
        f"Title: {new_item.get('title', 'Unknown')}\n"
        f"Category: {new_item.get('category', '')}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Brand: {new_item.get('brand', 'Unknown')}\n"
        f"Condition: {new_item.get('condition', '')}\n"
        f"Description: {new_item.get('description', '')}"
    )

    wardrobe_items = wardrobe.get("items", [])

    if not wardrobe_items:
        context_line = (
            f"\nFor reference, the user typically owns: {profile_context}\n"
            if profile_context else ""
        )
        prompt = (
            f"A user is considering buying the following thrifted item:\n\n"
            f"{item_desc}\n\n"
            f"Their wardrobe is empty.{context_line} Give general styling advice for this item: "
            "what types of pieces pair well with it, what vibe or occasion it suits, "
            "and how to build an outfit around it. Keep the response concise and practical."
        )
    else:
        wardrobe_summary = "\n".join(
            f"- {w.get('title', 'Item')}: {w.get('description', '')} "
            f"(colors: {', '.join(w.get('colors', []))})"
            for w in wardrobe_items
        )
        prompt = (
            f"A user is considering buying the following thrifted item:\n\n"
            f"{item_desc}\n\n"
            f"Their current wardrobe includes:\n{wardrobe_summary}\n\n"
            "Suggest 1–2 specific outfit combinations using the new item paired with "
            "named pieces from the wardrobe above. Be specific about which wardrobe "
            "pieces to combine, the overall vibe, and when they'd wear it."
        )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return "Error: outfit suggestion is missing or incomplete — cannot generate a fit card."

    client = _get_groq_client()

    prompt = (
        f"Write a 2–4 sentence Instagram/TikTok caption for this thrifted outfit.\n\n"
        f"Item: {new_item.get('title', 'Unknown item')}\n"
        f"Price: ${new_item.get('price', '?')}\n"
        f"Platform: {new_item.get('platform', 'thrift store')}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n\n"
        f"Outfit description:\n{outfit}\n\n"
        "Rules:\n"
        "- Sound casual and authentic, like a real OOTD post\n"
        "- Mention the item name, price, and platform once each, naturally\n"
        "- Capture the specific vibe of the outfit\n"
        "- Do NOT use bullet points or headers — write flowing sentences only"
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=1.2,
    )
    return response.choices[0].message.content


# ── Tool 4: compare_price ─────────────────────────────────────────────────────

def compare_price(item: dict) -> str:
    """
    Estimate whether a listing's price is fair based on comparable listings
    in the dataset.

    Args:
        item: A listing dict to evaluate. Must include at least 'price',
              'category', and 'style_tags'.

    Returns:
        A non-empty string summarising the price assessment: whether the item
        is a great deal, fairly priced, or potentially overpriced relative to
        comparable listings. If the item has no price field or no comparable
        listings exist in the dataset, returns a descriptive message without
        raising an exception.

    Comparables are selected in two passes:
        1. Same category + at least one shared style_tag.
        2. If pass 1 yields fewer than 3 results, fall back to same category only.
    The item itself is excluded from the comparison pool (matched by 'id').
    Verdict thresholds:
        <= 25th percentile  → great deal
        25th–75th           → fair price
        > 75th percentile   → potentially overpriced
    """
    if item.get("price") is None:
        return "Error: the provided item does not have a price — cannot compare."

    listings = load_listings()

    item_id = item.get("id")
    item_price = float(item["price"])
    item_category = item.get("category", "").lower()
    item_tags = {t.lower() for t in item.get("style_tags", [])}

    pool = [l for l in listings if l.get("id") != item_id]

    # Pass 1: same category + at least one shared style_tag
    comparables = [
        l for l in pool
        if l.get("category", "").lower() == item_category
        and {t.lower() for t in l.get("style_tags", [])} & item_tags
    ]
    pool_label = "category + style tags"

    # Pass 2: fall back to same category only
    if len(comparables) < 3:
        comparables = [l for l in pool if l.get("category", "").lower() == item_category]
        pool_label = "category only"

    if not comparables:
        return (
            f"No comparable listings found for category "
            f"'{item.get('category', 'unknown')}' in the dataset — "
            "unable to assess price fairness."
        )

    prices = sorted(l["price"] for l in comparables)
    n = len(prices)
    avg_price = sum(prices) / n
    median_price = (
        prices[n // 2] if n % 2 == 1
        else (prices[n // 2 - 1] + prices[n // 2]) / 2
    )
    p25 = prices[max(0, int(n * 0.25) - 1)]
    p75 = prices[min(n - 1, int(n * 0.75))]

    if item_price <= p25:
        verdict = "great deal — priced below the 25th percentile for comparable items"
    elif item_price <= p75:
        verdict = "fair price — within the typical range for comparable items"
    else:
        verdict = "potentially overpriced — above the 75th percentile for comparable items"

    return (
        f"Price assessment for \"{item.get('title', 'this item')}\" at ${item_price:.2f}:\n"
        f"  Verdict: {verdict}.\n"
        f"  Comparable listings ({n} items, category: {item.get('category', '?')}):\n"
        f"    Average: ${avg_price:.2f} | Median: ${median_price:.2f} | "
        f"Range: ${prices[0]:.2f}–${prices[-1]:.2f}\n"
        f"  (Comparison pool: {pool_label})"
    )


# ── Tool 7: check_trending_styles ────────────────────────────────────────────

# Reddit's RSS feed works without OAuth (unlike the JSON API since 2023).
_REDDIT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ATOM_NS = "http://www.w3.org/2005/Atom"

# Size buckets → subreddits most relevant to that size range.
_SIZE_SUBREDDITS: dict[str, list[str]] = {
    "plus":    ["PlusSizeFashion", "femalefashionadvice"],
    "petite":  ["PetiteFashionAdvice", "femalefashionadvice"],
    "standard": ["femalefashionadvice", "malefashionadvice", "streetwear", "ThriftStoreHauls"],
}

_PLUS_TOKENS   = {"xl", "xxl", "xxxl", "1x", "2x", "3x", "4x", "1xl", "2xl", "3xl", "plus"}
_PETITE_TOKENS = {"xxs", "xs", "petite", "00", "0", "2"}


def _size_bucket(size: Optional[str]) -> str:
    """Map a size string to one of: 'plus', 'petite', or 'standard'."""
    if not size:
        return "standard"
    token = size.lower().strip()
    if token in _PLUS_TOKENS:
        return "plus"
    if token in _PETITE_TOKENS:
        return "petite"
    return "standard"


def _fetch_reddit_titles(subreddit: str, limit: int = 20) -> list[str]:
    """Return post titles from a subreddit's hot RSS feed, or [] on any error.

    Uses the Atom RSS feed instead of the JSON API — Reddit's RSS feeds are
    still publicly accessible without OAuth (as of 2025).
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _REDDIT_UA,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        root = _ET.fromstring(raw)
        titles = [
            entry.findtext(f"{{{_ATOM_NS}}}title") or ""
            for entry in root.findall(f"{{{_ATOM_NS}}}entry")
        ]
        return [t for t in titles if t][:limit]
    except (urllib.error.URLError, _ET.ParseError, OSError):
        return []


def check_trending_styles(size: Optional[str] = None) -> str:
    """
    Fetch trending posts from Reddit fashion communities and summarize what styles
    are currently popular, with context for the user's size range.

    Args:
        size: The user's clothing size (e.g., "M", "XL", "XXS"). Determines which
              size-focused communities are queried. None returns general trends.

    Returns:
        A formatted trend report string. Falls back gracefully if Reddit is
        unreachable by returning an LLM-generated summary based on training data.
    """
    bucket = _size_bucket(size)
    subreddits = _SIZE_SUBREDDITS[bucket]
    size_label = size if size else "general"

    # Collect titles from up to two subreddits
    all_titles: list[str] = []
    sources_hit: list[str] = []
    for sub in subreddits[:2]:
        titles = _fetch_reddit_titles(sub)
        if titles:
            all_titles.extend(titles)
            sources_hit.append(f"r/{sub}")

    client = _get_groq_client()

    if all_titles:
        posts_block = "\n".join(f"- {t}" for t in all_titles[:30])
        source_note = f"Source communities: {', '.join(sources_hit)}"
        prompt = (
            f"You are a fashion trend analyst. Below are real post titles from Reddit "
            f"fashion communities ({', '.join(sources_hit)}) fetched right now.\n\n"
            f"Post titles:\n{posts_block}\n\n"
            f"The user wears size: {size_label}\n\n"
            "Based ONLY on these posts, identify 4–6 trending styles, aesthetics, or garment types "
            "that appear frequently. For each trend:\n"
            "  • Name the trend/aesthetic (1–3 words)\n"
            "  • One sentence explaining what it looks like or what's driving it\n"
            "  • A note on how easy it is to find in thrift stores\n\n"
            f"End with one sentence about size availability: are these trends well-represented "
            f"for size {size_label} in the secondhand market?\n\n"
            "Be specific and concise. Do not invent trends not reflected in the titles above."
        )
    else:
        # Reddit unreachable — fall back to LLM knowledge
        prompt = (
            f"You are a fashion trend analyst. Reddit is currently unreachable, so rely on "
            f"your knowledge of current fashion trends (as of early-mid 2025).\n\n"
            f"The user wears size: {size_label}\n\n"
            "List 4–6 trending styles or aesthetics that are currently popular in secondhand / "
            "thrift fashion communities. For each:\n"
            "  • Name the trend (1–3 words)\n"
            "  • One sentence on what defines it\n"
            "  • A note on thrift availability\n\n"
            f"End with a note on size {size_label} availability in the secondhand market.\n\n"
            "Note at the top: '(live Reddit data unavailable — using knowledge base)'"
        )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    report = response.choices[0].message.content

    header = f"Trending styles for size {size_label}"
    if sources_hit:
        header += f" · live from {', '.join(sources_hit)}"
    return f"{header}\n{'─' * len(header)}\n{report}"


# ── Style profile helpers ─────────────────────────────────────────────────────

def _empty_profile() -> dict:
    return {
        "preferred_colors": [],
        "preferred_styles": [],
        "preferred_size": None,
        "max_budget": None,
        "preferred_brands": [],
        "wardrobe_summary": "",
        "session_count": 0,
    }


# ── Tool 5: load_style_profile ────────────────────────────────────────────────

def load_style_profile(user_id: str) -> dict:
    """
    Load a persisted style profile for user_id from profiles/{user_id}.json.

    Returns a profile dict with keys: preferred_colors, preferred_styles,
    preferred_size, max_budget, preferred_brands, wardrobe_summary, session_count.
    If the file is missing or malformed, returns an empty default profile — never raises.
    """
    path = os.path.join(_PROFILES_DIR, f"{user_id}.json")
    try:
        with open(path, "r") as f:
            data = json.load(f)
        default = _empty_profile()
        return {k: data.get(k, v) for k, v in default.items()}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_profile()


# ── Tool 6: save_style_profile ────────────────────────────────────────────────

def save_style_profile(user_id: str, session: dict) -> str:
    """
    Persist an updated style profile to profiles/{user_id}.json after a session.

    Merges the selected item's colors, style tags, brand, size, and price ceiling
    into the existing profile, increments session_count, and writes to disk.
    Returns a confirmation string on success or a descriptive error string on failure
    — never raises.
    """
    profile = dict(session.get("profile") or _empty_profile())
    item = session.get("selected_item") or {}
    parsed = session.get("parsed") or {}

    def _merge(existing: list, incoming: list, cap: int = 20) -> list:
        merged = list(existing)
        for x in incoming:
            if x and x not in merged:
                merged.append(x)
        return merged[-cap:]

    profile["preferred_colors"] = _merge(profile["preferred_colors"], item.get("colors", []))
    profile["preferred_styles"] = _merge(profile["preferred_styles"], item.get("style_tags", []))
    brand = item.get("brand")
    if brand:
        profile["preferred_brands"] = _merge(profile["preferred_brands"], [brand], cap=10)
    if parsed.get("size"):
        profile["preferred_size"] = parsed["size"]
    if parsed.get("max_price") is not None:
        profile["max_budget"] = parsed["max_price"]
    profile["session_count"] = profile.get("session_count", 0) + 1

    try:
        os.makedirs(_PROFILES_DIR, exist_ok=True)
        path = os.path.join(_PROFILES_DIR, f"{user_id}.json")
        with open(path, "w") as f:
            json.dump(profile, f, indent=2)
        return f"Style profile updated (session {profile['session_count']})."
    except OSError as e:
        return f"Error: could not save style profile — {e}"
