# 🚀 Деплой конструктора приветственных ботов

## Структура проекта

```
tg-constructor/
├── constructor_bot/       # Бот-конструктор (управление)
│   ├── handlers/
│   │   ├── start.py       # /start и главное меню
│   │   ├── bots_list.py   # Список ботов
│   │   ├── add_bot.py     # Добавление нового бота
│   │   ├── scenario_editor.py  # Редактор сценария
│   │   ├── bot_settings.py     # Настройки бота
│   │   ├── statistics.py       # Статистика
│   │   └── broadcast.py        # Рассылка
│   ├── keyboards/menus.py      # Клавиатуры
│   └── middlewares/admin.py    # Проверка администраторов
│
├── welcome_bot/           # Движок приветственных ботов
│   ├── handlers/user.py        # Хэндлеры пользователей
│   ├── utils/
│   │   ├── scenario_engine.py  # Логика сценария
│   │   ├── sender.py           # Отправка сообщений
│   │   └── subscription.py    # Проверка подписки
│   └── main.py                 # Менеджер дочерних ботов
│
├── shared/
│   ├── models.py          # Модели БД (SQLAlchemy)
│   └── db.py              # Хелпер сессии
│
├── docker-compose.yml
├── Dockerfile.constructor
├── Dockerfile.welcome
├── requirements.txt
└── .env.example
```

---

## Шаг 1: Подготовка сервера (Ubuntu 22.04/24.04)

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Установка Docker Compose (если не установлен)
sudo apt install docker-compose-plugin -y

# Проверка
docker --version
docker compose version
```

---

## Шаг 2: Загрузка кода на сервер

```bash
# Создаём папку проекта
mkdir -p ~/tg-constructor
cd ~/tg-constructor

# Загружаем файлы (через scp, git или sftp)
# Пример через scp с локального компьютера:
# scp -r ./tg-constructor user@YOUR_SERVER_IP:~/

# Или через git (если выложили в репозиторий):
# git clone https://github.com/yourname/tg-constructor.git .
```

---

## Шаг 3: Создание бота-конструктора в BotFather

1. Откройте @BotFather в Telegram
2. Отправьте `/newbot`
3. Введите имя: например `My Constructor Bot`
4. Введите username: например `my_constructor_bot`
5. Скопируйте токен вида `1234567890:AAHxxx...`

---

## Шаг 4: Настройка .env файла

```bash
cd ~/tg-constructor
cp .env.example .env
nano .env
```

Заполните:
```env
CONSTRUCTOR_BOT_TOKEN=1234567890:AAHxxx...    # токен конструктора
CONSTRUCTOR_ADMIN_IDS=123456789               # ваш Telegram ID (узнайте у @userinfobot)

POSTGRES_USER=botuser
POSTGRES_PASSWORD=ВашНадёжныйПароль123
POSTGRES_DB=botdb
DATABASE_URL=postgresql+asyncpg://botuser:ВашНадёжныйПароль123@postgres:5432/botdb

REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

---

## Шаг 5: Запуск

```bash
cd ~/tg-constructor

# Собрать и запустить все контейнеры
docker compose up -d --build

# Проверить статус
docker compose ps

# Смотреть логи конструктора
docker compose logs -f constructor

# Смотреть логи менеджера ботов
docker compose logs -f welcome_manager
```

---

## Шаг 6: Первый запуск конструктора

1. Откройте конструктор-бот в Telegram
2. Отправьте `/start`
3. Нажмите **➕ Добавить бота**
4. Вставьте токен приветственного бота (создайте через @BotFather)
5. Укажите задержку первого сообщения (например `0`)
6. Укажите таймер напоминания (например `3600`)

---

## Шаг 7: Настройка сценария

После добавления бота:
1. Нажмите **📋 Сценарий**
2. Нажмите **➕ Добавить шаг**
3. Выберите тип: **💬 Сообщение** или **🔒 ОП**

### Добавить сообщение:
- Перешлите боту-конструктору любое сообщение (текст, фото, видео, стикер)
- Сообщение с кнопками: кнопки сохранятся автоматически
- Для ожидания ввода пользователя — не добавляйте кнопки

### Добавить ОП:
- Нажмите **📢 Спонсоры**
- Добавьте каждого спонсора: **название + ссылка + ID канала**
- ID канала = 0, если проверка не нужна
- Приветственный бот должен быть **администратором** канала спонсора

### Задержка между шагами:
- В меню шага нажмите **⏱ Задержка после шага**
- Введите секунды (0 = без задержки)
- Необязательно: добавьте **🔔 Текст ожидания** — он будет показан во время ожидания

---

## Шаг 8: Привязка канала к приветственному боту

1. Добавьте приветственного бота в канал как **администратора**
2. В настройках бота укажите **📡 Привязать канал** и введите ID канала

Пользователи, которые подают заявку в канал через реферальную ссылку, будут:
- Попадать в статистику с тегом источника
- Получать приветственное сообщение от бота

---

## Управление

```bash
# Перезапуск
docker compose restart

# Остановка
docker compose down

# Обновление кода и перезапуск
git pull  # или загрузите файлы
docker compose up -d --build

# Бэкап базы данных
docker compose exec postgres pg_dump -U botuser botdb > backup_$(date +%Y%m%d).sql

# Восстановление из бэкапа
docker compose exec -T postgres psql -U botuser botdb < backup_20240101.sql
```

---

## Мониторинг

```bash
# Все логи вместе
docker compose logs -f

# Только ошибки
docker compose logs -f | grep -i error

# Использование ресурсов
docker stats
```

---

## Частые вопросы

**Q: Как узнать свой Telegram ID?**
A: Напишите `/start` боту @userinfobot — он покажет ваш ID.

**Q: Как узнать ID канала?**
A: Перешлите любое сообщение из канала боту @userinfobot.

**Q: Бот не отвечает на /start в конструкторе?**
A: Проверьте, что ваш ID добавлен в CONSTRUCTOR_ADMIN_IDS в .env файле.

**Q: Проверка подписки не работает?**
A: Убедитесь, что приветственный бот добавлен **администратором** канала спонсора.

**Q: Как добавить нескольких администраторов конструктора?**
A: В .env укажите ID через запятую: `CONSTRUCTOR_ADMIN_IDS=123456789,987654321`
