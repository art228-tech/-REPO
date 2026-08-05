"""
Simple aiohttp server to serve the mini app and handle claim callbacks.
Runs as a separate service in Docker.
"""
import json
import logging
import os
import hmac
import hashlib
from aiohttp import web
from pathlib import Path

logger = logging.getLogger(__name__)

MINIAPP_DIR = Path(__file__).parent
BOT_TOKENS_FILE = "/app/miniapp_tokens.json"  # list of all welcome bot tokens


async def index(request):
    """Serve the roulette HTML."""
    html_path = MINIAPP_DIR / "roulette.html"
    return web.FileResponse(html_path)


async def handle_claim(request):
    """
    Called via Telegram WebApp.sendData → bot receives it via web_app_data update.
    This endpoint is just for direct HTTP fallback if needed.
    """
    return web.json_response({"ok": True})


def create_app():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/roulette", index)
    app.router.add_post("/claim", handle_claim)

    # Serve static files
    app.router.add_static("/static", MINIAPP_DIR)
    return app


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    port = int(os.getenv("MINIAPP_PORT", 8080))
    app = create_app()
    logger.info(f"Mini app server running on port {port}")
    web.run_app(app, port=port)
