#!/bin/bash
set -e
# Первый деплой на чистый Ubuntu 22.04/24.04 (запуск из корня проекта на сервере /opt/anime-telegram-bot)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/anime-bot.service /etc/systemd/system/
sudo cp deploy/anime-parser.service /etc/systemd/system/
sudo cp deploy/anime-parser.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now anime-bot.service
sudo systemctl enable --now anime-parser.timer
echo "OK: bot running, parser every 6h"
systemctl status anime-bot.service --no-pager | head -15
