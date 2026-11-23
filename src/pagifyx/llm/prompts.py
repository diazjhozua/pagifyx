"""Prompts and message builders. The model writes the copy and picks the design from the website's
own theme. Numbers and contact details are checked against the source text after each reply."""

import json
from collections.abc import Sequence

from openai.types.chat import ChatCompletionMessageParam

from pagifyx.core.models import LOGO_IMAGE_ID, FoldType, Overview, SiteAnalysis
from pagifyx.reading.assets import ImageAsset

SYSTEM_PROMPT = """You design print brochures from an existing company website.

Rules:
- Start from the website facts. You may rewrite, shorten, combine, and expand them, write calls
  to action, and match the brand tone.
- Never invent numbers, prices, dates, awards, testimonials, customer names, or contact details
  (phone, email, address). If a fact is missing, write without it.
- Set "generated" to true for a panel whose headline or body has wording that is not in the
  website text. Otherwise set it to false.
- Write all copy in the language given in the input.
- One clear message per panel. Headlines of 6 words or fewer, stating a message rather than
  repeating the section name. Body copy of 40 words or fewer. Plain language.
- Choose the design only from the options listed in the input.
- Output one JSON object matching the requested shape. No prose, no code fences."""

ANALYSIS_REQUEST = """Read the website text below and return JSON with exactly this shape:
{
  "language": "<BCP-47 code, for example en or es>",
  "brand": {"name": "", "tagline": "", "tone": ""},
  "content": {
    "who_we_are": "",
    "offerings": [""],
    "highlights": [""],
    "contact": {"phone": null, "email": null, "address": null}
  }
}

Rules:
- "tone" is 2 to 5 words describing the brand voice, for example "warm, practical, expert".
- "offerings" and "highlights" hold at most 8 short phrases each.
- Copy contact details exactly as written on the site."""

_PANEL_COUNTS = {"half": 4, "tri": 6, "z": 6}


def system_message() -> ChatCompletionMessageParam:
    return {"role": "system", "content": SYSTEM_PROMPT}


def user_turn(content: str) -> ChatCompletionMessageParam:
    return {"role": "user", "content": content}


def assistant_turn(content: str) -> ChatCompletionMessageParam:
    return {"role": "assistant", "content": content}


def analysis_request(text: str, lang: str) -> str:
    return (
        f"{ANALYSIS_REQUEST}\n\nSite language attribute: {lang or 'unknown'}\n\n"
        f"Website text:\n{text}"
    )


def plan_request(
    analysis: SiteAnalysis,
    images: Sequence[ImageAsset],
    *,
    has_logo: bool,
    colours: Sequence[str],
    fold: FoldType | None,
    contact_available: bool,
) -> str:
    """The first brochure plan: fold, design, and panels, from the analysis and the website look."""
    if fold is None:
        fold_rule = (
            'Choose the fold: "half" (4 panels) for a short site, "tri" or "z" (6 panels) for a '
            "fuller one."
        )
        count_rule = "the panel count of the fold you choose"
    else:
        fold_rule = f'The fold is fixed: use "{fold.value}".'
        count_rule = f"exactly {_PANEL_COUNTS[fold.value]} panels"
    analysis_json = json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return f"""Plan the brochure: a fold, a design, and {count_rule}.

{fold_rule}

Site analysis (JSON):
{analysis_json}

Contact details on the website or in the form: {"yes" if contact_available else "no"}.

Design:
- "preset" is one of: "full-colour" for a site with a strong brand colour (the cover and call to
  action become solid colour blocks), "night" for a dark site, "paper" for a light, neutral site.
- "primary" and "accent" come from this list of colours taken from the website:
  {", ".join(colours)}. Copy one of them exactly. "accent" may be "" when no second colour fits.

Panels, in print order: the outside side left to right, then the inside side left to right.
- The last outside panel is the Cover. Its headline is a short message for the front, six words
  or fewer, and it is not the brand name. The brand name and tagline print from the brand fields.
  Use image_id "{LOGO_IMAGE_ID}" there if a logo is listed.
- Sections: "Cover", "Call to action", "Who we are", "What we offer", "Highlights", "Contact",
  "Gallery". Use "Cover" once and "Contact" at most once. Other sections may repeat when the
  website has more to say on them.
- Use "Contact" only when contact details are available. Gallery shows one image and needs
  no headline.
- Every other panel needs a headline. Pick the sections that the website's content supports.

Available images (JSON). Give a panel an image id from this list, or null. Use each id once:
{json.dumps(_image_list(images, has_logo), ensure_ascii=False, indent=2)}

Return JSON with exactly this shape:
{{"fold": "half or tri or z",
  "design": {{"preset": "", "primary": "#RRGGBB", "accent": ""}},
  "panels": [{{"section": "", "headline": "", "body": "", "image_id": null,
              "generated": false}}]}}"""


def _image_list(images: Sequence[ImageAsset], has_logo: bool) -> list[dict[str, object]]:
    listed: list[dict[str, object]] = [
        {"id": image.image_id, "alt": image.alt, "width": image.width, "height": image.height}
        for image in images
    ]
    if has_logo:
        listed.insert(0, {"id": LOGO_IMAGE_ID, "alt": "Company logo"})
    return listed


def revision_request(message: str, fold: FoldType, panel_count: int) -> str:
    return (
        f"Revise the brochure plan as follows: {message}\n"
        f'Keep the fold "{fold.value}" and exactly {panel_count} panels. Keep the design unless '
        "the request asks to change it. Return the complete updated JSON, and keep any part the "
        "user did not ask to change."
    )


def overview_as_json(overview: Overview) -> str:
    return json.dumps(overview.model_dump(mode="json"), ensure_ascii=False)
