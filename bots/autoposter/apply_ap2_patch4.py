#!/usr/bin/env python3
"""
Патч автопостера v2 #4: ВЫБОР цвета кнопок в боте.

ВОЗМОЖНОСТИ:
  1. При создании поста, после шага "кнопки → Готово", если у поста есть
     кнопки — бот спрашивает цвет (🟢/🔴/🔵/⚪) и проставляет style всем
     кнопкам черновика. Без кнопок шаг пропускается.
  2. В карточке существующего поста — кнопка "🎨 Цвет кнопок": меняет цвет
     всех кнопок уже сохранённого поста на лету.

ЗАТРАГИВАЕТ:
  states/fsm.py        — стейт wait_btn_color
  keyboards/kb.py      — клавиатура выбора цвета + кнопка в post_card
  handlers/post_edit.py— перехват pbtn:done → выбор цвета → задержка
  handlers/tasks.py    — хендлеры post_color / pcol:<post>:<style>

ИДЕМПОТЕНТЕН. Запускать venv-питоном из каталога автопостера.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

ROOT = Path("/opt/autoposter")
FSM = ROOT / "states" / "fsm.py"
KB = ROOT / "keyboards" / "kb.py"
PE = ROOT / "handlers" / "post_edit.py"
TS = ROOT / "handlers" / "tasks.py"


def backup(p: Path) -> None:
    if p.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bak = p.with_suffix(p.suffix + f".bak-{stamp}")
        shutil.copy2(p, bak)
        print(f"  ✓ бэкап {p.name} → {bak.name}")


def check(p: Path) -> None:
    import ast
    ast.parse(p.read_text(encoding="utf-8"))
    print(f"  ✓ {p.relative_to(ROOT)} синтаксис OK")


# ============================================================ 1. FSM
def patch_fsm() -> None:
    src = FSM.read_text(encoding="utf-8")
    if "wait_btn_color" in src:
        print("  • fsm: wait_btn_color уже есть")
        return
    if "class PostStates(StatesGroup):" not in src:
        raise SystemExit("fsm: класс PostStates не найден")
    src = src.replace(
        "class PostStates(StatesGroup):",
        "class PostStates(StatesGroup):\n    wait_btn_color = State()",
        1,
    )
    FSM.write_text(src, encoding="utf-8")
    print("  ✓ fsm: стейт wait_btn_color")


# ============================================================ 2. keyboards
KB_COLOR_FN = '''

def buttons_color_choice() -> InlineKeyboardMarkup:
    """Выбор цвета кнопок (Bot API 9.4 style)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Зелёные", callback_data="pcolor:success")],
        [InlineKeyboardButton(text="🔴 Красные", callback_data="pcolor:danger")],
        [InlineKeyboardButton(text="🔵 Синие", callback_data="pcolor:primary")],
        [InlineKeyboardButton(text="⚪ Без цвета", callback_data="pcolor:none")],
    ])


