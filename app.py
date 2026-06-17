"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from tools import check_trending_styles
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(user_query: str, wardrobe_choice: str, user_id: str) -> tuple[str, str, str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Returns a tuple of five strings:
        (listing_text, outfit_suggestion, fit_card, profile_status, trends)
    """
    if not user_query or not user_query.strip():
        return "Please enter a search query.", "", "", "", ""

    uid = user_id.strip() or "default"

    wardrobe = (
        get_example_wardrobe()
        if wardrobe_choice == "Example wardrobe"
        else get_empty_wardrobe()
    )

    session = run_agent(query=user_query, wardrobe=wardrobe, user_id=uid)

    if session["error"]:
        return session["error"], "", "", "", ""

    item = session["selected_item"]
    note_prefix = f"ℹ️ {session['fallback_note']}\n\n" if session.get("fallback_note") else ""
    listing_text = (
        note_prefix +
        f"{item['title']}\n"
        f"Brand: {item.get('brand') or 'Unknown'}\n"
        f"Price: ${item['price']:.2f}  •  Platform: {item['platform']}\n"
        f"Size: {item['size']}  •  Condition: {item['condition']}\n"
        f"Colors: {', '.join(item.get('colors', []))}\n"
        f"Tags: {', '.join(item.get('style_tags', []))}\n\n"
        f"{item['description']}\n\n"
        f"─────────────────────────\n"
        f"{session['price_assessment']}"
    )

    profile = session["profile"]
    parsed = session["parsed"]
    profile_status = (
        f"{session['profile_save']}\n"
        f"─────────────────────────\n"
        f"Sessions remembered: {profile.get('session_count', 0)}\n"
        f"Size used: {parsed.get('size') or '—'}"
        + (" (from profile)" if parsed.get('size') and parsed['size'] == profile.get('preferred_size') and not _query_has_size(user_query) else "") + "\n"
        f"Budget used: {'$' + str(parsed['max_price']) if parsed.get('max_price') else '—'}"
        + (" (from profile)" if parsed.get('max_price') and parsed['max_price'] == profile.get('max_budget') and not _query_has_price(user_query) else "") + "\n"
        f"Known colors: {', '.join(profile.get('preferred_colors', [])) or '—'}\n"
        f"Known styles: {', '.join(profile.get('preferred_styles', [])) or '—'}"
    )

    return listing_text, session["outfit_suggestion"], session["fit_card"], profile_status, session.get("trends") or ""


def handle_trends(size_input: str, user_id: str) -> str:
    """Called by Gradio when the user clicks 'What's trending in my size?'."""
    from tools import load_style_profile
    uid = user_id.strip() or "default"
    size = size_input.strip() or None
    if not size:
        profile = load_style_profile(uid)
        size = profile.get("preferred_size") or None
    return check_trending_styles(size=size)


def _query_has_size(query: str) -> bool:
    import re
    return bool(re.search(r'\bsize\s+\S+|\b(XXS|XXL|XS|XL|[SML])\b', query, re.IGNORECASE))


def _query_has_price(query: str) -> bool:
    import re
    return bool(re.search(r'under|below|less\s+than|max|\$\d', query, re.IGNORECASE))


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            with gr.Column(scale=1):
                wardrobe_choice = gr.Radio(
                    choices=["Example wardrobe", "Empty wardrobe (new user)"],
                    value="Example wardrobe",
                    label="Wardrobe",
                )
                user_id_input = gr.Textbox(
                    label="Your username (for style memory)",
                    placeholder="e.g. victor",
                    value="default",
                    lines=1,
                )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=10,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=10,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=10,
                interactive=False,
            )
            profile_output = gr.Textbox(
                label="🧠 Style memory",
                lines=10,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe", "default"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice, user_id_input],
            label="Try these queries",
        )

        gr.Markdown("---")
        gr.Markdown("### 📈 What's trending in your size?")
        gr.Markdown(
            "Fetches live posts from Reddit fashion communities and summarizes "
            "trending styles for your size. Tip: include your size below or log in "
            "first so FitFindr can pull it from your style memory."
        )

        with gr.Row():
            trend_size_input = gr.Textbox(
                label="Your size (optional — auto-filled from style memory if blank)",
                placeholder="e.g. M, XL, XXS",
                lines=1,
                scale=2,
            )
            trend_btn = gr.Button("What's trending in my size?", scale=1)

        trends_output = gr.Textbox(
            label="📈 Trending styles",
            lines=14,
            interactive=False,
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, user_id_input],
            outputs=[listing_output, outfit_output, fitcard_output, profile_output, trends_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, user_id_input],
            outputs=[listing_output, outfit_output, fitcard_output, profile_output, trends_output],
        )
        trend_btn.click(
            fn=handle_trends,
            inputs=[trend_size_input, user_id_input],
            outputs=[trends_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
