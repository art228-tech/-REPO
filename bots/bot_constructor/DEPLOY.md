# 🚀 Деплой в продакшен

Подробное руководство: домен → VPS → nginx + HTTPS → systemd.

## Что тебе нужно купить

### 1. Домен (~$1-15/год)
Telegram WebApp требует HTTPS — без домена не запустить рулетку. Самые удобные регистраторы:

- **Cloudflare** ([cloudflare.com](https://www.cloudflare.com)) — самые низкие цены, бесплатный DNS и CDN. Расплата только картой.
- **Namecheap** ([namecheap.com](https://www.namecheap.com)) — простой интерфейс.
- **Reg.ru** — удобно с российскими картами.

Подойдёт любой `.com`, `.online`, `.xyz`, `.fun` — рулетке без разницы.

### 2. VPS (~$3-7/мес)
Хватит самой простой конфигурации: 1 CPU, 1 GB RAM, 10 GB SSD, Ubuntu 22.04.

- **Hetzner Cloud** ([hetzner.com/cloud](https://www.hetzner.com/cloud)) — €4.51/мес за CX22 (2 vCPU, 4 ГБ). Лучшее соотношение цена/качество в EU.
- **Selectel** ([selectel.ru](https://selectel.ru)) — российские дата-центры, оплата с карт РФ.
- **Timeweb** ([timeweb.cloud](https://timeweb.cloud)) — простой, можно оплатить с РФ-карты.
- **Beget** ([beget.com](https://beget.com)) — бюджетно, российский хостер.

После регистрации создай **сервер с Ubuntu 22.04** и **зайди по SSH**.

### 3. Привязать домен к серверу
В панели регистратора создай A-запись:
```
Type: A
Name: @ (или поддомен, например "bot")
Value: <IP_твоего_VPS>
TTL: 3600
```

DNS обновляется 5-60 минут. Проверь через `ping yourdomain.com`.

---

## Установка на сервер

### 1. Подключение по SSH

```bash
ssh root@<IP_сервера>
```

### 2. Обновить систему и установить зависимости

```bash
apt update && apt upgrade -y
apt install -y python3.12 python3.12-venv python3-pip git nginx certbot python3-certbot-nginx
```

> Если Python 3.12 нет в репах — поставь python3.11 (тоже подойдёт):
> `apt install -y python3.11 python3.11-venv`

### 3. Загрузить код

```bash
mkdir -p /opt/bot
cd /opt/bot
# Распакуй сюда архив bot_constructor.zip (с компа через scp):
# scp bot_constructor.zip root@<IP>:/opt/bot/
unzip bot_constructor.zip
mv bot_constructor/* .
rm -rf bot_constructor bot_constructor.zip
```

### 4. Виртуальное окружение

```bash
cd /opt/bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Настроить `.env`

```bash
cp .env.example .env
nano .env
```

Впиши:
```
BOT_TOKEN=твой_токен_от_BotFather
ADMIN_IDS=твой_telegram_id
DB_PATH=/opt/bot/data.db
WEBAPP_URL=https://yourdomain.com
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8080
```

> `WEBAPP_HOST=127.0.0.1` — чтобы веб-сервер слушал только локалхост, nginx будет проксировать.

### 6. nginx + HTTPS

Создай конфиг nginx:

```bash
nano /etc/nginx/sites-available/bot
```

Вставь:
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Активируй и проверь:
```bash
ln -s /etc/nginx/sites-available/bot /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

Получи HTTPS-сертификат:
```bash
certbot --nginx -d yourdomain.com
```
Certbot спросит email и автоматически перепишет конфиг nginx на HTTPS. Согласись со всеми вопросами. Сертификат продлевается автоматически.

### 7. systemd-сервис

Создай юнит:
```bash
nano /etc/systemd/system/bot.service
```

Вставь:
```ini
[Unit]
Description=Telegram bot-constructor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bot
ExecStart=/opt/bot/venv/bin/python /opt/bot/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Запусти:
```bash
systemctl daemon-reload
systemctl enable --now bot
systemctl status bot
```

Логи смотри так:
```bash
journalctl -u bot -f
```

### 8. Открыть порты

Если стоит UFW:
```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable
```

### 9. Проверка

1. Открой в браузере: `https://yourdomain.com/roulette` — должна показаться рулетка.
2. Открой бота в Telegram, нажми /start, добавь приветку, добавь шаг "рулетка", протестируй на канале/в личке.

---

## Обновление кода

```bash
cd /opt/bot
# обновить файлы (через scp, rsync, git pull — как удобнее)
systemctl restart bot
```

## Бэкап БД

```bash
cp /opt/bot/data.db /backup/data-$(date +%F).db
```

## Если что-то сломалось

```bash
systemctl status bot          # статус
journalctl -u bot -n 100      # последние 100 строк логов
journalctl -u bot -f          # логи в реальном времени
nginx -t                       # проверить конфиг nginx
certbot renew --dry-run        # проверить продление сертификата
```

## Безопасность

- Создай отдельного пользователя вместо root:
  ```bash
  adduser bot
  usermod -aG sudo bot
  # перенастроить systemd-юнит на User=bot, chown /opt/bot
  ```
- Закрой root-вход по SSH (`PermitRootLogin no` в `/etc/ssh/sshd_config`).
- Используй ключи SSH вместо паролей.
- Поставь fail2ban: `apt install fail2ban`.
