# ТЗ: Telegram-бот «Конструктор приветок» (aiogram 3.x, Python 3.10+)

## ЦЕЛЬ

Написать продакшен-готовый бот-конструктор, который позволяет администратору создавать и управлять
ботами-приветками. Приветка — это отдельный Telegram-бот, который реагирует на **chat_join_request**
в каналах и проводит юзера по сценарию (рулетка / обязательная подписка / сообщения).

Один процесс конструктора управляет ВСЕМИ приветками: каждая приветка живёт отдельным Bot+Dispatcher
с polling в том же процессе (паттерн «менеджер ботов»).

## АРХИТЕКТУРА

```
/opt/bot/
├── main.py                          # точка входа
├── config.py                        # .env: BOT_TOKEN (конструктора), ADMIN_IDS, DB_PATH
├── requirements.txt                 # aiogram>=3.7,<4.0, aiosqlite, python-dotenv
├── database/
│   ├── __init__.py                  # реэкспорт get_db, init_db, now
│   └── db.py                        # вся БД (см. ниже)
├── bots/
│   ├── manager.py                   # BotManager — держит polling всех приветок
│   ├── greeter.py                   # хендлеры приветки: chat_join_request, /start, проверки
│   └── scenario.py                  # движок сценария (отправка шагов, дубли, advance, ...)
├── handlers/                        # хендлеры КОНСТРУКТОРА (а не приветок)
│   ├── __init__.py                  # register_all(dp)
│   ├── start.py                     # /start, главное меню
│   ├── add_bot.py                   # добавление приветки по токену
│   ├── bot_menu.py                  # карточка приветки, настройки
│   ├── scenario_edit.py             # список/переупорядочивание/удаление шагов
│   ├── step_create.py               # создание шагов всех 3 типов (большой файл, 1000+ строк)
│   ├── sponsor_edit.py              # редактирование спонсоров в ОП-шаге (патч 6)
│   ├── stats.py                     # статистика
│   ├── refs.py                      # реф-ссылки
│   ├── broadcast.py                 # рассылка
│   ├── channel_links.py             # инвайт-ссылки канала со статистикой (патч 17-18, 25)
│   └── welcome_channels.py          # каналы приветки + задержка per-канал (патч 27)
├── keyboards/
│   ├── __init__.py
│   └── constructor_kb.py            # все клавиатуры конструктора
├── states/
│   ├── __init__.py
│   └── fsm.py                       # все StatesGroup
└── utils/
    ├── __init__.py
    ├── helpers.py                   # send_step_message, build_inline_buttons и пр.
    ├── checker.py                   # check_subscription (members + pending_join_requests)
    └── sponsor_monitor.py           # фоновый воркер проверки спонсорских каналов
```

## БД (SQLite, aiosqlite, WAL)

Все таблицы создавать через `CREATE TABLE IF NOT EXISTS`, миграции через `ALTER TABLE` по
проверке наличия колонки. Не использовать ORM.

