"""
tests/test_tools.py

Pytest tests for each FitFindr tool.
At least one test per failure mode is covered for each tool.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# ── Shared fixtures ────────────────────────────────────────────────────────────

SAMPLE_LISTINGS = [
    {
        "id": "lst_001",
        "title": "Vintage Levi's 501 Jeans",
        "description": "Classic denim jeans with light fading",
        "category": "bottoms",
        "style_tags": ["vintage", "denim", "classic"],
        "size": "M",
        "condition": "good",
        "price": 38.0,
        "colors": ["blue", "indigo"],
        "brand": "Levi's",
        "platform": "depop",
    },
    {
        "id": "lst_002",
        "title": "Graphic Tee",
        "description": "Cool vintage graphic tee with retro print",
        "category": "tops",
        "style_tags": ["graphic", "vintage", "streetwear"],
        "size": "S",
        "condition": "excellent",
        "price": 15.0,
        "colors": ["white"],
        "brand": None,
        "platform": "thredUp",
    },
    {
        "id": "lst_003",
        "title": "Expensive Wool Coat",
        "description": "Luxury designer coat in pristine condition",
        "category": "outerwear",
        "style_tags": ["luxury", "designer", "wool"],
        "size": "L",
        "condition": "excellent",
        "price": 200.0,
        "colors": ["black"],
        "brand": "Gucci",
        "platform": "poshmark",
    },
]

# The graphic tee is used as the "new item" the user is considering buying
SAMPLE_ITEM = SAMPLE_LISTINGS[1]

SAMPLE_WARDROBE = {
    "items": [
        {
            "title": "Baggy Jeans",
            "description": "Loose fit denim jeans",
            "colors": ["blue"],
        },
        {
            "title": "Chunky Sneakers",
            "description": "Platform sneakers with thick sole",
            "colors": ["white"],
        },
    ]
}

EMPTY_WARDROBE = {"items": []}


def _groq_mock(response_text: str) -> MagicMock:
    """Return a Groq client mock that produces `response_text`."""
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = response_text
    client.chat.completions.create.return_value = response
    return client


# ── Tool 1: search_listings ────────────────────────────────────────────────────

class TestSearchListings:

    def test_no_keyword_match_returns_empty_list(self):
        """Failure mode: description has zero overlap with any listing."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            results = search_listings("zxyqw invisible unicorn")

        assert results == []

    def test_all_items_above_max_price_returns_empty_list(self):
        """Failure mode: every listing exceeds max_price."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            results = search_listings("vintage", max_price=1.0)

        assert results == []

    def test_no_listing_matches_requested_size_returns_empty_list(self):
        """Failure mode: size filter excludes all listings."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            results = search_listings("vintage", size="XXL")

        assert results == []

    def test_price_filter_excludes_items_above_ceiling(self):
        """Items priced above max_price must not appear; items at max_price must appear."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            # max_price=38 → lst_001 ($38) and lst_002 ($15) qualify; lst_003 ($200) does not
            results = search_listings("vintage denim graphic", max_price=38.0)

        ids = {r["id"] for r in results}
        assert "lst_003" not in ids
        assert "lst_001" in ids or "lst_002" in ids  # at least one cheap match

    def test_size_filter_is_case_insensitive(self):
        """Searching for "m" and "M" should return the same results."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            upper = search_listings("vintage", size="M")
            lower = search_listings("vintage", size="m")

        assert {r["id"] for r in upper} == {r["id"] for r in lower}

    def test_higher_keyword_overlap_ranks_first(self):
        """Items that match more keywords should appear before those that match fewer."""
        from tools import search_listings

        # "vintage graphic" — lst_002 has both in title, tags, and description;
        # lst_001 only matches "vintage"
        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            results = search_listings("vintage graphic")

        assert len(results) >= 2
        assert results[0]["id"] == "lst_002"

    def test_price_and_size_filters_applied_together(self):
        """Both filters must be active simultaneously."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            # S-sized items under $20 → only lst_002
            results = search_listings("vintage", size="S", max_price=20.0)

        ids = {r["id"] for r in results}
        assert "lst_002" in ids
        assert "lst_001" not in ids  # size M, not S
        assert "lst_003" not in ids  # too expensive

    def test_no_filters_returns_all_matching_listings(self):
        """With no price or size filter, every keyword-matching listing is returned."""
        from tools import search_listings

        with patch("tools.load_listings", return_value=SAMPLE_LISTINGS):
            # "vintage" appears in lst_001 and lst_002 but not lst_003
            results = search_listings("vintage")

        ids = {r["id"] for r in results}
        assert "lst_001" in ids
        assert "lst_002" in ids
        assert "lst_003" not in ids


# ── Tool 2: suggest_outfit ─────────────────────────────────────────────────────

class TestSuggestOutfit:

    def test_missing_api_key_raises_value_error(self, monkeypatch):
        """Failure mode: GROQ_API_KEY is unset — must raise ValueError before calling LLM."""
        from tools import suggest_outfit

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)

    def test_empty_wardrobe_returns_non_empty_string(self, monkeypatch):
        """Failure mode: wardrobe is empty — must return general advice, not raise."""
        from tools import suggest_outfit

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_client = _groq_mock("Pair this tee with wide-leg trousers for an effortless look.")

        with patch("tools._get_groq_client", return_value=mock_client):
            result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)

        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_empty_wardrobe_prompt_describes_general_styling(self, monkeypatch):
        """When wardrobe is empty, the LLM prompt should request general styling advice."""
        from tools import suggest_outfit

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_client = _groq_mock("General advice here.")

        with patch("tools._get_groq_client", return_value=mock_client):
            suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        assert "wardrobe is empty" in prompt.lower() or "general styling" in prompt.lower()

    def test_non_empty_wardrobe_returns_string(self, monkeypatch):
        """Happy path: wardrobe has items — returns a non-empty outfit suggestion."""
        from tools import suggest_outfit

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_client = _groq_mock("Outfit 1: Graphic Tee + Baggy Jeans — a relaxed streetwear combo.")

        with patch("tools._get_groq_client", return_value=mock_client):
            result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)

        assert isinstance(result, str)
        assert len(result.strip()) > 0
        mock_client.chat.completions.create.assert_called_once()

    def test_non_empty_wardrobe_prompt_includes_wardrobe_items(self, monkeypatch):
        """The LLM prompt must name the user's actual wardrobe pieces."""
        from tools import suggest_outfit

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_client = _groq_mock("Outfit suggestion.")

        with patch("tools._get_groq_client", return_value=mock_client):
            suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        assert "Baggy Jeans" in prompt or "Chunky Sneakers" in prompt


