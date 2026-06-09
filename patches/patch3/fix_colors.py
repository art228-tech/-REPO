#!/usr/bin/env python3
"""Фикс палитры цветов в утилитах под Bot API 9.4: только 3 цвета, danger вместо destructive."""
import re

P = "/opt/bot/utils/helpers.py"
with open(P, encoding="utf-8") as f:
    src = f.read()

# 1) STYLE_LABELS — оставляем 4 пункта: default + 3 цвета (без secondary)
old = '''STYLE_LABELS = {
    "default":      "⚪ Стандартная",
    "primary":      "🔵 Синяя",
    "success":      "🟢 Зелёная",
    "destructive":  "🔴 Красная",
    "secondary":    "⚫ Серая",
}'''
new = '''STYLE_LABELS = {
    "default":  "⚪ Стандартная",
    "primary":  "🔵 Синяя",
    "success":  "🟢 Зелёная",
    "danger":   "🔴 Красная",
}'''
assert old in src, "STYLE_LABELS pattern not found"
src = src.replace(old, new)

# 2) _LEGACY_TO_STYLE — все красные/опасные → danger; secondary убираем,
# жёлтые и пр. вторичные → default
old = '''_LEGACY_TO_STYLE = {
    "default": "",
    "blue":    "primary",
    "green":   "success",
    "red":     "destructive",
    "yellow":  "secondary",
    "purple":  "primary",
    "orange":  "destructive",
    "white":   "",
    "black":   "secondary",
    "fire":    "destructive",
    "star":    "primary",
    "heart":   "destructive",
    "rocket":  "primary",
    "lock":    "secondary",
    "key":     "primary",
    "check":   "success",
    "cross":   "destructive",
    "gift":    "success",
    "primary":     "primary",
    "success":     "success",
    "destructive": "destructive",
    "secondary":   "secondary",
}'''
new = '''_LEGACY_TO_STYLE = {
    "default": "",
    "blue":    "primary",
    "green":   "success",
    "red":     "danger",
    "yellow":  "",
    "purple":  "primary",
    "orange":  "danger",
    "white":   "",
    "black":   "",
    "fire":    "danger",
    "star":    "primary",
    "heart":   "danger",
    "rocket":  "primary",
    "lock":    "",
    "key":     "primary",
    "check":   "success",
    "cross":   "danger",
    "gift":    "success",
    "primary":     "primary",
    "success":     "success",
    "danger":      "danger",
    # Старые алиасы для обратной совместимости
    "destructive": "danger",
    "secondary":   "",
}'''
assert old in src, "_LEGACY_TO_STYLE pattern not found"
src = src.replace(old, new)

with open(P, "w", encoding="utf-8") as f:
    f.write(src)
print("helpers.py patched: 3 colors, danger instead of destructive")