```sql
-- Боты-приветки, которые добавил админ
CREATE TABLE greeting_bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    tg_id INTEGER NOT NULL,
    username TEXT,
    name TEXT,
    owner_id INTEGER NOT NULL,
    join_delay INTEGER NOT NULL DEFAULT 0,    -- сек, общая (используется если нет welcome_channels)
    delete_timer INTEGER NOT NULL DEFAULT 10, -- сек, удаление предыдущего шага
    typing_mode INTEGER NOT NULL DEFAULT 0,   -- 0=обычная, 1=имитация печати 5-8 сек
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

-- Шаги сценария
CREATE TABLE steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,                  -- FK greeting_bots
    step_order INTEGER NOT NULL,              -- 0,1,2,...
    step_type TEXT NOT NULL,                  -- 'roulette' | 'op' | 'message'
    config TEXT NOT NULL,                     -- JSON: см. ниже структура для каждого типа
    duplicate_after INTEGER NOT NULL DEFAULT 60,    -- сек, первый дубль
    duplicate_increment INTEGER NOT NULL DEFAULT 0, -- прибавка к каждому след дублю
    duplicate_max INTEGER NOT NULL DEFAULT 3,       -- максимум дублей
    copy_broken INTEGER NOT NULL DEFAULT 0,   -- 1 = оригинал копии мёртв (патч 26)
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Юзеры приветок
CREATE TABLE bot_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    tg_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    is_premium INTEGER NOT NULL DEFAULT 0,
    current_step_order INTEGER NOT NULL DEFAULT 0,
    last_message_id INTEGER,
    last_message_chat_id INTEGER,
    awaiting_user_msg INTEGER NOT NULL DEFAULT 0,
    awaiting_kb_text TEXT,
    is_dead INTEGER NOT NULL DEFAULT 0,            -- TelegramForbidden
    source TEXT,                                    -- 'request' | 'start' | реф-код (патч 21)
    joined_channel INTEGER NOT NULL DEFAULT 0,     -- успешно прошёл ОП
    channel_link_id INTEGER,                        -- к какой инвайт-ссылке канала привязан (патч 18)
    ref_id INTEGER,                                 -- к какой реф-ссылке привязан
    created_at INTEGER NOT NULL,
    UNIQUE(bot_id, tg_id),
    FOREIGN KEY (bot_id) REFERENCES greeting_bots(id) ON DELETE CASCADE
);

-- Прохождения шагов (для статистики)
CREATE TABLE step_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    step_id INTEGER NOT NULL,
    completed_at INTEGER NOT NULL,
    UNIQUE(user_id, step_id)
);

-- Pending заявки (для проверки спонсоров «по заявкам»)
CREATE TABLE pending_join_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_tg_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(bot_id, chat_id, user_tg_id)
);

-- Реф-ссылки
CREATE TABLE ref_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    clicks INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

-- Инвайт-ссылки канала (патч 17-18, 25)
CREATE TABLE channel_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    name TEXT,
    invite_link TEXT NOT NULL,
    creates_join_request INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);

-- Каналы приветки (патч 27): приветка пишет ТОЛЬКО для заявок из этих каналов,
-- у каждого канала своя задержка старта сценария.
CREATE TABLE welcome_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    title TEXT,
    start_delay INTEGER NOT NULL DEFAULT 0,    -- сек
    created_at INTEGER NOT NULL,
    UNIQUE(bot_id, chat_id)
);

-- Отложенные старты (патч 20): персистентность через перезапуск
CREATE TABLE scheduled_starts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    fire_at INTEGER NOT NULL,
    UNIQUE(bot_id, user_id)
);
```

## ТИПЫ ШАГОВ И ИХ CONFIG-JSON

### roulette (рулетка)
```json
{
  "text": "<html-текст с премиум-эмодзи>",
  "photo_file_id": "...",
  "button_text": "🎰 Крутить",
  "win_amount": "5000 ⭐",
  "is_premium": false           // премиум-рулетка с увеличенным выигрышем
}
```
Реализация: при отправке шага бот шлёт сообщение, ждёт нажатия кнопки → анимация
(стикер вращения 1-2 сек) → присылает поздравление "Ты выиграл X!" → advance.

### op (обязательная подписка)
```json
{
  "text": "...",
  "photo_file_id": "...",
  "sponsors": [
    {
      "name": "Канал спонсора",
      "url": "https://t.me/...",
      "channel_id": -1001234,         // 0 если без проверки
      "check": true,                   // проверять подписку
      "request_mode": false,           // true = проверять через pending_join_requests (заявки)
      "color": "default"
    }
  ],
  "check_button_text": "✅ Проверить",
  "check_button_color": "success",
  "check_button_custom_emoji_id": "...",
  "skip_timer": 15    // патч 23: пауза после исчерпания дублей перед пропуском
}
```
Логика: показать ссылки на спонсоров + кнопку "Проверить". При нажатии — для каждого
спонсора с `check=true`: если `request_mode=false` → проверка `get_chat_member` (member/admin/creator/restricted = ок); если `request_mode=true` → проверка через таблицу `pending_join_requests`. Все прошли → advance + `step_completions`. Не все → alert "Не все подписки".

