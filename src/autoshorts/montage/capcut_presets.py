"""Реальные ID пресетов CapCut 8.7.0, извлечённые из эталонного проекта
пользователя (templates/capcut_reference_8.7.json).

Эти значения используются генератором черновика, чтобы CapCut применял ровно
тот же стиль (субтитры «Сияние», анимации «Зум/Качели/Осветление», блюр-фон),
что и в ручном проекте.
"""
from __future__ import annotations

# Субтитры: шаблон текста «Сияние» (розово-фиолетовый) + шрифт + анимация текста.
SUBTITLE_TEXT_TEMPLATE_RESOURCE_ID = "7577568565935475985"  # cc_胖卡通粉紫对比_english
SUBTITLE_TEXT_TEMPLATE_NAME = "cc_胖卡通粉紫对比_english"
SUBTITLE_FONT_RESOURCE_ID = "7579481374890003713"           # шрифт «блок»
SUBTITLE_CAPTION_ANIM_RESOURCE_ID = "7362061652197380625"   # анимация субтитров
SUBTITLE_SCALE_X = 1.14
SUBTITLE_POS_Y = -0.4753645833333333                        # ниже центра

# Видео-эффект блюра (для фоновой размытой копии).
BLUR_EFFECT_RESOURCE_ID = "7399464929830423813"             # «Размытие»
BLUR_BG_SCALE = 4.2                                         # копия на весь экран
MAIN_BG_SCALE = 2.33                                        # основной блок

# Комбо-анимации эмодзи (наборы «Зум/Качели/Отскок»).
# id с пустым значением — пресеты, которых ещё нет в эталоне (отскок 1/2):
# их реальные ID добавим, когда получим проект, где они применены.
ANIM = {
    "zoom1": {"id": "6759078592740594184", "name": "Зум 1",
              "category_id": "2037708346", "category_name": "Trending-1",
              "type": "group", "duration": 2233333},
    "zoom2": {"id": "6740867832570974733", "name": "Зум 2",
              "category_id": "2037708312", "category_name": "Basic",
              "type": "in", "duration": 233333},
    "swing_down": {"id": "6739338374441603598", "name": "Качели вниз",
                   "category_id": "2037708296", "category_name": "Trending1",
                   "type": "in", "duration": 500000},
    # заготовки — заполнить реальными ID из проекта с отскоком:
    "bounce1": {"id": "", "name": "Отскок 1", "category_id": "",
                "category_name": "", "type": "in", "duration": 500000},
    "bounce2": {"id": "", "name": "Отскок 2", "category_id": "",
                "category_name": "", "type": "in", "duration": 500000},
}

# Скорость проигрывания эмодзи (в эталоне 1.33) — сохраняется при клонировании.
EMOJI_SPEED = 1.33

# Громкость фоновой музыки по умолчанию (задаётся в интерфейсе при добавлении).
MUSIC_VOLUME_DEFAULT = 0.15


def emoji_anim_choices() -> list[str]:
    """Доступные комбо-анимации эмодзи (только с известными ID)."""
    return [k for k in ("zoom1", "zoom2", "bounce1", "bounce2")
            if ANIM.get(k, {}).get("id")]
# Выход (для QR): осветление.
ANIM_OUT_LIGHTEN = {"id": "6798320902548230669", "name": "Осветление",
                    "category_id": "2037708371", "category_name": "Trending-2",
                    "type": "out", "duration": 233333}

# Анимация перехода в начале (jump-cut ~2.17с).
INTRO_TRANSITION_ANIM = ANIM["swing_down"]

# Кандидаты комбо-анимации эмодзи (рандом): пользователь просил zoom1/2, отскок1/2.
EMOJI_ANIM_CHOICES = ["zoom1", "zoom2"]

# Громкости из эталона.
VOL_VOICE = 1.0
VOL_SWOOSH = 0.125
VOL_MUSIC = 0.05          # фоновая музыка очень тихо
VOL_ACCENT = 1.0

# Позиции/масштабы оверлеев из эталона.
EMOJI_SCALE = 0.8
EMOJI_POS_Y = 0.234
QR_SCALE = 0.54
QR_POS_Y = 0.24

# Тайминг QR в конце.
QR_TOTAL_SEC = 1.2
QR_IN_SEC = 0.233
QR_OUT_SEC = 0.233

# Точка перехода/jump-cut в начале.
INTRO_JUMPCUT_SEC = 2.17