# ── Tool 3: create_fit_card ────────────────────────────────────────────────────

class TestCreateFitCard:

    def test_empty_outfit_string_returns_error_message(self):
        """Failure mode: outfit is empty string — must return error string, not raise."""
        from tools import create_fit_card

        result = create_fit_card("", SAMPLE_ITEM)

        assert isinstance(result, str)
        assert "error" in result.lower()

    def test_whitespace_only_outfit_returns_error_message(self):
        """Failure mode: outfit is all whitespace — must return error string, not raise."""
        from tools import create_fit_card

        result = create_fit_card("   \n\t  ", SAMPLE_ITEM)

        assert isinstance(result, str)
        assert "error" in result.lower()

    def test_empty_outfit_does_not_call_llm(self):
        """The LLM must not be called when the outfit guard fires."""
        from tools import create_fit_card

        with patch("tools._get_groq_client") as mock_get_client:
            create_fit_card("", SAMPLE_ITEM)

        mock_get_client.assert_not_called()

    def test_missing_api_key_raises_value_error_for_valid_outfit(self, monkeypatch):
        """Failure mode: valid outfit but GROQ_API_KEY is unset — must raise ValueError."""
        from tools import create_fit_card

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            create_fit_card("Graphic Tee with baggy jeans and chunky sneakers.", SAMPLE_ITEM)

    def test_valid_inputs_return_string_from_llm(self, monkeypatch):
        """Happy path: valid outfit and item → returns LLM-generated caption."""
        from tools import create_fit_card

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        caption = "Snagged this Graphic Tee for $15 on thredUp and it's giving retro everything."
        mock_client = _groq_mock(caption)

        with patch("tools._get_groq_client", return_value=mock_client):
            result = create_fit_card("Graphic Tee + baggy jeans.", SAMPLE_ITEM)

        assert isinstance(result, str)
        assert len(result.strip()) > 0
        mock_client.chat.completions.create.assert_called_once()

    def test_prompt_includes_item_price_and_platform(self, monkeypatch):
        """The LLM prompt must embed price and platform so the caption can mention them."""
        from tools import create_fit_card

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        mock_client = _groq_mock("Caption text.")

        with patch("tools._get_groq_client", return_value=mock_client):
            create_fit_card("A great streetwear look.", SAMPLE_ITEM)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        # SAMPLE_ITEM has price=15.0, platform="thredUp"
        assert "15" in prompt
        assert "thredUp" in prompt
