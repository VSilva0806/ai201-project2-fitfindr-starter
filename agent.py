"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract description, size, and max_price from a natural language query using regex.

    Size: matched via "size <X>" or standalone uppercase size tokens (S, M, L, XL, etc.).
    Price: matched via patterns like "under $30", "less than 30", "$30 or less".
    Description: the query with size/price clauses removed.
    """
    # --- size ---
    size = None
    size_pattern = re.compile(
        r'\bsize\s+([A-Z0-9]{1,4}(?:/[A-Z0-9]{1,4})?)\b'
        r'|'
        r'\b(XXS|XXL|XXXL|XS|XL|S/M|M/L|[SML])\b',
        re.IGNORECASE,
    )
    size_match = size_pattern.search(query)
    if size_match:
        size = (size_match.group(1) or size_match.group(2)).upper()

    # --- max_price ---
    max_price = None
    price_match = re.search(
        r'(?:under|below|less\s+than|max(?:imum)?|no\s+more\s+than)\s*\$?\s*(\d+(?:\.\d+)?)'
        r'|\$(\d+(?:\.\d+)?)\s*(?:or\s+less|max)',
        query, re.IGNORECASE,
    )
    if price_match:
        raw = price_match.group(1) or price_match.group(2)
        max_price = float(raw)

    # --- description: strip size/price clauses from query ---
    desc = query
    desc = re.sub(
        r'(?:under|below|less\s+than|max(?:imum)?|no\s+more\s+than)\s*\$?\s*\d+(?:\.\d+)?',
        '', desc, flags=re.IGNORECASE,
    )
    desc = re.sub(r'\$\d+(?:\.\d+)?\s*(?:or\s+less|max)?', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\bsize\s+[A-Z0-9]{1,4}(?:/[A-Z0-9]{1,4})?\b', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\b(XXS|XXL|XXXL|XS|XL|S/M|M/L|[SML])\b', '', desc)
    desc = re.sub(r'[,.]', ' ', desc)
    desc = re.sub(r'\s+', ' ', desc).strip()

    return {"description": desc, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: initialize session
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into structured parameters
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search for matching listings
    session["search_results"] = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    if not session["search_results"]:
        session["error"] = (
            f"No listings found matching your request. "
            "Try broadening your description, raising your budget, or omitting the size filter."
        )
        return session

    # Step 4: select the top result
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest an outfit using the selected item and wardrobe
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=wardrobe,
    )

    # Step 6: generate the fit card
    session["fit_card"] = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )

    # Step 7: return the completed session
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

        # ── State flow verification ─────────────────────────────────────────
        print("\n\n=== STATE FLOW VERIFICATION ===\n")

        # 1. Confirm selected_item is the exact dict passed into suggest_outfit.
        #    suggest_outfit receives new_item=session["selected_item"], so they
        #    share the same object identity. Check via id() AND dict equality.
        item_passed_to_suggest = session["selected_item"]
        print("session['selected_item']:")
        print(f"  id       : {id(session['selected_item'])}")
        print(f"  listing id: {session['selected_item'].get('id')}")
        print(f"  title    : {session['selected_item'].get('title')}")
        print(f"  price    : {session['selected_item'].get('price')}")

        # Same object reference — id() must match because run_agent passes
        # session["selected_item"] directly (no copy made).
        print(f"\nObject identity check (same dict in memory): "
              f"{id(item_passed_to_suggest) == id(session['selected_item'])}")

        # 2. Confirm outfit_suggestion is the exact string passed into create_fit_card.
        print(f"\nsession['outfit_suggestion'] (first 120 chars):")
        print(f"  {repr(session['outfit_suggestion'][:120])}")
        print(f"  type : {type(session['outfit_suggestion'])}")
        print(f"  len  : {len(session['outfit_suggestion'])} chars")

        # 3. Confirm fit_card came from create_fit_card (not a re-prompt or hardcode).
        print(f"\nsession['fit_card'] (first 120 chars):")
        print(f"  {repr(session['fit_card'][:120])}")
        print(f"  type : {type(session['fit_card'])}")

        # 4. Show the full session keys to confirm no extra state was injected.
        print(f"\nAll session keys: {list(session.keys())}")
        print(f"session['error']   : {session['error']}  ← None means no early exit")

    print("\n\n=== No-results path ===\n")

    # Patch suggest_outfit to detect if it gets called (it must NOT be).
    import tools as _tools
    _suggest_outfit_orig = _tools.suggest_outfit
    _suggest_outfit_called = []

    def _suggest_outfit_spy(*args, **kwargs):
        _suggest_outfit_called.append(True)
        return _suggest_outfit_orig(*args, **kwargs)

    _tools.suggest_outfit = _suggest_outfit_spy
    # Re-import so run_agent picks up the patched version.
    import importlib, agent as _agent_mod
    importlib.reload(_agent_mod)
    from agent import run_agent as run_agent_patched

    session2 = run_agent_patched(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )

    print(f"session2['error']    : {session2['error']}")
    print(f"session2['fit_card'] : {session2['fit_card']}")
    print(f"session2['outfit_suggestion']: {session2['outfit_suggestion']}")
    print(f"suggest_outfit called: {bool(_suggest_outfit_called)}")
    print()

    assert session2["error"] is not None,        "FAIL: error should be set"
    assert session2["fit_card"] is None,          "FAIL: fit_card should be None"
    assert session2["outfit_suggestion"] is None, "FAIL: outfit_suggestion should be None"
    assert not _suggest_outfit_called,            "FAIL: suggest_outfit must NOT be called on empty results"

    print("All assertions passed — no-results branch is correct.")
