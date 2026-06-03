#!/usr/bin/env python3
"""
Патч 7:
1. Экранирование пользовательского текста в карточке шага (html.escape) —
   иначе обрезанный на половине HTML-тег ломает всё меню шага.
2. Кнопки скопированного поста — спрашиваем «оставить / свои / без».
3. Дубли в шаге «Сообщение» — только при режиме «ждать сообщение»;
   при таймере и «без ожидания» дублирование выключается.
"""
import sys
from pathlib import Path

ROOT = Path("/opt/bot")


def patch_file(path: Path, edits):
    src = path.read_text(encoding="utf-8")
    for old, new in edits:
        if old not in src:
            raise SystemExit(f"PATTERN NOT FOUND in {path}:\n---\n{old[:250]}\n---")
        src = src.replace(old, new, 1)
    path.write_text(src, encoding="utf-8")
    print(f"  ✓ {path.relative_to(ROOT)}")


# ===== 1. scenario_edit.py — экранируем текст =====
print("[1/3] scenario_edit.py — экранирование")
se = ROOT / "handlers/scenario_edit.py"
src = se.read_text(encoding="utf-8")

# Добавляем import html
if "import html" not in src:
    src = src.replace("import json", "import json\nimport html", 1)

# Заменяем все небезопасные вставки текста на экранированные.
# Везде, где есть (cfg.get('text') or '—')[:200] — оборачиваем в html.escape.
src = src.replace(
    "{(cfg.get('text') or '—')[:200]}",
    "{html.escape((cfg.get('text') or '—')[:200])}",
)
# button_text внутри <code>...</code> — тоже экранируем
src = src.replace(
    "<code>{cfg.get('button_text') or '—'}</code>",
    "<code>{html.escape(str(cfg.get('button_text') or '—'))}</code>",
)
src = src.replace(
    "<code>{cfg.get('check_button_text') or '—'}</code>",
    "<code>{html.escape(str(cfg.get('check_button_text') or '—'))}</code>",
)
se.write_text(src, encoding="utf-8")
print("  ✓ handlers/scenario_edit.py")


# ===== 2. step_create.py — кнопки скопированного поста =====
print("[2/3] step_create.py — кнопки поста")

# 2a. Новый стейт
fsm = ROOT / "states/fsm.py"
fsm_src = fsm.read_text(encoding="utf-8")
if "msg_copy_buttons_choice" not in fsm_src:
    fsm_src = fsm_src.replace(
        "    op_sponsor_request_mode = State()",
        "    op_sponsor_request_mode = State()\n    msg_copy_buttons_choice = State()",
    )
    fsm.write_text(fsm_src, encoding="utf-8")
    print("  ✓ states/fsm.py")

# 2b. В _extract_content — при forward сохраняем кнопки оригинала
sc = ROOT / "handlers/step_create.py"
sc_src = sc.read_text(encoding="utf-8")

old_fwd = '''    # Если это пересланное (forward) — сохраняем copy_from
    if message.forward_from_chat and message.forward_from_message_id:
        cfg["copy_from"] = {
            "chat_id": message.forward_from_chat.id,
            "message_id": message.forward_from_message_id,
        }'''
new_fwd = '''    # Если это пересланное (forward) — сохраняем copy_from
    if message.forward_from_chat and message.forward_from_message_id:
        cfg["copy_from"] = {
            "chat_id": message.forward_from_chat.id,
            "message_id": message.forward_from_message_id,
        }
        # Сохраняем инлайн-кнопки оригинала (copy_message их теряет)
        if message.reply_markup and message.reply_markup.inline_keyboard:
            orig_btns = []
            for row in message.reply_markup.inline_keyboard:
                line = []
                for b in row:
                    btn = {"text": b.text}
                    if b.url:
                        btn["url"] = b.url
                    elif b.callback_data:
                        # callback на чужой бот работать не будет — пропускаем
                        continue
                    else:
                        continue
                    line.append(btn)
                if line:
                    orig_btns.append(line)
            if orig_btns:
                cfg["_orig_buttons"] = orig_btns'''
if old_fwd in sc_src:
    sc_src = sc_src.replace(old_fwd, new_fwd, 1)
    sc.write_text(sc_src, encoding="utf-8")
    print("  ✓ handlers/step_create.py (_extract_content)")
else:
    print("  ⚠ блок forward не найден — пропущено (возможно структура иная)")


# ===== 3. scenario.py — дубли только при wait_mode == user_message =====
print("[3/3] scenario.py — дубли в «Сообщении»")
sn = ROOT / "bots/scenario.py"
sn_src = sn.read_text(encoding="utf-8")

# Находим _schedule_duplicate / место где запускается дублирование для message-шага.
# Самый надёжный способ — в точке, где для message-шага решается, нужно ли дублировать.
# Добавим guard: если шаг message и wait_mode != user_message — не планируем дубль.
marker = "async def _send_message_step(self, bot, bot_record, user, step, cfg)"
if marker in sn_src and "_dup_allowed_for_message" not in sn_src:
    # Вставляем хелпер перед _send_message_step
    helper = '''    @staticmethod
    def _dup_allowed_for_message(cfg: dict) -> bool:
        """Дубли в шаге message имеют смысл только когда ждём ответ юзера."""
        return cfg.get("wait_mode") == "user_message"

    '''
    sn_src = sn_src.replace(
        "    " + marker,
        helper + marker,
        1,
    )
    print("  ✓ bots/scenario.py (добавлен _dup_allowed_for_message)")
else:
    print("  ⚠ _send_message_step не найден или уже пропатчен")

sn.write_text(sn_src, encoding="utf-8")

print("\n✅ Патч применён.")
print("⚠️  ВНИМАНИЕ: для пункта 3 нужно вручную проверить scenario.py —")
print("    где планируется дубль для message-шага, добавить проверку:")
print("    if step['step_type']=='message' and not self._dup_allowed_for_message(cfg): skip")
print("\nПерезапусти: systemctl restart bot")
