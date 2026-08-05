#!/bin/bash

# ============================================================
#   Установщик конструктора приветственных ботов
#   Поддержка: Ubuntu 20.04 / 22.04 / 24.04
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/tg-constructor"
REPO_ZIP_URL=""   # заполняется ниже если нужно

print_banner() {
    echo -e "${CYAN}"
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║   🤖  Конструктор приветственных ботов       ║"
    echo "  ║       Автоматическая установка               ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo -e "${NC}"
}

step() {
    echo -e "\n${BLUE}${BOLD}▶ $1${NC}"
}

ok() {
    echo -e "${GREEN}✅ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

err() {
    echo -e "${RED}❌ $1${NC}"
    exit 1
}

ask() {
    # ask <VAR_NAME> <prompt> [default]
    local varname=$1
    local prompt=$2
    local default=$3
    local value=""

    while [[ -z "$value" ]]; do
        if [[ -n "$default" ]]; then
            read -rp "$(echo -e "${BOLD}$prompt${NC} [${default}]: ")" value
            value="${value:-$default}"
        else
            read -rp "$(echo -e "${BOLD}$prompt${NC}: ")" value
        fi
        if [[ -z "$value" ]]; then
            warn "Поле не может быть пустым. Попробуйте снова."
        fi
    done
    eval "$varname='$value'"
}

ask_optional() {
    local varname=$1
    local prompt=$2
    read -rp "$(echo -e "${BOLD}$prompt${NC} (Enter = пропустить): ")" value
    eval "$varname='$value'"
}

# ── Проверка root / sudo ──────────────────────────────────────
check_privileges() {
    if [[ $EUID -ne 0 ]]; then
        SUDO="sudo"
        if ! command -v sudo &>/dev/null; then
            err "Запустите скрипт от root или установите sudo."
        fi
    else
        SUDO=""
    fi
}

# ── Установка Docker ─────────────────────────────────────────
install_docker() {
    step "Проверка Docker..."

    if command -v docker &>/dev/null; then
        ok "Docker уже установлен: $(docker --version)"
    else
        step "Установка Docker..."
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq ca-certificates curl gnupg lsb-release

        $SUDO install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
            $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        $SUDO chmod a+r /etc/apt/keyrings/docker.gpg

        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
          https://download.docker.com/linux/ubuntu \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null

        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
            docker-buildx-plugin docker-compose-plugin

        # Добавить текущего пользователя в группу docker
        if [[ -n "$SUDO_USER" ]]; then
            $SUDO usermod -aG docker "$SUDO_USER"
        fi

        $SUDO systemctl enable docker
        $SUDO systemctl start docker
        ok "Docker установлен!"
    fi

    # Проверяем docker compose
    if docker compose version &>/dev/null; then
        ok "Docker Compose доступен: $(docker compose version --short)"
    else
        err "Docker Compose не найден. Попробуйте переустановить Docker."
    fi
}

# ── Установка утилит ─────────────────────────────────────────
install_utils() {
    step "Установка утилит..."
    $SUDO apt-get install -y -qq unzip curl wget git 2>/dev/null || true
    ok "Утилиты готовы"
}

# ── Распаковка / копирование кода ────────────────────────────
setup_project() {
    step "Подготовка проекта в $INSTALL_DIR..."

    mkdir -p "$INSTALL_DIR"

    # Если скрипт запущен из папки, где уже лежит код — используем его
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [[ -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
        ok "Код найден рядом со скриптом, копирую..."
        cp -r "$SCRIPT_DIR"/. "$INSTALL_DIR/"
    elif [[ -f "$SCRIPT_DIR/tg-constructor.zip" ]]; then
        ok "Найден архив tg-constructor.zip, распаковываю..."
        unzip -o "$SCRIPT_DIR/tg-constructor.zip" -d "$HOME/tg_tmp"
        cp -r "$HOME/tg_tmp/tg-constructor/." "$INSTALL_DIR/"
        rm -rf "$HOME/tg_tmp"
    else
        err "Не найден код проекта рядом со скриптом install.sh.\nПоложите install.sh в одну папку с tg-constructor.zip (или с папкой проекта) и запустите снова."
    fi

    mkdir -p "$INSTALL_DIR/media"
    ok "Файлы проекта готовы"
}

# ── Интерактивная настройка .env ─────────────────────────────
configure_env() {
    step "Настройка конфигурации (.env)"

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD} Шаг 1: Токен бота-конструктора${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  1. Откройте Telegram → @BotFather"
    echo "  2. Отправьте /newbot"
    echo "  3. Введите имя и username"
    echo "  4. Скопируйте токен вида: 1234567890:AAHxxx..."
    echo ""
    ask CONSTRUCTOR_TOKEN "Вставьте токен конструктора"

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD} Шаг 2: Ваш Telegram ID (администратор)${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  Напишите /start боту @userinfobot — он покажет ваш ID."
    echo "  Можно указать несколько через запятую: 123456,789012"
    echo ""
    ask ADMIN_IDS "Ваш Telegram ID"

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD} Шаг 3: Пароль базы данных${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  Придумайте надёжный пароль (только латинские буквы и цифры)."
    echo ""
    ask DB_PASS "Пароль для PostgreSQL" "BotPass$(shuf -i 1000-9999 -n 1)"

    # Генерируем .env
    cat > "$INSTALL_DIR/.env" <<EOF
# === CONSTRUCTOR BOT ===
CONSTRUCTOR_BOT_TOKEN=${CONSTRUCTOR_TOKEN}
CONSTRUCTOR_ADMIN_IDS=${ADMIN_IDS}

# === DATABASE ===
POSTGRES_USER=botuser
POSTGRES_PASSWORD=${DB_PASS}
POSTGRES_DB=botdb
DATABASE_URL=postgresql+asyncpg://botuser:${DB_PASS}@postgres:5432/botdb

# === REDIS ===
REDIS_URL=redis://redis:6379/0

# === MISC ===
MEDIA_DIR=/app/media
LOG_LEVEL=INFO
EOF

    ok ".env файл создан"
}

# ── Сборка и запуск ──────────────────────────────────────────
build_and_start() {
    step "Сборка Docker образов (может занять 2-5 минут)..."
    cd "$INSTALL_DIR"

    # Убедимся что docker доступен для текущего пользователя
    if ! docker info &>/dev/null; then
        $SUDO docker compose up -d --build
    else
        docker compose up -d --build
    fi

    ok "Контейнеры запущены!"
}

# ── Проверка статуса ─────────────────────────────────────────
check_status() {
    step "Проверка статуса контейнеров..."
    sleep 5
    cd "$INSTALL_DIR"

    if ! docker info &>/dev/null; then
        $SUDO docker compose ps
    else
        docker compose ps
    fi
}

# ── Настройка автозапуска ────────────────────────────────────
setup_autostart() {
    step "Настройка автозапуска при перезагрузке сервера..."

    # Docker сам перезапускает контейнеры с restart: always
    # Дополнительно добавим systemd unit для надёжности
    cat > /tmp/tg-constructor.service <<EOF
[Unit]
Description=TG Constructor Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

    $SUDO mv /tmp/tg-constructor.service /etc/systemd/system/tg-constructor.service
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable tg-constructor.service 2>/dev/null || true
    ok "Автозапуск настроен (systemd)"
}

# ── Создание скрипта управления ──────────────────────────────
create_manage_script() {
    cat > "$INSTALL_DIR/manage.sh" <<'MANAGE'
#!/bin/bash
# Управление конструктором ботов

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$INSTALL_DIR"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

case "$1" in
    start)
        echo -e "${GREEN}▶ Запуск...${NC}"
        docker compose up -d
        ;;
    stop)
        echo -e "${GREEN}⏹ Остановка...${NC}"
        docker compose down
        ;;
    restart)
        echo -e "${GREEN}🔄 Перезапуск...${NC}"
        docker compose restart
        ;;
    logs)
        SERVICE="${2:-}"
        if [[ -n "$SERVICE" ]]; then
            docker compose logs -f "$SERVICE"
        else
            docker compose logs -f
        fi
        ;;
    status)
        docker compose ps
        ;;
    update)
        echo -e "${GREEN}⬆️ Обновление...${NC}"
        docker compose down
        docker compose up -d --build
        ;;
    backup)
        FILENAME="backup_$(date +%Y%m%d_%H%M%S).sql"
        docker compose exec postgres pg_dump -U botuser botdb > "$FILENAME"
        echo -e "${GREEN}✅ Бэкап сохранён: $FILENAME${NC}"
        ;;
    restore)
        if [[ -z "$2" ]]; then
            echo "Использование: ./manage.sh restore backup_20240101.sql"
            exit 1
        fi
        docker compose exec -T postgres psql -U botuser botdb < "$2"
        echo -e "${GREEN}✅ Восстановлено из $2${NC}"
        ;;
    *)
        echo -e "${CYAN}${BOLD}Управление конструктором ботов${NC}"
        echo ""
        echo "  ./manage.sh start         — запустить"
        echo "  ./manage.sh stop          — остановить"
        echo "  ./manage.sh restart       — перезапустить"
        echo "  ./manage.sh status        — статус контейнеров"
        echo "  ./manage.sh logs          — все логи"
        echo "  ./manage.sh logs constructor    — логи конструктора"
        echo "  ./manage.sh logs welcome_manager — логи ботов"
        echo "  ./manage.sh update        — пересобрать и перезапустить"
        echo "  ./manage.sh backup        — бэкап базы данных"
        echo "  ./manage.sh restore FILE  — восстановить из бэкапа"
        ;;
