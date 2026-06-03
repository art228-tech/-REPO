#!/usr/bin/env python3
"""
Патч 28: убрать сырой текст шага из карточки в конструкторе
(он провоцирует PEER_FLOOD при edit_text из-за плотности кастомных
эмодзи и url). Вместо рендера текста — пометка с длиной и кнопка
«Посмотреть текст», которая шлёт текст отдельным сообщением.

На сам сценарий для пользователей это НЕ влияет — юзеры приветки
получают тексты как раньше.
"""
from pathlib import Path

ROOT = Path("/opt/bot")


def patch(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding="utf-8")
    if old not in src:
        raise SystemExit(f"NOT FOUND ({label}) in {path.name}:\n---\n{old[:300]}\n---")
    src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  \u2713 {path.relative_to(ROOT)} \u2014 {label}")


SE = ROOT / "handlers/scenario_edit.py"
KB = ROOT / "keyboards/constructor_kb.py"

# === 1. _describe_step: убираем сырой текст, оставляем длину ===
patch(
    SE,
    '''            f"🎰 <b>Рулетка</b>\\n"
            f"Текст: {html.escape((cfg.get('text') or '—')[:200])}\\n"''',
    '''            f"🎰 <b>Рулетка</b>\\n"
            f"📝 Текст: {len(cfg.get('text') or '')} симв.\\n"''',
    "рулетка: текст → длина",
)

patch(
    SE,
    '''            f"📢 <b>Обязательная подписка</b>\\n"
            f"Текст: {html.escape((cfg.get('text') or '—')[:200])}\\n"''',
    '''            f"📢 <b>Обязательная подписка</b>\\n"
            f"📝 Текст: {len(cfg.get('text') or '')} симв.\\n"''',
    "ОП: текст → длина",
)

patch(
    SE,
    '''            f"💬 <b>Сообщение</b>\\n"
            f"Текст: {html.escape((cfg.get('text') or '—')[:200])}\\n"''',
    '''            f"💬 <b>Сообщение</b>\\n"
            f"📝 Текст: {len(cfg.get('text') or '')} симв.\\n"''',
    "сообщение: текст → длина",
)

# === 2. step_view: добавляем кнопку «Посмотреть текст» ===
patch(
    KB,
    '''def step_view(step_id: int, bot_id: int, step_type: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"step_up:{step_id}"),
            InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"step_dn:{step_id}"),
        ],
    ]
    if step_type == "op":
        rows.append([InlineKeyboardButton(text="👥 Спонсоры", callback_data=f"spons:{step_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить шаг", callback_data=f"step_del:{step_id}")])
    rows.append([InlineKeyboardButton(text="« К сценарию", callback_data=f"scn:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)''',
    '''def step_view(step_id: int, bot_id: int, step_type: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"step_up:{step_id}"),
            InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"step_dn:{step_id}"),
        ],
        [InlineKeyboardButton(text="👁 Посмотреть текст", callback_data=f"step_txt:{step_id}")],
    ]
    if step_type == "op":
        rows.append([InlineKeyboardButton(text="👥 Спонсоры", callback_data=f"spons:{step_id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить шаг", callback_data=f"step_del:{step_id}")])
    rows.append([InlineKeyboardButton(text="« К сценарию", callback_data=f"scn:{bot_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)''',
    "кнопка «Посмотреть текст» в step_view",
)

# === 3. Хендлер step_txt — шлёт текст отдельным сообщением ===
se_src = SE.read_text(encoding="utf-8")
if "step_txt" not in se_src:
    handler = '''


@router.callback_query(F.data.startswith("step_txt:"))
async def cb_step_text(cb: CallbackQuery, state: FSMContext) -> None:
    """Показывает сырой текст шага отдельным сообщением, чтобы избежать
    PEER_FLOOD при edit_text карточки шага с плотным контентом."""
    if not is_admin(cb.from_user.id):
        await cb.answer("\u26d4", show_alert=True)
        return
    step_id = int(cb.data.split(":")[1])
    step = await get_db().get_step(step_id)
    if not step:
        await cb.answer("Шаг не найден", show_alert=True)
        return
    cfg = json.loads(step["config"])
    text = cfg.get("text") or ""
    if not text:
        await cb.answer("У шага нет текста", show_alert=True)
        return
    try:
        await cb.message.answer(
            text,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as e:
        await cb.answer(f"Не удалось показать: {e}", show_alert=True)
        return
    await cb.answer()
'''
    se_src = se_src + handler
    # импорт LinkPreviewOptions
    if "LinkPreviewOptions" not in se_src:
        se_src = se_src.replace(
            "from aiogram.types import",
            "from aiogram.types import LinkPreviewOptions,",
            1,
        )
    SE.write_text(se_src, encoding="utf-8")
    print("  \u2713 handlers/scenario_edit.py \u2014 хендлер step_txt")

print("\\n\u2705 Патч 28 применён. Перезапусти: systemctl restart bot")
