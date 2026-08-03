from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import accounts
import config
from db import db
from keyboards import (
    account_actions_kb,
    accounts_kb,
    base_kb,
    cancel_kb,
    confirm_kb,
    export_kb,
    main_menu,
    messages_kb,
    settings_kb,
    variants_kb,
)
from logger_setup import log
from mailing import resume_after_spamblock_check, worker
from states import AddAccountSG, BaseSG, MessagesSG, SetProxySG, SettingsSG

router = Router()

# Live stats message editing
_stats_lock = asyncio.Lock()


async def ensure_owner(message: Message) -> bool:
    owners = await db.get_owner_ids()
    if not owners:
        await db.add_owner(message.from_user.id)
        log.info("First owner registered: %s", message.from_user.id)
        return True
    if message.from_user.id not in owners:
        await message.answer("Нет доступа. Бот привязан к другому владельцу.")
        return False
    return True


async def ensure_owner_cb(callback: CallbackQuery) -> bool:
    owners = await db.get_owner_ids()
    if not owners:
        await db.add_owner(callback.from_user.id)
        return True
    if callback.from_user.id not in owners:
        await callback.answer("Нет доступа", show_alert=True)
        return False
    return True


def parse_contacts_file(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # csv-ish: take first column
        if "," in line:
            line = line.split(",", 1)[0].strip()
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        if "\t" in line:
            line = line.split("\t", 1)[0].strip()
        line = line.strip().strip('"').strip("'")
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(line)
    return result


async def push_stats_to_chat(bot: Bot, chat_id: int, text: str) -> None:
    async with _stats_lock:
        run = await db.get_run()
        msg_id = run["stats_message_id"]
        try:
            if msg_id:
                await bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=msg_id,
                )
                return
        except Exception:
            pass
        sent = await bot.send_message(chat_id, text)
        await db.set_run(stats_message_id=sent.message_id, chat_id=chat_id)


