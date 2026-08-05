"""
Веб-сервер для WebApp рулетки.

Маршруты:
  GET  /roulette       — HTML страница рулетки
  POST /api/win        — вызывается из webapp, когда юзер забрал приз
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from bots.manager import get_manager
from bots.scenario import get_engine
from database import get_db

log = logging.getLogger("webapp")

BASE = Path(__file__).resolve().parent


def _verify_init_data(init_data: str, bot_token: str) -> tuple[bool, dict]:
    """Проверка валидности Telegram WebApp initData по HMAC-SHA256."""
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        recv_hash = parsed.pop("hash", "")
        if not recv_hash:
            return False, {}
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if computed != recv_hash:
            return False, {}
        if parsed.get("user"):
            parsed["user"] = json.loads(parsed["user"])
        return True, parsed
    except Exception as e:
        log.warning("verify_init_data: %s", e)
        return False, {}


async def handle_roulette_page(request: web.Request) -> web.Response:
    html_path = BASE / "static" / "roulette.html"
    if not html_path.exists():
        return web.Response(text="Not found", status=404)
    return web.FileResponse(html_path)


async def handle_static_file(request: web.Request) -> web.Response:
    fname = request.match_info["filename"]
    fpath = BASE / "static" / fname
    if not fpath.exists() or not fpath.is_file():
        return web.Response(text="Not found", status=404)
    return web.FileResponse(fpath)


async def handle_win(request: web.Request) -> web.Response:
    """Юзер забрал приз. Двигаем сценарий дальше."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)

    bid = int(body.get("bid") or 0)
    sid = int(body.get("sid") or 0)
    init_data = body.get("init_data") or ""
    if not bid or not sid or not init_data:
        return web.json_response({"ok": False, "error": "missing args"}, status=400)

    db = get_db()
    bot_record = await db.get_greeting_bot(bid)
    if not bot_record:
        return web.json_response({"ok": False, "error": "no bot"}, status=404)

    ok, parsed = _verify_init_data(init_data, bot_record["token"])
    if not ok:
        return web.json_response({"ok": False, "error": "bad signature"}, status=403)

    user = parsed.get("user") or {}
    tg_id = int(user.get("id") or 0)
    if not tg_id:
        return web.json_response({"ok": False, "error": "no user"}, status=400)

    bot = get_manager().get_bot(bid)
    if not bot:
        return web.json_response({"ok": False, "error": "bot not running"}, status=503)

    engine = get_engine()
    try:
        await engine.handle_roulette_done(bot, bot_record, tg_id, 5000)
    except Exception as e:
        log.exception("handle_win: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)
    return web.json_response({"ok": True})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/roulette", handle_roulette_page)
    app.router.add_get("/static/{filename}", handle_static_file)
    app.router.add_post("/api/win", handle_win)
    return app


async def start_webapp(host: str, port: int) -> tuple[web.AppRunner, web.TCPSite]:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("WebApp слушает на http://%s:%s", host, port)
    return runner, site
