#!/usr/bin/env python3
"""
Патч 9: финальный фикс кнопок пересланного поста.

Проблема: посты из ботов-розыгрышей приходят с forward_origin type='user'
(а не 'channel'). copy_message от чужого бота часто не работает, а кнопки
терялись, т.к. извлекались только внутри forward-блока.

Решение:
- Кнопки-ссылки (url) извлекаются из reply_markup ВСЕГДА — переслано или нет.
- copy_from используем только для пересылок из КАНАЛА. Для постов от
  пользователя/бота — сохраняем контент напрямую (текст + фото).
"""
from pathlib import Path

ROOT = Path("/opt/bot")
SC = ROOT / "handlers/step_create.py"


def patch(path: Path, edits):
    src = path.read_text(encoding="utf-8")
    for old, new in edits:
        if old not in src:
            raise SystemExit(f"NOT FOUND in {path.name}:\n---\n{old[:300]}\n---")
        src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)}")


src = SC.read_text(encoding="utf-8")

# Находим текущий forward-блок (после патча 8 он мог измениться — поддержим оба варианта).
import re

# Вырезаем весь блок от "# Telegram отдаёт данные" / "# Если это пересланное"
# до "return cfg" — и ставим новую логику.
m = re.search(
    r"\n(    #[^\n]*\n)?    (?:_fwd_chat_id = None|if message\.forward_from_chat).*?\n    return cfg\n",
    src, re.DOTALL,
)
if not m:
    raise SystemExit("Не нашёл forward-блок в _extract_content — структура неожиданная")

new_block = '''
    # --- Кнопки-ссылки извлекаем ВСЕГДА (переслано сообщение или нет) ---
    if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
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
            cfg["_orig_buttons"] = orig_btns

    # --- copy_from только для пересылок из КАНАЛА ---
    fwd_chat = None
    fwd_mid = None
    if message.forward_from_chat and message.forward_from_message_id:
        # старый API
        if getattr(message.forward_from_chat, "type", None) == "channel":
            fwd_chat = message.forward_from_chat.id
            fwd_mid = message.forward_from_message_id
    else:
        origin = getattr(message, "forward_origin", None)
        if origin is not None and getattr(origin, "type", None) == "channel":
            och = getattr(origin, "chat", None)
            omid = getattr(origin, "message_id", None)
            if och is not None and omid is not None:
                fwd_chat = och.id
                fwd_mid = omid
    if fwd_chat is not None and fwd_mid is not None:
        cfg["copy_from"] = {"chat_id": fwd_chat, "message_id": fwd_mid}
        # при копировании поста из канала контент берём из самого поста
        for k in ("photo_file_id", "sticker_file_id", "animation_file_id",
                  "video_file_id", "document_file_id", "text"):
            cfg.pop(k, None)
    # Если переслано от пользователя/бота (не канал) — copy_from НЕ ставим,
    # контент (текст+медиа) уже сохранён выше как обычное сообщение.
    return cfg
'''

src = src[:m.start()] + new_block + src[m.end():]
SC.write_text(src, encoding="utf-8")
print("  ✓ handlers/step_create.py (_extract_content переписан)")

print("\n✅ Патч 9 применён. Перезапусти: systemctl restart bot")
