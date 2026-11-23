# Pagifyx

Turns a company's existing website into a print-ready brochure. Covers the source material (Website, Theme, Brand), the physical output (Brochure, Fold, Panel), and the review loop (Overview, Revision, Approval).

## Source

**Website**:
A company's public website. The source of all content, Theme, and Brand for a Brochure.

**Theme**:
The visual system of a Website: palette, fonts, imagery style, and layout feel.
_Avoid_: Style, skin

**Brand**:
The identity of a company: name, logo, tagline, and tone of voice.
_Avoid_: Theme

## Output

**Brochure**:
A Letter-size (8.5" × 11"), landscape, folded document generated from a Website and delivered as `.docx`.

**Fold**:
The physical folding layout a Brochure uses. One of Half-fold, Tri-fold, or Z-fold.

**Half-fold**:
A Fold with 4 Panels, 2 per side, folded in half.

**Tri-fold**:
A Fold with 6 Panels, 3 per side, in a standard letter fold.

**Z-fold**:
A Fold with 6 Panels on the same grid as Tri-fold, where the panels fold in opposite directions.

**Face**:
One side of a Brochure. A Face holds its Panels left to right, as printed. A Tri-fold has an Outside Face and an Inside Face.

**Panel**:
One cell on a Face, the unit that the Overview plans.

## Review

**Overview**:
A Panel-by-panel plan of a Brochure (headline, body copy, and image per Panel), shown to the user before generation.

**Revision**:
A change request the user makes against the Overview in chat. Each Revision goes to the LLM with the full conversation history.

**Approval**:
The user's explicit action that turns the approved Overview into a `.docx`.
_Avoid_: Confirm, finalize
