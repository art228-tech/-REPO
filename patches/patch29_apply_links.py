#!/usr/bin/env python3
"""
Патч 29 для конструктора приветок: редактирование ссылок в шагах сценария.

В карточке шага — кнопка «🔗 Ссылки».
Показывает уникальные ссылки из текста шага (внутри <a href="...">) и из его
кнопок (cfg["buttons"][i]["url"]). Тап на ссылку → бот просит новую → меняет
её ВЕЗДЕ по точному совпадению (и в тексте, и во всех кнопках где была).

Для шагов с copy_from (скопированный пост) не работает — там контент чужой
(копируется Telegram-ом 1-в-1).

Зависимости: должен быть применён патч 28 (кнопка «👁 Посмотреть текст» в
step_view). Если её нет — патч всё равно ляжет, но будет слегка иначе
выглядеть. Не критично.
"""
import re
from pathlib import Path

ROOT = Path("/opt/bot")


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  \u2713 {path.relative_to(ROOT)} \u2014 {label}")


FSM = ROOT / "states/fsm.py"
KB = ROOT / "keyboards/constructor_kb.py"
SE = ROOT / "handlers/scenario_edit.py"
DB = ROOT / "database/db.py"

# === 1. FSM-стейт ===
fsm_src = FSM.read_text(encoding="utf-8")
if "step_link_new_url" not in fsm_src:
    # вставляем в группу StepStates если есть, иначе добавляем класс
    if "class StepStates(StatesGroup):" in fsm_src:
        fsm_src = fsm_src.replace(
            "class StepStates(StatesGroup):",
            "class StepStates(StatesGroup):\n    step_link_new_url = State()",
            1,
        )
    else:
        fsm_src += (
            "\n\nclass StepStates(StatesGroup):\n"
            "    step_link_new_url = State()\n"
        )
    FSM.write_text(fsm_src, encoding="utf-8")
    print("  \u2713 states/fsm.py \u2014 стейт step_link_new_url")

# === 2. Кнопка «🔗 Ссылки» в step_view ===
# Пытаемся вставить кнопку рядом с «👁 Посмотреть текст» (патч 28).
# Если её нет — вставляем перед «🗑 Удалить шаг».
kb_src = KB.read_text(encoding="utf-8")
v_text_btn = '[InlineKeyboardButton(text="👁 Посмотреть текст", callback_data=f"step_txt:{step_id}")],'
del_btn = '    rows.append([InlineKeyboardButton(text="🗑 Удалить шаг", callback_data=f"step_del:{step_id}")])'
links_line = '[InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"step_links:{step_id}")],'

if "step_links" not in kb_src:
    if v_text_btn in kb_src:
        kb_src = kb_src.replace(
            v_text_btn,
            v_text_btn + "\n        " + links_line,
            1,
        )
        KB.write_text(kb_src, encoding="utf-8")
        print("  \u2713 keyboards/constructor_kb.py \u2014 кнопка «Ссылки» (рядом с просмотром текста)")
    elif del_btn in kb_src:
        # старая структура — отдельная строка перед удалением
        kb_src = kb_src.replace(
            del_btn,
            '    rows.append([InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"step_links:{step_id}")])\n' + del_btn,
            1,
        )
        KB.write_text(kb_src, encoding="utf-8")
        print("  \u2713 keyboards/constructor_kb.py \u2014 кнопка «Ссылки» (перед удалением)")
    else:
        raise SystemExit("в step_view нет ни «Посмотреть текст», ни «Удалить шаг» — куда вставлять?")

# === 3. update_step в БД ===
db_src = DB.read_text(encoding="utf-8")
if "async def update_step" not in db_src:
    # вставляем после get_step
    anchor = "    async def get_step(self"
    if anchor not in db_src:
        raise SystemExit("в db.py нет get_step — не туда патч")
    method = (
        "    async def update_step(self, step_id: int, **fields) -> None:\n"
        "        if not fields:\n"
        "            return\n"
        "        sets = ', '.join(f'{k}=?' for k in fields)\n"
        "        params = list(fields.values()) + [step_id]\n"
        "        await self.conn.execute(f'UPDATE steps SET {sets} WHERE id=?', params)\n"
        "        await self.conn.commit()\n\n"
    )
    db_src = db_src.replace(anchor, method + anchor, 1)
    DB.write_text(db_src, encoding="utf-8")
    print("  \u2713 database/db.py \u2014 метод update_step")