# -------------------- start / menu --------------------


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    await state.clear()
    await message.answer(
        "Привет. Это панель рассылки по родственникам.\n"
        "1) Настройки → API_ID/API_HASH (my.telegram.org)\n"
        "2) Добавь аккаунты (+ прокси при необходимости)\n"
        "3) Загрузи базу (txt)\n"
        "4) Добавь варианты Msg1 / Msg2\n"
        "5) Выставь интервалы и жми Старт\n\n"
        "При PeerFlood (спамблок) аккаунт отключается, остальные продолжают.\n"
        "Стоп → сними SB через @SpamBot → Старт (флаги SB перепроверяются).",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
@router.callback_query(F.data == "cancel")
async def cancel_any(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(event, CallbackQuery):
        if not await ensure_owner_cb(event):
            return
        await accounts.cancel_login(event.from_user.id)
        await event.message.answer("Отменено.", reply_markup=main_menu())
        await event.answer()
    else:
        if not await ensure_owner(event):
            return
        await accounts.cancel_login(event.from_user.id)
        await event.answer("Отменено.", reply_markup=main_menu())


# -------------------- accounts --------------------


@router.message(F.text == "👤 Аккаунты")
async def accounts_menu(message: Message) -> None:
    if not await ensure_owner(message):
        return
    accs = await db.list_accounts()
    await message.answer(
        f"Аккаунты: {len(accs)}",
        reply_markup=accounts_kb(accs),
    )


@router.callback_query(F.data == "acc:list")
async def acc_list_cb(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    accs = await db.list_accounts()
    await callback.message.edit_text(
        f"Аккаунты: {len(accs)}",
        reply_markup=accounts_kb(accs),
    )
    await callback.answer()


@router.callback_query(F.data == "acc:add")
async def acc_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    api_id, api_hash = await db.get_api_credentials()
    if not api_id or not api_hash:
        await callback.answer("Сначала укажи API_ID/API_HASH в настройках", show_alert=True)
        return
    await state.set_state(AddAccountSG.proxy)
    await callback.message.answer(
        "Прокси для этого аккаунта (или «-» без прокси).\n"
        "Форматы:\n"
        "<code>socks5://user:pass@host:port</code>\n"
        "<code>host:port:user:pass</code>\n"
        "<code>host:port</code>",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AddAccountSG.proxy)
async def acc_proxy_step(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    raw = (message.text or "").strip()
    if raw in ("-", "нет", "no", "none"):
        await state.update_data(proxy=None)
    else:
        try:
            from db import ProxyConfig

            ProxyConfig.parse(raw)  # validate
            await state.update_data(proxy=raw)
        except Exception as e:
            await message.answer(f"Неверный прокси: {e}\nПопробуй ещё раз или «-»")
            return
    await state.set_state(AddAccountSG.phone)
    await message.answer("Номер телефона аккаунта в международном формате, например +79001234567:")


@router.message(AddAccountSG.phone)
async def acc_phone_step(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    phone = (message.text or "").strip()
    data = await state.get_data()
    try:
        await message.answer("Отправляю код в Telegram…")
        phone = await accounts.start_login(
            message.from_user.id, phone, data.get("proxy")
        )
        await state.update_data(phone=phone)
        await state.set_state(AddAccountSG.code)
        await message.answer(
            f"Код отправлен на {phone}.\n"
            "Пришли код сюда (цифры из Telegram / SMS)."
        )
    except Exception as e:
        log.exception("start_login failed")
        await state.clear()
        await message.answer(f"Ошибка входа: {e}", reply_markup=main_menu())


@router.message(AddAccountSG.code)
async def acc_code_step(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    code = (message.text or "").strip()
    try:
        result = await accounts.complete_login_code(message.from_user.id, code)
        if result.get("need_2fa"):
            await state.set_state(AddAccountSG.password)
            await message.answer("Нужен облачный пароль 2FA. Пришли пароль:")
            return
        await state.clear()
        await message.answer(
            f"✅ Аккаунт добавлен: {result['phone']}\n"
            f"TG: {result.get('name')} @{result.get('username') or '—'}",
            reply_markup=main_menu(),
        )
    except Exception as e:
        log.exception("complete_login_code failed")
        await message.answer(f"Ошибка кода: {e}\nМожно /cancel и начать заново.")


@router.message(AddAccountSG.password)
async def acc_2fa_step(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    password = message.text or ""
    try:
        result = await accounts.complete_login_2fa(message.from_user.id, password)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт добавлен: {result['phone']}",
            reply_markup=main_menu(),
        )
    except Exception as e:
        log.exception("2fa failed")
        await message.answer(f"Ошибка 2FA: {e}")


@router.callback_query(F.data.startswith("acc:view:"))
async def acc_view(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    account_id = int(callback.data.split(":")[-1])
    acc = await db.get_account(account_id)
    if not acc:
        await callback.answer("Не найден", show_alert=True)
        return
    proxy = acc["proxy_json"] or "нет"
    text = (
        f"<b>Аккаунт #{acc['id']}</b>\n"
        f"Телефон: <code>{acc['phone']}</code>\n"
        f"Статус: <b>{acc['status']}</b>\n"
        f"Прокси: <code>{proxy[:200]}</code>\n"
        f"Ошибка: {acc['last_error'] or '—'}\n"
        f"SB at: {acc['spamblocked_at'] or '—'}"
    )
    await callback.message.edit_text(text, reply_markup=account_actions_kb(account_id))
    await callback.answer()


@router.callback_query(F.data.startswith("acc:proxy:"))
async def acc_proxy_set(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    account_id = int(callback.data.split(":")[-1])
    await state.set_state(SetProxySG.value)
    await state.update_data(account_id=account_id)
    await callback.message.answer(
        "Пришли новый прокси или «-» чтобы удалить:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SetProxySG.value)
async def acc_proxy_save(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    data = await state.get_data()
    account_id = int(data["account_id"])
    raw = (message.text or "").strip()
    try:
        await accounts.set_account_proxy(account_id, raw)
        await state.clear()
        await message.answer("Прокси обновлён.", reply_markup=main_menu())
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("acc:unsb:"))
async def acc_unsb(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    account_id = int(callback.data.split(":")[-1])
    await accounts.clear_spamblock_flag(account_id)
    await callback.answer("Флаг SB снят, статус active")
    acc = await db.get_account(account_id)
    await callback.message.edit_text(
        f"#{account_id} {acc['phone']} → active",
        reply_markup=account_actions_kb(account_id),
    )


@router.callback_query(F.data.startswith("acc:check:"))
async def acc_check(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    account_id = int(callback.data.split(":")[-1])
    await callback.answer("Проверяю…")
    ok, info = await accounts.check_account_alive(account_id)
    await callback.message.answer(
        f"{'✅' if ok else '❌'} Аккаунт #{account_id}: {info}"
    )


@router.callback_query(F.data.startswith("acc:del:"))
async def acc_del(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    account_id = int(callback.data.split(":")[-1])
    await accounts.remove_account(account_id)
    accs = await db.list_accounts()
    await callback.message.edit_text(
        f"Удалён. Осталось: {len(accs)}",
        reply_markup=accounts_kb(accs),
    )
    await callback.answer("Удалён")


# -------------------- base --------------------


@router.message(F.text == "📇 База")
async def base_menu(message: Message) -> None:
    if not await ensure_owner(message):
        return
    stats = await db.contact_stats()
    await message.answer(
        "База родственников\n"
        f"Всего: {stats['total']} | pending: {stats['pending']} | "
        f"sent: {stats['sent']} | failed: {stats['failed']}\n\n"
        "Формат файла: один контакт на строку — номер, @username или id.",
        reply_markup=base_kb(),
    )


@router.callback_query(F.data.startswith("base:upload:"))
async def base_upload(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    mode = callback.data.split(":")[-1]
    await state.set_state(BaseSG.upload)
    await state.update_data(replace=(mode == "replace"))
    await callback.message.answer(
        "Пришли .txt файл или текст со списком контактов.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(BaseSG.upload, F.document)
async def base_upload_doc(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await ensure_owner(message):
        return
    data = await state.get_data()
    file = await bot.get_file(message.document.file_id)
    buf = await bot.download_file(file.file_path)
    text = buf.read().decode("utf-8", errors="ignore")
    contacts = parse_contacts_file(text)
    result = await db.import_contacts(contacts, replace=bool(data.get("replace")))
    await state.clear()
    await message.answer(
        f"Импорт готов. Добавлено: {result['added']}, "
        f"пропущено(дубли): {result['skipped']}, всего: {result['total']}",
        reply_markup=main_menu(),
    )


@router.message(BaseSG.upload, F.text)
async def base_upload_text(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    data = await state.get_data()
    contacts = parse_contacts_file(message.text or "")
    if not contacts:
        await message.answer("Пусто. Пришли список или файл.")
        return
    result = await db.import_contacts(contacts, replace=bool(data.get("replace")))
    await state.clear()
    await message.answer(
        f"Импорт готов. Добавлено: {result['added']}, "
        f"пропущено: {result['skipped']}, всего: {result['total']}",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "base:clear")
async def base_clear(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    await callback.message.answer(
        "Точно очистить всю базу контактов?",
        reply_markup=confirm_kb("clear_base"),
    )
    await callback.answer()


@router.callback_query(F.data == "confirm:clear_base:yes")
async def base_clear_yes(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    await db.clear_contacts()
    await callback.message.answer("База очищена.", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "confirm:clear_base:no")
async def base_clear_no(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    await callback.message.answer("Ок, база не тронута.")


@router.callback_query(F.data == "base:stats")
async def base_stats(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    stats = await db.contact_stats()
    await callback.message.answer(
        "\n".join(f"{k}: {v}" for k, v in stats.items())
    )
    await callback.answer()


# -------------------- messages --------------------


@router.message(F.text == "✉️ Сообщения")
async def msg_menu(message: Message) -> None:
    if not await ensure_owner(message):
        return
    v1 = await db.list_variants(1)
    v2 = await db.list_variants(2)
    await message.answer(
        f"Варианты Msg1: {len(v1)}\nВарианты Msg2: {len(v2)}\n"
        "При отправке выбирается случайный вариант слота.",
        reply_markup=messages_kb(),
    )


@router.callback_query(F.data == "msg:menu")
async def msg_menu_cb(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    await callback.message.edit_text("Сообщения", reply_markup=messages_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("msg:list:"))
async def msg_list(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    slot = int(callback.data.split(":")[-1])
    variants = await db.list_variants(slot)
    if not variants:
        text = f"Msg{slot}: пусто"
    else:
        text = f"Msg{slot} варианты:\n" + "\n".join(
            f"#{v['id']}: {v['text']}" for v in variants
        )
    await callback.message.edit_text(text[:4000], reply_markup=variants_kb(slot, variants))
    await callback.answer()


@router.callback_query(F.data.startswith("msg:add:"))
async def msg_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    slot = int(callback.data.split(":")[-1])
    await state.set_state(MessagesSG.add_text)
    await state.update_data(slot=slot)
    await callback.message.answer(
        f"Пришли текст варианта для Msg{slot}:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(MessagesSG.add_text)
async def msg_add_save(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    data = await state.get_data()
    slot = int(data["slot"])
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пусто.")
        return
    vid = await db.add_variant(slot, text)
    await state.clear()
    await message.answer(f"Добавлен вариант #{vid} в Msg{slot}", reply_markup=main_menu())


@router.callback_query(F.data.startswith("msg:del:"))
async def msg_del(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    _, _, vid, slot = callback.data.split(":")
    await db.delete_variant(int(vid))
    variants = await db.list_variants(int(slot))
    await callback.message.edit_text(
        f"Msg{slot} после удаления:",
        reply_markup=variants_kb(int(slot), variants),
    )
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("msg:clear:"))
async def msg_clear(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    slot = int(callback.data.split(":")[-1])
    await db.clear_variants(slot)
    await callback.answer(f"Msg{slot} очищен")
    await callback.message.answer(f"Все варианты Msg{slot} удалены.")


# -------------------- settings --------------------


@router.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message) -> None:
    if not await ensure_owner(message):
        return
    api_id, api_hash = await db.get_api_credentials()
    between, per_acc = await db.get_delays()
    hash_mask = (api_hash[:4] + "…" + api_hash[-4:]) if len(api_hash) > 8 else ("задан" if api_hash else "нет")
    await message.answer(
        f"API_ID: {api_id or 'нет'}\n"
        f"API_HASH: {hash_mask}\n"
        f"Пауза msg1→msg2: {between}с\n"
        f"Интервал на 1 аккаунт: {per_acc}с",
        reply_markup=settings_kb(),
    )


@router.callback_query(F.data == "set:api")
async def set_api(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    await state.set_state(SettingsSG.api_id)
    await callback.message.answer(
        "Пришли API_ID (число с my.telegram.org):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsSG.api_id)
async def set_api_id(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужно число.")
        return
    await state.update_data(api_id=raw)
    await state.set_state(SettingsSG.api_hash)
    await message.answer("Теперь API_HASH:")


@router.message(SettingsSG.api_hash)
async def set_api_hash(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    data = await state.get_data()
    api_hash = (message.text or "").strip()
    await db.set_setting("api_id", data["api_id"])
    await db.set_setting("api_hash", api_hash)
    await state.clear()
    await message.answer("API сохранены.", reply_markup=main_menu())


@router.callback_query(F.data == "set:delay_msg")
async def set_delay_msg(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    await state.set_state(SettingsSG.delay_msg)
    await callback.message.answer("Секунды между Msg1 и Msg2:")
    await callback.answer()


@router.message(SettingsSG.delay_msg)
async def save_delay_msg(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Число секунд.")
        return
    await db.set_setting("delay_between_messages", raw)
    await state.clear()
    await message.answer(f"Пауза msg1→msg2 = {raw}с", reply_markup=main_menu())


@router.callback_query(F.data == "set:delay_acc")
async def set_delay_acc(callback: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_owner_cb(callback):
        return
    await state.set_state(SettingsSG.delay_acc)
    await callback.message.answer(
        "Интервал в секундах между отправками с ОДНОГО аккаунта "
        "(например 60 = раз в минуту с этого номера):"
    )
    await callback.answer()


@router.message(SettingsSG.delay_acc)
async def save_delay_acc(message: Message, state: FSMContext) -> None:
    if not await ensure_owner(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Число ≥ 1.")
        return
    await db.set_setting("delay_per_account", raw)
    await state.clear()
    await message.answer(f"Интервал на аккаунт = {raw}с", reply_markup=main_menu())


# -------------------- start/stop/stats --------------------


@router.message(F.text == "▶️ Старт")
async def start_mailing(message: Message, bot: Bot) -> None:
    if not await ensure_owner(message):
        return
    if worker.running:
        await message.answer("Уже запущено. Смотри статистику.")
        return

    async def stats_cb(text: str) -> None:
        await push_stats_to_chat(bot, message.chat.id, text)

    try:
        # Reset stats message so a fresh one is created
        await db.set_run(stats_message_id=0)
        note = await resume_after_spamblock_check(message.chat.id, stats_cb)
        await message.answer(
            "Рассылка запущена.\n"
            "При SB аккаунт отключается, остальные продолжают.\n"
            f"{note}",
            reply_markup=main_menu(),
        )
        await push_stats_to_chat(bot, message.chat.id, await worker.build_stats_text())
    except Exception as e:
        log.exception("start failed")
        await message.answer(f"Не удалось стартовать: {e}", reply_markup=main_menu())


@router.message(F.text == "⏹ Стоп")
async def stop_mailing(message: Message, bot: Bot) -> None:
    if not await ensure_owner(message):
        return
    if not worker.running:
        await db.set_run(status="stopped", stopped=True, last_error="stopped_by_user")
        await message.answer("Рассылка не была активна. Статус = stopped.", reply_markup=main_menu())
        return
    await worker.stop("stopped_by_user")
    await message.answer(
        "Остановлено. База и прогресс сохранены (sent/pending не сбрасываются).",
        reply_markup=main_menu(),
    )
    await push_stats_to_chat(bot, message.chat.id, await worker.build_stats_text())


@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message, bot: Bot) -> None:
    if not await ensure_owner(message):
        return
    text = await worker.build_stats_text()
    await push_stats_to_chat(bot, message.chat.id, text)


# -------------------- export --------------------


@router.message(F.text == "📤 Выгрузка")
async def export_menu(message: Message) -> None:
    if not await ensure_owner(message):
        return
    await message.answer("Что выгрузить?", reply_markup=export_kb())


@router.callback_query(F.data.startswith("export:"))
async def export_do(callback: CallbackQuery) -> None:
    if not await ensure_owner_cb(callback):
        return
    kind = callback.data.split(":")[-1]
    if kind == "all":
        lines = []
        for status in ("pending", "sent", "failed", "processing", "skipped"):
            items = await db.export_contacts(status)
            for i in items:
                lines.append(f"{i}\t{status}")
        content = "\n".join(lines) + ("\n" if lines else "")
        name = "contacts_all.txt"
    else:
        items = await db.export_contacts(kind)
        content = "\n".join(items) + ("\n" if items else "")
        name = f"contacts_{kind}.txt"

    path = config.EXPORTS_DIR / name
    path.write_text(content, encoding="utf-8")
    await callback.message.answer_document(
        BufferedInputFile(content.encode("utf-8"), filename=name),
        caption=f"{name}: {content.count(chr(10))} строк",
    )
    await callback.answer()


# -------------------- logs --------------------


@router.message(F.text == "🧾 Логи")
async def send_logs(message: Message) -> None:
    if not await ensure_owner(message):
        return
    log_path = config.LOGS_DIR / "mailer.log"
    err_path = config.LOGS_DIR / "errors.log"
    if log_path.exists():
        data = log_path.read_bytes()[-100_000:]
        await message.answer_document(
            BufferedInputFile(data, filename="mailer.log"),
            caption="Последние ~100KB mailer.log",
        )
    else:
        await message.answer("mailer.log пока нет")
    if err_path.exists() and err_path.stat().st_size > 0:
        data = err_path.read_bytes()[-50_000:]
        await message.answer_document(
            BufferedInputFile(data, filename="errors.log"),
            caption="errors.log",
        )


@router.message(Command("owners"))
async def add_owner_cmd(message: Message) -> None:
    if not await ensure_owner(message):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        owners = await db.get_owner_ids()
        await message.answer(f"Владельцы: {owners}\nДобавить: /owners <telegram_id>")
        return
    await db.add_owner(int(parts[1]))
    await message.answer("Добавлен.")


async def on_startup(bot: Bot) -> None:
    await db.connect()
    # Recover interrupted run state
    requeued = await db.requeue_processing()
    run = await db.get_run()
    if run["status"] == "running":
        await db.set_run(
            status="stopped",
            stopped=True,
            last_error="process_restarted",
        )
    log.info("Bot startup complete, requeued processing=%s", requeued)
    me = await bot.get_me()
    log.info("Bot @%s started", me.username)


async def on_shutdown(bot: Bot) -> None:
    if worker.running:
        await worker.stop("shutdown")
    await accounts.disconnect_all()
    await db.close()
    log.info("Shutdown complete")


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    return dp