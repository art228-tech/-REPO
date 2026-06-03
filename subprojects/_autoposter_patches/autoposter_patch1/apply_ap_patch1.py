#!/usr/bin/env python3
"""
Патч автопостера #1 — три фикса:
1. Премиум-эмодзи на кнопках (icon_custom_emoji_id) — ставится напрямую
   в объект кнопки, минуя конструктор InlineKeyboardButton.
2. Премиум-эмодзи и форматирование в тексте поста с медиа — берём
   message.html_text (а не сырой caption).
3. Удалённая задача убирается из task_ids всех каналов постинга.
"""
from pathlib import Path

ROOT = Path("/opt/autoposter")


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  \u2713 {path.relative_to(ROOT)} \u2014 {label}")


HL = ROOT / "utils/helpers.py"
PE = ROOT / "handlers/post_edit.py"
DB = ROOT / "database/db.py"

# === ФИКС 1: премиум-эмодзи на кнопках ===
patch(
    HL,
    '''        kwargs: dict = {"text": b.get("text", "\u041a\u043d\u043e\u043f\u043a\u0430"), "url": b["url"]}
        if b.get("style"):
            kwargs["style"] = b["style"]
        if b.get("icon_custom_emoji_id"):
            kwargs["icon_custom_emoji_id"] = b["icon_custom_emoji_id"]
        try:
            rows.append([InlineKeyboardButton(**kwargs)])
        except TypeError:
            kwargs.pop("style", None)
            kwargs.pop("icon_custom_emoji_id", None)
            rows.append([InlineKeyboardButton(**kwargs)])''',
    '''        kwargs: dict = {"text": b.get("text", "\u041a\u043d\u043e\u043f\u043a\u0430"), "url": b["url"]}
        if b.get("style"):
            kwargs["style"] = b["style"]
        try:
            btn = InlineKeyboardButton(**kwargs)
        except TypeError:
            kwargs.pop("style", None)
            btn = InlineKeyboardButton(**kwargs)
        # icon_custom_emoji_id нет в конструкторе \u2014 ставим в объект напрямую
        em = b.get("icon_custom_emoji_id")
        if em:
            try:
                object.__setattr__(btn, "icon_custom_emoji_id", em)
            except Exception:
                pass
        rows.append([btn])''',
    "премиум-эмодзи на кнопках",
)

# === ФИКС 2: текст поста с медиа ===
patch(
    PE,
    '''    html = None
    if message.html_text:
        html = message.html_text
    elif message.caption:
        html = message.caption
    cfg["text"] = html''',
    '''    # html_text собирает HTML и из text, и из caption вместе с
    # entities \u2014 премиум-эмодзи и форматирование сохраняются.
    cfg["text"] = message.html_text or None''',
    "текст поста с медиа (html_text)",
)

# === ФИКС 3: delete_task чистит posting_state ===
patch(
    DB,
    '''    async def delete_task(self, task_id: int) -> None:
        await self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await self.conn.commit()''',
    '''    async def delete_task(self, task_id: int) -> None:
        await self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        # убираем задачу из task_ids всех каналов постинга
        import json as _j
        cur = await self.conn.execute(
            "SELECT channel_id, task_ids FROM posting_state"
        )
        rows = await cur.fetchall()
        for r in rows:
            try:
                ids = _j.loads(r["task_ids"] or "[]")
            except Exception:
                ids = []
            if task_id in ids:
                ids = [x for x in ids if x != task_id]
                await self.conn.execute(
                    "UPDATE posting_state SET task_ids=? WHERE channel_id=?",
                    (_j.dumps(ids), r["channel_id"]),
                )
        await self.conn.commit()''',
    "delete_task чистит posting_state",
)

print("\n\u2705 Патч автопостера применён. Перезапусти: systemctl restart autoposter")
