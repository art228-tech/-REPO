"""Ошибки конвейера.

Все они рассчитаны на то, что текст попадёт прямо в интерфейс и в журнал,
поэтому формулируются на языке пользователя, а не разработчика.
"""
from __future__ import annotations


class PipelineError(Exception):
    """Базовая ошибка, которую имеет смысл показать пользователю."""


class TemplateError(PipelineError):
    """Шаблон не удалось разобрать или в нём нет нужного элемента."""


class AssetShortage(PipelineError):
    """Закончились входные материалы — клипы или озвучки."""


class ClipTooShort(PipelineError):
    """Клип короче слота, в который его нужно поставить."""


class AudioError(PipelineError):
    """Не удалось разобрать озвучку."""


class ToolMissing(PipelineError):
    """Нет внешнего инструмента: ffmpeg, ffprobe или модели распознавания."""


class ValidationError(PipelineError):
    """Собранный черновик не прошёл самопроверку."""
