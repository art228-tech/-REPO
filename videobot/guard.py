"""Сторож нагрузки: пауза, когда процессор держится высоко.

Сам бот греть ноутбук нечем — он не жмёт и не перекодирует видео, а выдаёт
ролик по внутреннему идентификатору Telegram, то есть байты идут между
серверами Telegram, а не через этот компьютер. Сторож нужен на случай, когда
тяжело от чего-то другого: рядом собирается партия роликов, идёт распознавание
речи, экспортируется проект.

Порог берётся не по мгновенному значению, а по выдержке: процессор скачет до
ста процентов от любого чиха, и бот, засыпающий на каждом скачке, был бы
бесполезен.

Температуру на Windows надёжно не прочитать — для этого нужны отдельные
драйверы, и на части железа они всё равно молчат. Загрузка процессора читается
везде и означает по сути то же самое.
"""
from __future__ import annotations

import asyncio
import time

from .logs import get_logger

log = get_logger("сторож")

try:
    import psutil
except ImportError:  # без psutil сторож просто не мешает работать
    psutil = None

SAMPLE_S = 3.0


class Guard:
    def __init__(self, limit_percent: int, grace_s: int):
        self.limit = max(1, min(100, limit_percent))
        self.grace_s = max(1, grace_s)
        self.paused = False
        self.last_percent = 0.0
        self._over_since: float | None = None

    @property
    def available(self) -> bool:
        return psutil is not None

    def feed(self, percent: float, moment: float) -> bool:
        """Принимает замер и говорит, стоит ли сейчас работать.

        Вынесено отдельно от чтения датчика, чтобы поведение можно было
        проверить тестами, не нагружая процессор по-настоящему.
        """
        self.last_percent = percent

        if percent >= self.limit:
            if self._over_since is None:
                self._over_since = moment
            elif not self.paused and moment - self._over_since >= self.grace_s:
                self.paused = True
                log.warning(
                    "Процессор держится на %.0f%% дольше %d с — встаю на паузу",
                    percent, self.grace_s)
        else:
            self._over_since = None
            if self.paused:
                self.paused = False
                log.info("Процессор отпустил (%.0f%%) — продолжаю", percent)

        return not self.paused

    async def watch(self) -> None:
        """Фоновый замер. Работает, пока задачу не отменят."""
        if psutil is None:
            log.info("psutil не установлен — сторож нагрузки выключен")
            return

        psutil.cpu_percent(interval=None)  # первый вызов всегда возвращает ноль
        while True:
            await asyncio.sleep(SAMPLE_S)
            self.feed(psutil.cpu_percent(interval=None), time.monotonic())

    async def wait_until_free(self) -> None:
        """Придерживает работу, пока сторож на паузе."""
        while self.paused:
            await asyncio.sleep(SAMPLE_S)
