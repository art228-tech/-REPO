"""Тесты БД и проверки логики."""
import asyncio
import json
import sys
import tempfile
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Стабы для конфига чтобы импорт не валился
os.environ["BOT_TOKEN"] = "1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
os.environ["ADMIN_IDS"] = "123"
os.environ["DB_PATH"] = ":memory:"

from database.db import DB
from utils.helpers import (
    build_inline_keyboard, color_button_text, parse_token, COLOR_PREFIXES,
)
from webapp.server import _verify_init_data


async def test_db_full():
    db = DB(":memory:")
    await db.connect()

    # 1) добавление приветки
    bot_id = await db.add_greeting_bot("1:AAA", 42, "testbot", "Test", 999)
    assert bot_id == 1
    b = await db.get_greeting_bot(1)
    assert b["username"] == "testbot"
    assert b["delete_timer"] == 10
    assert b["join_delay"] == 0

    # 2) update settings
    await db.update_greeting_bot_settings(1, join_delay=5, delete_timer=20)
    b = await db.get_greeting_bot(1)
    assert b["join_delay"] == 5 and b["delete_timer"] == 20

    # 3) добавление шагов
    s1 = await db.add_step(1, "roulette", {"text":"hi","button_text":"go"})
    s2 = await db.add_step(1, "op", {"text":"op", "sponsors":[]})
    s3 = await db.add_step(1, "message", {"text":"msg"})
    steps = await db.list_steps(1)
    assert [s["step_order"] for s in steps] == [0,1,2]
    assert steps[0]["step_type"] == "roulette"

    # 4) move step (поднимем 3-й вверх)
    await db.move_step(s3, -1)  # был на 2, стал на 1
    steps = await db.list_steps(1)
    types_order = [s["step_type"] for s in steps]
    assert types_order == ["roulette", "message", "op"], types_order

    # 5) delete step (удалим первый — порядки сдвинутся)
    await db.delete_step(s1)
    steps = await db.list_steps(1)
    assert [s["step_order"] for s in steps] == [0,1]
    assert [s["step_type"] for s in steps] == ["message", "op"]

    # 6) пользователи
    u = await db.upsert_user(1, 100500, username="alice", first_name="Alice", is_premium=True)
    assert u["is_premium"] == 1
    assert u["is_alive"] == 1
    # повторный upsert не должен создавать дубль
    u2 = await db.upsert_user(1, 100500, username="alice2", first_name="Al", is_premium=False)
    assert u2["id"] == u["id"]
    assert u2["username"] == "alice2"
    users = await db.list_users(1)
    assert len(users) == 1

    # 7) Mark dead и list_alive
    await db.mark_user_dead(u["id"])
    assert len(await db.list_alive_user_tg_ids(1)) == 0
    # снова upsert — оживёт
    await db.upsert_user(1, 100500, username="alice", first_name="Alice", is_premium=True)
    assert len(await db.list_alive_user_tg_ids(1)) == 1

    # 8) реф-ссылки
    r = await db.add_ref_link(1, "Тест-ссылка")
    assert r["code"] and r["name"] == "Тест-ссылка"
    r2 = await db.get_ref_link_by_code(1, r["code"])
    assert r2["id"] == r["id"]
    assert len(await db.list_ref_links(1)) == 1

    # 9) reset_user_progress
    await db.update_user(u["id"], current_step_order=5, completed=1, duplicate_count=3)
    await db.reset_user_progress(u["id"])
    user = await db.get_user(u["id"])
    assert user["current_step_order"] == 0
    assert user["completed"] == 0
    assert user["duplicate_count"] == 0

    # 10) step completion
    cur_steps = await db.list_steps(1)
    await db.record_step_completion(u["id"], cur_steps[0]["id"])
    assert await db.has_completed_step(u["id"], cur_steps[0]["id"]) is True

    # 11) admin state
    await db.set_admin_state(999, "AddBotStates:token", {"x": 1})
    state, data = await db.get_admin_state(999)
    assert state == "AddBotStates:token"
    assert data == {"x": 1}
    await db.set_admin_state(999, None)
    state, data = await db.get_admin_state(999)
    assert state is None and data == {}

    # 12) delete bot — cascade
    await db.delete_greeting_bot(1)
    assert len(await db.list_steps(1)) == 0
    assert len(await db.list_users(1)) == 0
    assert len(await db.list_ref_links(1)) == 0

    await db.close()
    print("test_db_full: OK")


def test_helpers():
    # цвет кнопки
    s = color_button_text("Привет", "green")
    assert s == "🟢 Привет", s
    s = color_button_text("X", "default")
    assert s == "X", s

    # клавиатура с разными типами
    kb = build_inline_keyboard([
        [{"text":"A","url":"https://x.com"}],
        [{"text":"B","callback_data":"b","color":"red"}],
    ])
    assert kb is not None
    assert len(kb.inline_keyboard) == 2
    # Цвет — нативный (поле style), текст без эмодзи-префиксов.
    _b = kb.inline_keyboard[1][0]
    assert _b.text == "B", _b.text
    assert _b.model_dump(exclude_none=True).get("style") == "danger"

    # пустая
    assert build_inline_keyboard([]) is None
    assert build_inline_keyboard([[{"text":"x"}]]) is None  # ни url ни cb

    # parse_token
    t = parse_token("Вот мой токен 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefghi жэжэ")
    assert t == "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZabcdefghi", t
    assert parse_token("чёт левое") is None

    print("test_helpers: OK")


def test_init_data_verify():
    # Берём тестовый bot_token и валидный пример с офиц. документации
    import hashlib, hmac
    from urllib.parse import urlencode
    token = "12345:ABCD"
    data = {
        "auth_date": "1700000000",
        "query_id": "abc",
        "user": '{"id":123,"first_name":"X"}',
    }
    items = sorted(data.items())
    data_check_string = "\n".join(f"{k}={v}" for k,v in items)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    hash_val = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    init_data = urlencode(data) + "&hash=" + hash_val
    ok, parsed = _verify_init_data(init_data, token)
    assert ok, "verify должен пройти"
    assert parsed["user"]["id"] == 123

    # Подделка
    ok, _ = _verify_init_data(init_data + "x", token)
    assert not ok
    ok, _ = _verify_init_data(init_data, "WRONG_TOKEN")
    assert not ok
    print("test_init_data_verify: OK")


async def main():
    await test_db_full()
    test_helpers()
    test_init_data_verify()
    print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