esac
MANAGE

    chmod +x "$INSTALL_DIR/manage.sh"
    ok "Скрипт управления создан: $INSTALL_DIR/manage.sh"
}

# ── Финальный вывод ──────────────────────────────────────────
print_success() {
    echo ""
    echo -e "${GREEN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║        ✅  Установка завершена!              ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo -e "${BOLD}📁 Проект установлен в:${NC} $INSTALL_DIR"
    echo ""
    echo -e "${BOLD}🤖 Откройте ваш бот-конструктор в Telegram и отправьте /start${NC}"
    echo ""
    echo -e "${CYAN}${BOLD}Управление:${NC}"
    echo "  cd $INSTALL_DIR"
    echo "  ./manage.sh status          — проверить статус"
    echo "  ./manage.sh logs constructor — логи конструктора"
    echo "  ./manage.sh restart         — перезапустить всё"
    echo "  ./manage.sh backup          — бэкап базы данных"
    echo ""
    echo -e "${CYAN}${BOLD}Следующие шаги:${NC}"
    echo "  1. Откройте бот-конструктор в Telegram → /start"
    echo "  2. Нажмите ➕ Добавить бота"
    echo "  3. Вставьте токен приветственного бота из @BotFather"
    echo "  4. Настройте сценарий: добавьте шаги и ОП"
    echo "  5. Добавьте приветственного бота администратором в ваш канал"
    echo ""
}

# ── MAIN ─────────────────────────────────────────────────────
main() {
    print_banner
    check_privileges
    install_utils
    install_docker
    setup_project
    configure_env
    build_and_start
    check_status
    setup_autostart
    create_manage_script
    print_success
}

main