Если у юзера ОП уже фактически выполнен на момент отправки шага (все каналы пройдены) — пропускаем шаг **без** записи `step_completions` (патч 15).

### message (сообщение)
```json
{
  "text": "...",
  "photo_file_id": "...",
  "animation_file_id": "...",
  "video_file_id": "...",
  "document_file_id": "...",
  "sticker_file_id": "...",
  "copy_from": {"chat_id": -1001, "message_id": 11102},   // если пересланный пост
  "wait_mode": "none" | "timer" | "user_message",
  "wait_timer": 30,                  // если wait_mode=timer
  "keyboard_text": "Нажми сюда",     // если wait_mode=user_message — reply-кнопка
  "buttons": [
    {
      "text": "Получить", 
      "url": "https://...",
      "color": "default|primary|success|danger|warning|secondary",
      "custom_emoji_id": "5402100905883488232"
    }
  ],
  "buttons_layout": "vertical" | "row2" | "row3"   // патчи 14, 16
}
```

## МЕХАНИКА СЦЕНАРИЯ

1. **Получение заявки** (`chat_join_request`):
   - Записываем заявку в `pending_join_requests` (всегда).
   - Если канал — спонсорский «по заявкам» для какой-то приветки, **не** запускаем сценарий (только трекинг).
   - Проверяем что канал есть в `welcome_channels` (патч 27): если в списке пусто или канала нет — игнор. Только разрешённые каналы.
   - `upsert_user` с `source="request"`. Если invite_link заявки совпадает с `channel_links.invite_link` — записываем `channel_link_id` (патч 18).
   - Берём `start_delay` из `welcome_channels` для этого канала (патч 27): если 0 → шлём шаг 0 сразу; иначе — пишем в `scheduled_starts` и просыпаемся через delay (фоновый воркер `_due_starts_worker`, патч 20).

2. **Отправка шага**:
   - Если `typing_mode=1` (патч 19) — шлём `send_chat_action(typing)`, ждём 5-8 сек, потом отправляем.
   - `roulette/op/message` — соответствующая функция.
   - Запоминаем `last_message_id` и `last_message_chat_id` юзера для следующего удаления при advance.

3. **Дублирование застрявшего шага**:
   - Через `duplicate_after` сек после отправки запускаем asyncio.Task: послать шаг ещё раз.
   - Каждый раз прибавляем `duplicate_increment`. Максимум `duplicate_max`.
   - При дубле: предыдущее сообщение удаляем **отложенно** (фоном через 5 сек, патч 11), чтобы юзер заметил повтор.
   - **После исчерпания дублей** в ОП-шаге: ждём `skip_timer` сек (патч 22-23), потом auto-advance (без записи в step_completions).
   - Авто-пропуск **не** засчитывает `step_completions` (патч 15). Только успешная проверка ОП через кнопку — засчитывает.

4. **advance** (переход к следующему шагу):
   - Удаляем предыдущее сообщение (с `delete_timer`).
   - Снимаем reply-keyboard если была.
   - Берём шаг `current_step_order + 1`. Если нет — конец сценария.
   - Если у шага `copy_broken=1` (патч 26) → пропускаем, идём к следующему.
   - Если шаг `op` и юзер уже подписан на всех — пропускаем без записи.
   - Иначе — `_send_step`.

5. **Обработка `chat_member` юзера** (патч 17): когда юзер заходит в канал по нашей инвайт-ссылке, обновляем `bot_users.joined_channel=1`.

## ОБРАБОТКА КОПИЙ ПОСТОВ (`copy_from`)

`copy_message` падает с `Bad Request: message to copy not found` если оригинал удалён. Это надо ловить:
- В `helpers.send_step_message` обернуть `copy_message` в `try/except TelegramBadRequest`, если "message to copy not found" → бросить `CopyOriginGone`.
- В `_send_message_step` ловить `CopyOriginGone` → `db.mark_copy_broken(step_id)` → `record_step_completion` → `asyncio.create_task(advance)` → `return -1` (маркер автоскипа).
- В `scenario_menu` показывать ⚠️ возле шагов с `copy_broken=1` (патч 26).