def post_color_choice(post_id: int) -> InlineKeyboardMarkup:
    """Смена цвета кнопок существующего поста."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Зелёные", callback_data=f"pcol:{post_id}:success")],
        [InlineKeyboardButton(text="🔴 Красные", callback_data=f"pcol:{post_id}:danger")],
        [InlineKeyboardButton(text="🔵 Синие", callback_data=f"pcol:{post_id}:primary")],
        [InlineKeyboardButton(text="⚪ Без цвета", callback_data=f"pcol:{post_id}:none")],
        [InlineKeyboardButton(text="« К посту", callback_data=f"post:{post_id}")],
    ])
'''


def patch_kb() -> None:
    src = KB.read_text(encoding="utf-8")

    # 2a. функции выбора цвета
    if "buttons_color_choice" not in src:
        src = src.rstrip() + "\n" + KB_COLOR_FN
        print("  ✓ kb: buttons_color_choice / post_color_choice")
    else:
        print("  • kb: функции цвета уже есть")

    # 2b. кнопка "🎨 Цвет кнопок" в карточке поста
    old = ('    rows.append([InlineKeyboardButton(text="🔗 Ссылки", '
           'callback_data=f"post_links:{post_id}")])\n')
    new = old + ('    rows.append([InlineKeyboardButton(text="🎨 Цвет кнопок", '
                 'callback_data=f"post_color:{post_id}")])\n')
    if 'post_color:{post_id}' in src:
        print("  • kb: кнопка «Цвет кнопок» уже есть")
    elif old in src:
        src = src.replace(old, new, 1)
        print("  ✓ kb: кнопка «🎨 Цвет кнопок» в post_card")
    else:
        print("  ! kb: не нашёл строку с «Ссылки» — кнопку цвета не добавил")

    KB.write_text(src, encoding="utf-8")
    check(KB)


# ============================================================ 3. post_edit
def patch_post_edit() -> None:
    src = PE.read_text(encoding="utf-8")
    if "[patch4]" in src:
        print("  • post_edit: уже пропатчен")
        check(PE)
        return

    # 3a. импорт клавиатуры выбора цвета
    src = src.replace(
        "from keyboards.kb import buttons_choice, task_card",
        "from keyboards.kb import buttons_choice, buttons_color_choice, task_card",
        1,
    )

    # 3b. заменяем обработчик "Готово": если есть кнопки -> спросить цвет,
    #     иначе -> сразу задержка (старое поведение)
    old_done = '''@router.callback_query(PostStates.wait_buttons_choice, F.data == "pbtn:done")
async def cb_pbtn_done(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PostStates.wait_next_delay)
    await cb.message.edit_text(
        "⏱ Через сколько секунд после этого поста публиковать следующий? Пришли число."
    )
    await cb.answer()'''

    new_done = '''# [patch4] после кнопок — спросить цвет (если кнопки есть)
async def _ask_delay(cb_or_msg) -> None:
    await cb_or_msg.edit_text(
        "⏱ Через сколько секунд после этого поста публиковать следующий? Пришли число."
    )


@router.callback_query(PostStates.wait_buttons_choice, F.data == "pbtn:done")
async def cb_pbtn_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft", {})
    has_buttons = False
    if draft.get("buttons"):
        try:
            has_buttons = len(json.loads(draft["buttons"])) > 0
        except Exception:
            has_buttons = False
    if has_buttons:
        await state.set_state(PostStates.wait_btn_color)
        await cb.message.edit_text(
            "🎨 <b>Цвет кнопок</b>\\n\\nВыбери цвет для кнопок поста:",
            reply_markup=buttons_color_choice(),
        )
        await cb.answer()
        return
    await state.set_state(PostStates.wait_next_delay)
    await _ask_delay(cb.message)
    await cb.answer()


@router.callback_query(PostStates.wait_btn_color, F.data.startswith("pcolor:"))
async def cb_pcolor(cb: CallbackQuery, state: FSMContext) -> None:
    style = cb.data.split(":")[1]  # success/danger/primary/none
    data = await state.get_data()
    draft = data.get("draft", {})
    try:
        btns = json.loads(draft["buttons"]) if draft.get("buttons") else []
    except Exception:
        btns = []
    for b in btns:
        if isinstance(b, dict) and b.get("url"):
            if style == "none":
                b.pop("style", None)
            else:
                b["style"] = style
    draft["buttons"] = json.dumps(btns, ensure_ascii=False) if btns else None
    await state.update_data(draft=draft)
    await state.set_state(PostStates.wait_next_delay)
    label = {"success": "🟢 зелёные", "danger": "🔴 красные",
             "primary": "🔵 синие", "none": "⚪ без цвета"}.get(style, style)
    await cb.message.edit_text(
        f"Цвет кнопок: {label}.\\n\\n"
        "⏱ Через сколько секунд после этого поста публиковать следующий? Пришли число."
    )
    await cb.answer()'''

    if old_done in src:
        src = src.replace(old_done, new_done, 1)
        print("  ✓ post_edit: выбор цвета после кнопок")
    else:
        raise SystemExit("post_edit: обработчик pbtn:done не найден (структура отличается)")

    PE.write_text(src, encoding="utf-8")
    check(PE)


# ============================================================ 4. tasks.py
TS_COLOR_HANDLERS = '''


# === [patch4] смена цвета кнопок существующего поста ===
from keyboards.kb import post_color_choice as _post_color_choice


@router.callback_query(F.data.startswith("post_color:"))
async def cb_post_color(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    post_id = int(cb.data.split(":")[1])
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True)
        return
    if post["copy_from_chat"]:
        await cb.answer(
            "У пересланных постов кнопки берутся с оригинала — цвет менять нельзя.",
            show_alert=True,
        )
        return
    if not post["buttons"]:
        await cb.answer("В этом посте нет кнопок", show_alert=True)
        return
    await cb.message.edit_text(
        "🎨 <b>Цвет кнопок</b>\\n\\nВыбери цвет:",
        reply_markup=_post_color_choice(post_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pcol:"))
async def cb_pcol_set(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    _, post_id_s, style = cb.data.split(":")
    post_id = int(post_id_s)
    post = await get_db().get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True)
        return
    try:
        btns = json.loads(post["buttons"]) if post["buttons"] else []
    except Exception:
        btns = []
    for b in btns:
        if isinstance(b, dict) and b.get("url"):
            if style == "none":
                b.pop("style", None)
            else:
                b["style"] = style
    new_buttons = json.dumps(btns, ensure_ascii=False) if btns else None
    await get_db().update_post(post_id, buttons=new_buttons)
    label = {"success": "🟢 зелёные", "danger": "🔴 красные",
             "primary": "🔵 синие", "none": "⚪ без цвета"}.get(style, style)
    post = await get_db().get_post(post_id)
    posts = await get_db().list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    await cb.message.edit_text(
        f"✅ Цвет кнопок изменён: {label}.",
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )
    await cb.answer()
# === [/patch4] ===
'''


def patch_tasks() -> None:
    src = TS.read_text(encoding="utf-8")
    if "[patch4]" in src:
        print("  • tasks: уже пропатчен")
        check(TS)
        return
    src = src.rstrip() + "\n" + TS_COLOR_HANDLERS
    TS.write_text(src, encoding="utf-8")
    print("  ✓ tasks: хендлеры post_color / pcol")
    check(TS)


# ============================================================ main
def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"Каталог {ROOT} не найден")
    print("0) Бэкапы…")
    for p in (FSM, KB, PE, TS):
        backup(p)
    print("1) fsm.py…")
    patch_fsm()
    check(FSM)
    print("2) keyboards/kb.py…")
    patch_kb()
    print("3) handlers/post_edit.py…")
    patch_post_edit()
    print("4) handlers/tasks.py…")
    patch_tasks()
    print("\n✅ Патч применён. Перезапусти: systemctl restart autoposter")


if __name__ == "__main__":
    main()
