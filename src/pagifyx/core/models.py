"""Data shapes exchanged with the LLM and used to build the brochure."""

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

LOGO_IMAGE_ID = "logo"


def _blank_if_null(value: Any) -> Any:
    return "" if value is None else value


def _empty_list_if_null(value: Any) -> Any:
    return [] if value is None else value


def _empty_object_if_null(value: Any) -> Any:
    return {} if value is None else value


def _false_if_null(value: Any) -> Any:
    return False if value is None else value


# The model may send null for a missing fact. Treat that as empty rather than failing the read.
Text = Annotated[str, BeforeValidator(_blank_if_null)]
TextList = Annotated[list[str], BeforeValidator(_empty_list_if_null)]


class FoldType(StrEnum):
    HALF = "half"
    TRI = "tri"
    Z = "z"


class PanelSection(StrEnum):
    """The content role of one panel. The model picks the roles that the website supports."""

    COVER = "Cover"
    CALL_TO_ACTION = "Call to action"
    WHO_WE_ARE = "Who we are"
    WHAT_WE_OFFER = "What we offer"
    HIGHLIGHTS = "Highlights"
    CONTACT = "Contact"
    GALLERY = "Gallery"


class Preset(StrEnum):
    """A look for the whole brochure. The model picks one from the website's theme."""

    FULL_COLOUR = "full-colour"
    NIGHT = "night"
    PAPER = "paper"


class BrandText(BaseModel):
    """Brand wording extracted from the website by the LLM."""

    name: Text = ""
    tagline: Text = ""
    tone: Text = ""


class Contact(BaseModel):
    phone: str | None = None
    email: str | None = None
    address: str | None = None

    def has_details(self) -> bool:
        return any((self.phone, self.email, self.address))


class SiteContent(BaseModel):
    """Content facts found on the website. The LLM must not invent any of these."""

    who_we_are: Text = ""
    offerings: TextList = Field(default_factory=list)
    highlights: TextList = Field(default_factory=list)
    contact: Annotated[Contact, BeforeValidator(_empty_object_if_null)] = Field(
        default_factory=Contact
    )


class SiteAnalysis(BaseModel):
    """Fold-independent analysis of a website: brand wording and content."""

    language: Text = "en"
    brand: Annotated[BrandText, BeforeValidator(_empty_object_if_null)] = Field(
        default_factory=BrandText
    )
    content: Annotated[SiteContent, BeforeValidator(_empty_object_if_null)] = Field(
        default_factory=SiteContent
    )


class Panel(BaseModel):
    """One panel of the brochure. `generated` marks wording that is not from the website."""

    section: PanelSection
    headline: Text = ""
    body: Text = ""
    image_id: str | None = None
    generated: Annotated[bool, BeforeValidator(_false_if_null)] = False


class Design(BaseModel):
    """The look of the brochure: a preset, plus the website colours chosen for it."""

    preset: Preset
    primary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: Text = ""


class Overview(BaseModel):
    """The brochure plan: fold, design, and panels in print order.

    Panels run left to right across the outside side, then left to right across the inside.
    """

    fold: FoldType
    design: Design
    panels: list[Panel]