## КНОПКИ С ЦВЕТОМ И ПРЕМИУМ-ЭМОДЗИ

В aiogram **3.7+** на `InlineKeyboardButton` есть поле `style` (для цвета: 'primary', 'success', 'danger', 'warning', 'secondary'). Поле `icon_custom_emoji_id` — премиум-эмодзи на кнопке — в конструкторе **отсутствует**, но Pydantic-объект его принимает через `object.__setattr__`.

```python
try:
    btn = InlineKeyboardButton(text=t, url=u, style=color)
except TypeError:
    btn = InlineKeyboardButton(text=t, url=u)
if emoji_id:
    try:
        object.__setattr__(btn, "icon_custom_emoji_id", emoji_id)
    except Exception:
        pass
```

Из пересланного поста извлекаем `style` и `icon_custom_emoji_id`: `getattr(b, "style", None)`, `getattr(b, "icon_custom_emoji_id", None)`.

При получении текста поста (свой или пересланный) использовать **`message.html_text`** — он собирает HTML и из `text`, и из `caption` с `entities`, сохраняя премиум-эмодзи и форматирование. **НЕ использовать `message.caption` напрямую**.

## РАСКЛАДКА КНОПОК В MESSAGE-ШАГЕ (патч 14, 16)

После выбора кнопок поста — спрашиваем юзера раскладку:
- 1 в ряд (вертикально) `buttons_layout="vertical"`
- 2 в ряд `buttons_layout="row2"`
- 3 в ряд `buttons_layout="row3"`

В отрисовке кнопки группируются по N в ряд.

## АНТИ-PEER_FLOOD В КАРТОЧКЕ ШАГА (патч 28)

При редактировании сообщения карточки шага (`cb.message.edit_text(...)`) Telegram может вернуть
PEER_FLOOD, если в тексте много премиум-эмодзи и url-ссылок. Поэтому в карточке шага сам текст
**не показывать** — только `📝 Текст: N симв.` и кнопка **👁 Посмотреть текст**, которая шлёт текст ОТДЕЛЬНЫМ новым сообщением (не edit).

## РЕДАКТИРОВАНИЕ ССЫЛОК В ШАГАХ (патч 29 — НОВОЕ)

В карточке шага добавить кнопку **🔗 Ссылки**:
- Извлекает все уникальные URL из `cfg["text"]` (через regex `href=[\'"]([^\'"]+)[\'"]`) и из `cfg["buttons"][i]["url"]`.
- Показывает список URL. Тап на URL → бот спрашивает новую ссылку → меняет ВЕЗДЕ по точному совпадению (и в `text`, и во всех `buttons[i].url` где она была).
- Для шагов с `copy_from` — выдаёт alert "В пересланных постах нельзя".
- Стейт `StepEditStates.wait_new_url`.

## РАЗДЕЛ «ПОСТРОЕНИЕ» (главное меню конструктора)

Главное меню: список добавленных приветок + кнопка ➕ Добавить.

Карточка приветки:
- `📜 Сценарий` → меню шагов с переупорядочиванием
- `⚙️ Настройки` → join_delay, delete_timer, typing_mode, 📢 Каналы приветки (welcome_channels)
- `📊 Статистика` → общая, по реф-ссылкам, по инвайт-ссылкам канала, по шагам
- `📣 Рассылка` → новая рассылка по живым юзерам
- `🔗 Реф-ссылки` → создать/удалить, статистика
- `📨 Инвайт-ссылки канала` → создать через `create_chat_invite_link(creates_join_request=True)` для конкретного канала, накапливать переходы

## РАЗДЕЛ «КАНАЛЫ ПРИВЕТКИ» (welcome_channels, патч 27)

