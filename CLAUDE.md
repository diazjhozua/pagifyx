# pagifyx

pagifyx turns an existing company website into a print-ready brochure (.docx). It is a local web app. It reads the site with Playwright, asks an LLM to plan the brochure, lets the user revise the plan in a chat, then writes a Word file the user can edit.

## Scenario

The company already has a website, a theme, a logo, and a brand. The brochure is built from those, not designed from scratch. Terms: Website, Theme, Brand, Fold, Overview, Revision, Approval. A Face is one side of a Brochure. A Panel is one cell on a Face.

## Current state

The original plan is built. This section is the reference for working on it.

- Interface: local FastAPI + Jinja2 web app bound to 127.0.0.1. Start with `uv run pagifyx` (port 8000). It needs a `.env` file.
- LLM: any OpenAI-compatible Chat Completions endpoint, configured through `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in `.env`. Output is requested in the prompt, validated with pydantic, and retried once. Do not use provider-specific `response_format`.
- Stack: Python 3.12 (`.python-version`), uv with `pyproject.toml` and `uv.lock`, hatchling build, src layout at `src/pagifyx/`.
- Layout: modules are grouped by responsibility under `src/pagifyx/`: `core/` (config, models, folds, theme, fonts, brand), `reading/` (scraper, images, assets), `llm/` (client, prompts), `output/` (docx_builder), `workflow/` (service, session), `web/` (app, routes, templates, static). Imports point downward only: `core` imports nothing above it. Tests mirror the groups under `tests/`.
- Plan: the model returns one `Overview` (fold, design, panels in print order). The fold is the model's choice unless the user picks one. `core/folds.py` `check_plan` checks the panel count (half 4, tri and z 6), one Cover as the last outside panel, Contact only with contact details, and image ids. `core/grounding.py` `check_grounding` rejects any number or email not in the website text or the form. A failed check gets one retry.
- Design: `Preset` (full-colour, night, paper) is chosen by the model from the site's own theme. Its primary and accent must come from the colour list `core/theme.py` `candidate_colours` builds from the site. `build_palette` derives paper and ink and darkens the primary until text reads at 4.5:1.
- Brand (name, tagline, logo) lives in `core/brand.py` and `core/models.py`. Theme (palette, font) lives in `core/theme.py`. Keep them separate.
- Workflow steps run under `Session.lock`. Compute the new state in locals and assign it only after the LLM call succeeds.
- Module reference and a step-by-step code walkthrough: `docs/index.html` (static guide, update by hand when modules change).
- Setup and workflow files in place: `.gitignore` (ignores `.env`, `/output/`), `.env.template`.

## Working rules

- Git: work on `main`. Commit only when the user asks.
- Pydantic models treat null from the model as empty text or an empty list (`BeforeValidator` in `core/models.py`).
- Routes in `web/routes.py` catch workflow errors through `_attempt`. Do not add `try` blocks to each route.

### Developer notes

- Setup: `uv python install 3.12`, `uv sync`, `uv run playwright install chromium`. Copy `.env.template` to `.env` first. The app fails at startup without the three LLM variables.
- Checks: `uv run ruff format src tests`, `uv run ruff check src tests`, `uv run pytest`. The 88 tests are offline. They use the `make_chat` fixture (scripted LLM) and monkeypatch `pagifyx.workflow.service.scrape_site`. Async tests use an `asyncio.run` helper, because pytest-asyncio is not installed.
- Real-browser check: there is no fixture site in the repo. Serve a folder with `python -m http.server 8765` and call `scrape_site("http://127.0.0.1:8765/")`.
- Image validation uses python-docx `Image.from_blob` (`images.is_embeddable`). It checks headers only, so truncated images can still embed.
- Font detection reads the Windows registry (`core/fonts.py`). On other platforms every site font falls back to Calibri.
- Computed colors can come back as `oklch()`/`oklab()` (modern CSS). `theme.parse_color` converts them. Test that form, not only `rgb()`.
- WebSearch fails in this environment with a LiteLLM Bedrock tool error. Do not rely on it for research.
- End-to-end run: start `uv run pagifyx` in the background and wait for HTTP 200 on `/`. Drive the flow with httpx and `follow_redirects=True`: `POST /sessions`, `/fold`, `/revise`, `/approve`, then `GET /download`. Keep helper scripts outside the repo.
- Real websites: check `robots.txt` first. A 403 from bot protection is a valid error. Do not work around it. The paste fallback is the supported path.
- Logo: `_capture_logo` captures the logo mark (the outermost small painted box around the logo icon) on a transparent page at `LOGO_SCALE`, through CDP `Page.captureScreenshot`. Playwright screenshots ignore device-scale overrides, so do not switch back to `locator.screenshot`.
- Site files are named per read (`read-<id>-*`). `Session.commit_read` deletes the previous read's files only after the model succeeds. Uploaded logos are never deleted by a read.
- `output/` holds generated `.docx` files and downloaded assets. It is gitignored, and it accumulates test sessions.
- Word compatibility: `output/docx_builder.py` writes OOXML children in schema order (`_insert_ordered` with `_TCPR_ORDER` and `_PPR_ORDER`). Out-of-order children make Word report the file as damaged.
- Do not add cell top or bottom padding to the docx. It pushed content onto a blank extra page. Use `space_before` on the first paragraph, and keep the spacer paragraph after each table at 1 pt.
- Face typography: `THREE_ACROSS` for 3-panel faces, `TWO_ACROSS` for 2-panel faces. Both use one scale (cover, headline, lead, body).
- Presets: `output/docx_builder.py` `_look` maps each `Preset` to cell fills and text colours. Headlines have no all-caps labels. Text colours come from `Palette.text_on`, so they always pass the contrast minimum.
- Visual check of a `.docx`: no renderer is on PATH. Export through Word with pywin32 (`ExportAsFixedFormat(path, 17)`), then render pages with pypdfium2. Run with `uv run --no-project --with pywin32 --with pypdfium2 --with pillow python`. PowerShell COM is blocked here. Run one Word export at a time, because parallel exports hang.
- On Windows Git Bash, stop a server with `netstat -ano` to find the PID, then `taskkill //PID <n> //F`.
- Bash on Windows: each call starts in the repo root, so use absolute paths. Long `sleep` calls are blocked. Wait for background jobs with a Monitor and an until-loop.
- `Write` on an existing file requires reading it first. Re-read files after `ruff format`, because it can change them on disk.

### Known gaps

- Z-fold `.docx` is identical to tri-fold. The "panels fold opposite ways" instruction is not printed.
- Sessions live in memory and are lost on restart.
- Logo capture only sees logos in the header or nav, or elements with "logo" in their class or alt. Other sites fall back to og:image. A dark logo on a dark cover has little contrast.
- Inside faces look sparse when the site has little copy or few images. The lower half of a panel stays empty.
- The `generated` flag is the model's own judgment. Code checks numbers and emails only, not invented claims such as "award-winning". The model also marks almost every panel as generated.
