#!/usr/bin/env python3
"""
Патч 25: инвайт-ссылки канала создаются с creates_join_request=True.

Было: createChatInviteLink делал обычную ссылку — по ней вступают
сразу, без заявки. Приветка не ловит chat_join_request → сценарий
не запускается, ссылка бесполезна.

Стало: ссылка «по заявкам» — переход = подача заявки, приветка
получает апдейт и пишет юзеру.
"""
from pathlib import Path

ROOT = Path("/opt/bot")  # для друга — /opt/friend_bot
CL = ROOT / "handlers/channel_links.py"

src = CL.read_text(encoding="utf-8")

old = '''        invite = await greeter.create_chat_invite_link(
            chat_id=channel_id, name=name[:32],
        )'''

new = '''        invite = await greeter.create_chat_invite_link(
            chat_id=channel_id, name=name[:32],
            creates_join_request=True,
        )'''

if old not in src:
    # запасной вариант — однострочная запись
    old2 = 'invite = await greeter.create_chat_invite_link(chat_id=channel_id, name=name[:32])'
    new2 = ('invite = await greeter.create_chat_invite_link('
            'chat_id=channel_id, name=name[:32], creates_join_request=True)')
    if old2 in src:
        src = src.replace(old2, new2, 1)
    else:
        raise SystemExit(
            "create_chat_invite_link не найден в channel_links.py — "
            "покажи `grep -n create_chat_invite_link /opt/bot/handlers/channel_links.py`"
        )
else:
    src = src.replace(old, new, 1)

CL.write_text(src, encoding="utf-8")
print("  ✓ handlers/channel_links.py — ссылки канала создаются «по заявкам»")
print("\n✅ Патч 25 применён. Перезапусти: systemctl restart bot")
print("\n⚠️  Ссылки, созданные ДО патча — остаются обычными. Создай новые,")
print("   чтобы они работали с приветкой.")