В настройках приветки:
- `📢 Каналы приветки` → меню списка каналов + ➕ добавить
- Добавление: спросить chat_id текстом (не пересылкой — патч 27)
- В карточке канала: переключатель ВКЛ/ВЫКЛ, кнопка ⏱ Задержка → ввести в секундах
- Если список каналов пустой → приветка **не пишет никому** (мы выбрали этот вариант)

## ПРОВЕРКА ОП ЧЕРЕЗ ЗАЯВКИ (request_mode, патч 4)

В таблице `pending_join_requests` храним ВСЕ заявки от юзеров (`UNIQUE(bot_id, chat_id, user_tg_id)`).
Автоочистка раз в час: удалять записи старше 30 дней.

Для спонсора с `request_mode=true` проверка такая: есть ли в `pending_join_requests` запись `(spam_bot_id, sponsor.channel_id, user_tg_id)` → значит юзер подал заявку → засчитываем "подписан".

## БАГИ КОТОРЫЕ НУЖНО НЕ ПОВТОРИТЬ (важно!)

1. **`duplicate_max` затирался `skip_timer`** (нашли в патче 28). При сохранении ОП-шага в `db.add_step` параметр `duplicate_max=draft.get("duplicate_max", 3)`, **не** `duplicate_max=v` где `v` — это значение последнего ввода `skip_timer`. И `skip_timer` идёт в **`cfg`**, не в колонку.

2. **`copy_message` не принимает `link_preview_options`** — превью в копиях не отключаются.

3. **При дублях `cur_count >= duplicate_max`** в `_runner` нельзя сразу удалять и идти дальше — нужно сначала послать дубль, потом проверять лимит на следующей итерации.

4. **`scheduled_starts` хранить в БД** (патч 20) — отложенные старты переживают перезапуск через фоновый воркер `_due_starts_worker`.

5. **Не вызывать `advance` напрямую из `_runner`** — иначе она отменит саму себя через `_cancel_dup`. Использовать `asyncio.create_task(self.advance(...))`.

6. **`_extract_content` для пересланного** — определять источник через `forward_origin` (новая схема aiogram) ИЛИ `forward_from_chat` + `forward_from_message_id` (старая). Сохранять `copy_from = {chat_id, message_id}`.

7. **PEER_FLOOD на edit_text** карточки шага — не показывать сырой текст с премиум-эмодзи и url.

8. **`disable_web_page_preview=True`** или `link_preview_options=LinkPreviewOptions(is_disabled=True)` ставить везде где идёт send_message (патч 24).

9. **При создании приветки** — проверять токен `get_me()`, сохранять `tg_id`, `username`, `name`; и запускать polling в BotManager сразу же (без рестарта основного процесса).

10. **При забане приветки** (Unauthorized) — помечать `is_active=0`, останавливать её polling, уведомлять админа.

## .env

```
BOT_TOKEN=<токен конструктора>
ADMIN_IDS=<id админа>
DB_PATH=/opt/bot/data.db
```

## ВЫХОД

- ZIP-архив с проектом `bot_constructor/`
- README с инструкцией установки на VPS (venv, systemd-юнит `bot.service`, запуск, логи через `journalctl -u bot`)

## КАК ТЕСТИРОВАТЬ

- Создаёшь конструктор, добавляешь по токену приветку.
- В приветку добавляешь канал в `welcome_channels` (по chat_id).
- В сценарии создаёшь 3 шага: рулетка, ОП с 2 спонсорами (1 с проверкой, 1 без), message с медиа и кнопками.
- Подаёшь заявку в канал → проверяешь что сценарий идёт.
- Удаляешь оригинал скопированного поста — шаг должен показаться в сценарии с ⚠️ и пропуститься.
- Жмёшь «🔗 Ссылки» в шаге → меняешь URL → проверяешь что в посте у юзера новый URL и в кнопке тоже.

## ВНЕШНИЙ ВИД

- Все клавиатуры — InlineKeyboardMarkup с emoji в подписях кнопок.
- Тексты сообщений с HTML-форматированием (`<b>`, `<i>`, `<code>`, `<a>`).
- Цвет в кнопках через `style` (если поддерживается версией Telegram).
