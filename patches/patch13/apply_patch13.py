#!/usr/bin/env python3
"""
Патч 13: при копировании кнопок поста сохраняются также цвет (style)
и премиум-стикер (icon_custom_emoji_id). build_inline_keyboard учит
эти поля рендерить.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path("/opt/bot")


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:250]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)} — {label}")


# === 1. step_create.py — извлекаем style + icon_custom_emoji_id ===
SC = ROOT / "handlers/step_create.py"
patch(
    SC,
    '''    if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
        orig_btns = []
        for row in message.reply_markup.inline_keyboard:
            line = []
            for b in row:
                if b.url:
                    line.append({"text": b.text, "url": b.url})
                # callback_data-кнопки чужого бота пропускаем — не переносимы
            if line:
                orig_btns.append(line)
        if orig_btns:
            cfg["_orig_buttons"] = orig_btns''',
    '''    if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
        orig_btns = []
        for row in message.reply_markup.inline_keyboard:
            line = []
            for b in row:
                if b.url:
                    btn = {"text": b.text, "url": b.url}
                    # Нативный цвет кнопки (Bot API 9.4)
                    _style = getattr(b, "style", None)
                    if _style:
                        btn["style"] = _style
                    # Премиум-стикер на кнопке
                    _emoji = getattr(b, "icon_custom_emoji_id", None)
                    if _emoji:
                        btn["icon_custom_emoji_id"] = _emoji
                    line.append(btn)
                # callback_data-кнопки чужого бота пропускаем — не переносимы
            if line:
                orig_btns.append(line)
        if orig_btns:
            cfg["_orig_buttons"] = orig_btns''',
    "извлечение style+emoji",
)

# === 2. step_create.py — при keep сохраняем эти поля ===
patch(
    SC,
    '''        flat = []
        for row in orig:
            for b in row:
                if b.get("url"):
                    flat.append({"text": b["text"], "url": b["url"]})
        draft["buttons"] = flat''',
    '''        flat = []
        for row in orig:
            for b in row:
                if b.get("url"):
                    nb = {"text": b["text"], "url": b["url"]}
                    if b.get("style"):
                        nb["style"] = b["style"]
                    if b.get("icon_custom_emoji_id"):
                        nb["icon_custom_emoji_id"] = b["icon_custom_emoji_id"]
                    flat.append(nb)
        draft["buttons"] = flat''',
    "сохранение style+emoji в buttons",
)

# === 3. helpers.py — build_inline_keyboard учит style + icon_custom_emoji_id ===
HL = ROOT / "utils/helpers.py"
patch(
    HL,
    '''            text = color_button_text(btn.get("text", "Кнопка"), btn.get("color", "default"))
            kwargs: dict[str, Any] = {"text": text}
            if btn.get("url"):
                kwargs["url"] = btn["url"]
            elif btn.get("callback_data"):
                kwargs["callback_data"] = btn["callback_data"]
            elif btn.get("web_app"):
                from aiogram.types import WebAppInfo
                kwargs["web_app"] = WebAppInfo(url=btn["web_app"])
            else:
                continue
            line.append(InlineKeyboardButton(**kwargs))''',
    '''            text = color_button_text(btn.get("text", "Кнопка"), btn.get("color", "default"))
            kwargs: dict[str, Any] = {"text": text}
            if btn.get("url"):
                kwargs["url"] = btn["url"]
            elif btn.get("callback_data"):
                kwargs["callback_data"] = btn["callback_data"]
            elif btn.get("web_app"):
                from aiogram.types import WebAppInfo
                kwargs["web_app"] = WebAppInfo(url=btn["web_app"])
            else:
                continue
            # Нативный цвет (Bot API 9.4) и премиум-стикер.
            # Передаём через kwargs — если поле не поддерживается, отлавливаем.
            if btn.get("style"):
                kwargs["style"] = btn["style"]
            if btn.get("icon_custom_emoji_id"):
                kwargs["icon_custom_emoji_id"] = btn["icon_custom_emoji_id"]
            try:
                line.append(InlineKeyboardButton(**kwargs))
            except TypeError:
                # старый aiogram без style/icon — убираем эти поля
                kwargs.pop("style", None)
                kwargs.pop("icon_custom_emoji_id", None)
                line.append(InlineKeyboardButton(**kwargs))''',
    "рендер style+emoji",
)

# === 4. дочистка БД — переносим style/emoji в уже сохранённые шаги нельзя
#         (старых данных нет), просто сообщаем ===
print("  ✓ существующие шаги не трогаем — пересоздай шаг чтобы стили подтянулись")

print("\n✅ Патч 13 применён. Перезапусти: systemctl restart bot")