# === 4. Хендлеры step_links / plink_pick / wait_new_url в scenario_edit.py ===
se_src = SE.read_text(encoding="utf-8")
if "step_links" not in se_src:
    handlers = '''


import re as _re_links


def _extract_step_links(cfg: dict) -> list[str]:
    """Уникальные ссылки из html-текста и из кнопок шага."""
    urls: list[str] = []
    seen = set()
    text = cfg.get("text") or ""
    for m in _re_links.finditer(r'href=[\\\'"]([^\\\'"]+)[\\\'"]', text):
        u = m.group(1)
        if u not in seen:
            seen.add(u); urls.append(u)
    for b in (cfg.get("buttons") or []):
        u = b.get("url")
        if u and u not in seen:
            seen.add(u); urls.append(u)
    return urls


def _replace_step_link(cfg: dict, old_url: str, new_url: str) -> dict:
    """Возвращает обновлённый cfg с заменой ссылки везде."""
    cfg = dict(cfg)
    text = cfg.get("text") or ""
    if text:
        cfg["text"] = _re_links.sub(
            r'href=([\\\'"])' + _re_links.escape(old_url) + r'\\1',
            lambda m: f'href={m.group(1)}{new_url}{m.group(1)}',
            text,
        )
    btns = cfg.get("buttons") or []
    new_btns = []
    for b in btns:
        if isinstance(b, dict):
            b = dict(b)
            if b.get("url") == old_url:
                b["url"] = new_url
        new_btns.append(b)
    cfg["buttons"] = new_btns
    return cfg


@router.callback_query(F.data.startswith("step_links:"))
async def cb_step_links(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("\u26d4", show_alert=True)
        return
    await state.clear()
    step_id = int(cb.data.split(":")[1])
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    cfg = json.loads(step["config"])
    if cfg.get("copy_from"):
        await cb.answer(
            "В скопированных постах нельзя \u2014 контент чужой, копируется Telegram-ом 1\u2011в\u20111.",
            show_alert=True,
        )
        return
    urls = _extract_step_links(cfg)
    if not urls:
        await cb.answer("В этом шаге нет ссылок", show_alert=True)
        return
    await state.update_data(_link_step_id=step_id, _link_urls=urls)
    rows = []
    for i, u in enumerate(urls):
        short = u if len(u) <= 60 else u[:57] + "..."
        rows.append([InlineKeyboardButton(text=f"\U0001F517 {short}", callback_data=f"plink:{i}")])
    rows.append([InlineKeyboardButton(text="\u00ab К шагу", callback_data=f"step:{step_id}")])
    await cb.message.edit_text(
        "<b>\U0001F517 Ссылки в шаге</b>\\n\\nВыбери, какую заменить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("plink:"))
async def cb_plink_pick(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    idx = int(cb.data.split(":")[1])
    data = await state.get_data()
    urls = data.get("_link_urls", [])
    step_id = data.get("_link_step_id")
    if idx >= len(urls) or not step_id:
        await cb.answer("Сессия устарела, открой ссылки заново", show_alert=True)
        return
    old = urls[idx]
    await state.update_data(_link_old=old)
    await state.set_state(StepStates.step_link_new_url)
    await cb.message.edit_text(
        f"\u0421\u0442\u0430\u0440\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430: <code>{old}</code>\\n\\n"
        "\u041f\u0440\u0438\u0448\u043b\u0438 <b>\u043d\u043e\u0432\u0443\u044e \u0441\u0441\u044b\u043b\u043a\u0443</b> (http://... или https://... или tg://...). "
        "\u0417\u0430\u043c\u0435\u043d\u044e \u0432\u0435\u0437\u0434\u0435 \u0432 \u044d\u0442\u043e\u043c \u0448\u0430\u0433\u0435."
    )
    await cb.answer()


@router.message(StepStates.step_link_new_url)
async def m_plink_new(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    new = (message.text or "").strip()
    if not (new.startswith("http://") or new.startswith("https://") or new.startswith("tg://")):
        await message.answer("Нужна корректная ссылка (http/https/tg).")
        return
    data = await state.get_data()
    step_id = data.get("_link_step_id")
    old = data.get("_link_old")
    if not step_id or not old:
        await message.answer("Сессия устарела.")
        await state.clear()
        return
    step = await get_db().get_step(step_id)
    if not step:
        await state.clear()
        return
    cfg = json.loads(step["config"])
    new_cfg = _replace_step_link(cfg, old, new)
    await get_db().update_step(step_id, config=json.dumps(new_cfg, ensure_ascii=False))
    await state.clear()
    await message.answer(
        f"\u2705 \u0421\u0441\u044b\u043b\u043a\u0430 \u0437\u0430\u043c\u0435\u043d\u0435\u043d\u0430 \u0432 \u0448\u0430\u0433\u0435:\\n"
        f"\u00ab<code>{old}</code>\u00bb\\n\u2192 \u00ab<code>{new}</code>\u00bb"
    )
'''
    # импорты
    if "InlineKeyboardButton" not in se_src:
        se_src = se_src.replace(
            "from aiogram.types import",
            "from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup,",
            1,
        )
    if "import json" not in se_src:
        se_src = se_src.replace(
            "from __future__ import annotations",
            "from __future__ import annotations\n\nimport json",
            1,
        )
    if "StepStates" not in se_src:
        se_src = se_src.replace(
            "from states.fsm import",
            "from states.fsm import StepStates,",
            1,
        )

    se_src += handlers
    SE.write_text(se_src, encoding="utf-8")
    print("  \u2713 handlers/scenario_edit.py \u2014 хендлеры редактирования ссылок")

print("\\n\u2705 Патч 29 применён. Перезапусти: systemctl restart bot")
