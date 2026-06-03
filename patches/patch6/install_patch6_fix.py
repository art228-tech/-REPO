#!/usr/bin/env python3
"""Fix для patch6: реализация «Добавить спонсора» + фикс конфликта sprm↔spdel."""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
shutil.copy(HERE / "sponsor_edit.py", "/opt/bot/handlers/sponsor_edit.py")
print("  ✓ handlers/sponsor_edit.py обновлён")
print("\n✅ Готово. Перезапусти: systemctl restart bot")
