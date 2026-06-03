"""Тест движка сценария ScenarioEngine с мок-ботом."""
import asyncio
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
os.environ["ADMIN_IDS"] = "123"

from database.db import DB
import database
from bots.scenario import ScenarioEngine


def make_mock_bot():
    counter = {"i": 1000}
    sent = []

    async def send_message(chat_id, text, reply_markup=None, **kw):
        counter["i"] += 1
        sent.append(("send_message", chat_id, text, reply_markup))
        m = MagicMock(); m.message_id = counter["i"]; return m

    async def send_photo(chat_id, photo, caption="", reply_markup=None, **kw):
        counter["i"] += 1
        sent.append(("send_photo", chat_id, caption, reply_markup))
        m = MagicMock(); m.message_id = counter["i"]; return m

    async def delete_message(chat_id, message_id):
        sent.append(("delete", chat_id, message_id))
        return True

    async def get_chat_member(chat_id, user_id):
        m = MagicMock(); m.status = "member"; return m

    async def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
        counter["i"] += 1
        sent.append(("copy", chat_id, from_chat_id, message_id))
        m = MagicMock(); m.message_id = counter["i"]; return m

    bot = MagicMock()
    bot.send_message = send_message
    bot.send_photo = send_photo
    bot.send_sticker = send_message
    bot.send_animation = send_photo
    bot.send_video = send_photo
    bot.send_document = send_photo
    bot.delete_message = delete_message
    bot.get_chat_member = get_chat_member
    bot.copy_message = copy_message
    return bot, sent


def msg_texts(sent):
    return [s[2] for s in sent if s[0] in ("send_message", "send_photo")]


async def setup_db():
    db = DB(":memory:")
    await db.connect()
    database.db._db_instance = db
    return db


