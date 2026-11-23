"""Start the local web app: `uv run pagifyx`. Binds to 127.0.0.1 only."""

import logging

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run("pagifyx.web.app:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
