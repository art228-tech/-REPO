"""Задачи и посты — управление."""
from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import get_db
from handlers.common import is_admin
from keyboards.kb import tasks_menu, task_card, post_card
from states.fsm import TaskStates
from utils.helpers import post_summary

router = Router()


# ===== Список задач =====
@router.callback_query(F.data == "tasks")
async def cb_tasks(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("⛔", show_alert=True)
        return
    await state.clear()
    tasks = await get_db().list_tasks()
    await cb.message.edit_text(
        f"<b>📋 Задачи</b>\n\nВсего: {len(tasks)}",
        reply_markup=tasks_menu(tasks),
    )
    await cb.answer()


# ===== Создание задачи =====
@router.callback_query(F.data == "task_add")
async def cb_task_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(TaskStates.wait_name)
    await cb.message.edit_text("Пришли <b>название</b> новой задачи:")
    await cb.answer()


@router.message(TaskStates.wait_name)
async def m_task_name(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id) or not message.text:
        return
    task_id = await get_db().add_task(message.text.strip()[:64])
    await state.clear()
    tasks = await get_db().list_tasks()
    await message.answer(
        f"✅ Задача создана. Открой её и добавь посты.",
        reply_markup=tasks_menu(tasks),
    )


# ===== Карточка задачи =====
@router.callback_query(F.data.startswith("task:"))
async def cb_task_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    task_id = int(cb.data.split(":")[1])
    db = get_db()
    task = await db.get_task(task_id)
    if not task:
        await cb.answer("Не найдено", show_alert=True)
        return
    posts = await db.list_posts(task_id)
    await cb.message.edit_text(
        f"<b>📋 {task['name']}</b>\n\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )
    await cb.answer()


# ===== Переименование =====
@router.callback_query(F.data.startswith("task_ren:"))
async def cb_task_rename(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    task_id = int(cb.data.split(":")[1])
    await state.set_state(TaskStates.wait_rename)
    await state.update_data(task_id=task_id)
    await cb.message.edit_text("Пришли <b>новое название</b> задачи:")
    await cb.answer()


@router.message(TaskStates.wait_rename)
async def m_task_rename(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id) or not message.text:
        return
    data = await state.get_data()
    task_id = data["task_id"]
    await get_db().rename_task(task_id, message.text.strip()[:64])
    await state.clear()
    db = get_db()
    task = await db.get_task(task_id)
    posts = await db.list_posts(task_id)
    await message.answer(
        f"✅ Переименовано.\n\n<b>📋 {task['name']}</b>\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )


# ===== Удаление задачи =====
@router.callback_query(F.data.startswith("task_del:"))
async def cb_task_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    task_id = int(cb.data.split(":")[1])
    await get_db().delete_task(task_id)
    tasks = await get_db().list_tasks()
    await cb.message.edit_text("🗑 Задача удалена.", reply_markup=tasks_menu(tasks))
    await cb.answer()


# ===== Карточка поста =====
@router.callback_query(F.data.startswith("post:"))
async def cb_post_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    if not post:
        await cb.answer("Не найдено", show_alert=True)
        return
    posts = await db.list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    await cb.message.edit_text(
        post_summary(post, idx + 1),
        reply_markup=post_card(post_id, post["task_id"], idx, len(posts)),
    )
    await cb.answer()


# ===== Перемещение постов =====
@router.callback_query(F.data.startswith("post_up:"))
async def cb_post_up(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    posts = await db.list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    if idx > 0:
        await db.swap_post_positions(post_id, posts[idx - 1]["id"])
    await _reopen_task(cb, post["task_id"])


@router.callback_query(F.data.startswith("post_down:"))
async def cb_post_down(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    posts = await db.list_posts(post["task_id"])
    idx = next((i for i, p in enumerate(posts) if p["id"] == post_id), 0)
    if idx < len(posts) - 1:
        await db.swap_post_positions(post_id, posts[idx + 1]["id"])
    await _reopen_task(cb, post["task_id"])


@router.callback_query(F.data.startswith("post_del:"))
async def cb_post_del(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    post_id = int(cb.data.split(":")[1])
    db = get_db()
    post = await db.get_post(post_id)
    task_id = post["task_id"]
    await db.delete_post(post_id)
    await _reopen_task(cb, task_id)


async def _reopen_task(cb: CallbackQuery, task_id: int) -> None:
    db = get_db()
    task = await db.get_task(task_id)
    posts = await db.list_posts(task_id)
    await cb.message.edit_text(
        f"<b>📋 {task['name']}</b>\n\nПостов: {len(posts)}",
        reply_markup=task_card(task_id, posts),
    )
    await cb.answer()