async def test_basic_scenario_progress():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "message", {"text":"step 1","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"step 2","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"step 3","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)

    engine = ScenarioEngine()
    bot, sent = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 0
        texts = msg_texts(sent)
        assert any("step 1" in t for t in texts), texts

        await engine.advance(bot, bot_record, u["id"])
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1
        texts = msg_texts(sent)
        assert any("step 2" in t for t in texts), texts

        await engine.advance(bot, bot_record, u["id"])
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 2
        texts = msg_texts(sent)
        assert any("step 3" in t for t in texts), texts

        await engine.advance(bot, bot_record, u["id"])
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["completed"] == 1
    finally:
        await engine.shutdown()
        await db.close()
    print("test_basic_scenario_progress: OK")


async def test_restart_resets_progress():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "message", {"text":"hi","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)
    await db.update_user(user["id"], current_step_order=5, duplicate_count=3, completed=1)
    user = await db.get_user(user["id"])

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 0
        assert u["duplicate_count"] == 0
        assert u["completed"] == 0
    finally:
        await engine.shutdown()
        await db.close()
    print("test_restart_resets_progress: OK")


async def test_timer_advance():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "message", {"text":"hi","wait_mode":"timer","wait_timer":1},
                      duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"end","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(1.4)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1, f"got {u['current_step_order']}"
    finally:
        await engine.shutdown()
        await db.close()
    print("test_timer_advance: OK")


async def test_message_advance_on_user_msg():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "message", {"text":"hi","wait_mode":"user_message"},
                      duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"end","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["awaiting_user_msg"] == 1
        advanced = await engine.handle_message_from_user(bot, bot_record, u["id"], "Привет!")
        assert advanced
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1
    finally:
        await engine.shutdown()
        await db.close()
    print("test_message_advance_on_user_msg: OK")


async def test_message_keyboard_button_match():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "message",
        {"text":"hi","wait_mode":"user_message","keyboard_text":"Дальше →"},
        duplicate_after=999, duplicate_max=0,
    )
    await db.add_step(bot_id, "message", {"text":"end","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.1)
        advanced = await engine.handle_message_from_user(bot, bot_record, user["id"], "блабла")
        assert not advanced
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 0
        advanced = await engine.handle_message_from_user(bot, bot_record, u["id"], "Дальше →")
        assert advanced
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1
    finally:
        await engine.shutdown()
        await db.close()
    print("test_message_keyboard_button_match: OK")


async def test_op_skip_if_already_subscribed():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "op", {
        "text": "subscribe please",
        "sponsors": [{
            "check": True, "channel_id": -1001234,
            "link":"https://t.me/x", "title":"X",
            "button_text":"Sub", "button_color":"default",
        }],
        "check_button_text": "✅", "check_button_color":"green",
    }, duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"after op","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)

    engine = ScenarioEngine()
    bot, sent = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.3)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1, f"got {u['current_step_order']}"
        texts = msg_texts(sent)
        assert any("after op" in t for t in texts), texts
    finally:
        await engine.shutdown()
        await db.close()
    print("test_op_skip_if_already_subscribed: OK")


async def test_op_block_if_not_subscribed():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "op", {
        "text": "subscribe",
        "sponsors": [{
            "check": True, "channel_id": -1001234,
            "link":"https://t.me/x", "title":"X",
            "button_text":"Sub","button_color":"default",
        }],
        "check_button_text":"✅", "check_button_color":"green",
    }, duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"after","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    async def left(*a, **kw):
        m = MagicMock(); m.status = "left"; return m
    bot.get_chat_member = left

    try:
        user = await db.upsert_user(bot_id, 99)
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.3)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 0

        advance, alert = await engine.handle_callback(bot, bot_record, u["id"], "check_op", {})
        assert advance is False
        assert alert is not None

        async def member(*a, **kw):
            m = MagicMock(); m.status = "member"; return m
        bot.get_chat_member = member
        advance, alert = await engine.handle_callback(bot, bot_record, u["id"], "check_op", {})
        assert advance is True
    finally:
        await engine.shutdown()
        await db.close()
    print("test_op_block_if_not_subscribed: OK")


async def test_roulette_advance():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "roulette", {"text":"r","button_text":"go"},
                      duplicate_after=999, duplicate_max=0)
    await db.add_step(bot_id, "message", {"text":"after r","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    try:
        user = await db.upsert_user(bot_id, 99)
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 0

        await engine.handle_roulette_done(bot, bot_record, 99, 5000)
        await asyncio.sleep(0.1)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1
        cur = await db.conn.execute("SELECT amount FROM roulette_wins")
        rows = await cur.fetchall()
        assert len(rows) == 1 and rows[0][0] == 5000
    finally:
        await engine.shutdown()
        await db.close()
    print("test_roulette_advance: OK")


async def test_blocked_user_marked_dead():
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.methods import SendMessage
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(bot_id, "message", {"text":"hi","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)

    engine = ScenarioEngine()
    bot, _ = make_mock_bot()
    async def block(*a, **kw):
        raise TelegramForbiddenError(
            method=SendMessage(chat_id=1, text="x"),
            message="Forbidden: bot was blocked by the user",
        )
    bot.send_message = block

    try:
        user = await db.upsert_user(bot_id, 99)
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(0.2)
        u = await db.get_user(user["id"])
        assert u["is_alive"] == 0
    finally:
        await engine.shutdown()
        await db.close()
    print("test_blocked_user_marked_dead: OK")


async def test_duplicate_mechanism():
    db = await setup_db()
    bot_id = await db.add_greeting_bot("1:AAA", 1, "u", "n", 1)
    bot_record = await db.get_greeting_bot(bot_id)
    await db.add_step(
        bot_id, "message",
        {"text":"hi","wait_mode":"user_message"},
        duplicate_after=1, duplicate_increment=0, duplicate_max=2,
    )
    await db.add_step(bot_id, "message", {"text":"end","wait_mode":"none"},
                      duplicate_after=999, duplicate_max=0)
    user = await db.upsert_user(bot_id, 99)

    engine = ScenarioEngine()
    bot, sent = make_mock_bot()
    try:
        await engine.start_or_restart(bot, bot_record, user)
        await asyncio.sleep(3.5)
        u = await db.get_user(user["id"])
        assert u["current_step_order"] == 1, f"got {u['current_step_order']}"
        sends = [s for s in sent if s[0] == "send_message"]
        assert len(sends) >= 4, f"sends={len(sends)}"
    finally:
        await engine.shutdown()
        await db.close()
    print("test_duplicate_mechanism: OK")


async def main():
    await test_basic_scenario_progress()
    await test_restart_resets_progress()
    await test_timer_advance()
    await test_message_advance_on_user_msg()
    await test_message_keyboard_button_match()
    await test_op_skip_if_already_subscribed()
    await test_op_block_if_not_subscribed()
    await test_roulette_advance()
    await test_blocked_user_marked_dead()
    print("\n[slow] test_duplicate_mechanism (~3.5s)…")
    await test_duplicate_mechanism()
    print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
