"""Пользовательские настройки парсера, редактируемые из бота."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tgparser.db.models import Setting

SETTINGS_KEY = "scan_settings"


@dataclass(slots=True)
class ScanSettings:
    """Всё, что настраивается из бота."""

    # --- что собираем ---

    # Глубина обхода истории в днях. 0 — без ограничения.
    history_depth_days: int = 30

    # Собирать авторов сообщений. Основная стратегия: чтение истории — обычное
    # поведение клиента, антиспам на него почти не реагирует.
    collect_history: bool = True

    # Собирать авторов комментариев под постами каналов.
    collect_comments: bool = True

    # Учитывать служебные сообщения о вступлении. Приезжают вместе с историей,
    # то есть достаются бесплатно, и это единственный способ увидеть тех, кто
    # вступил и молчит, когда список участников скрыт.
    collect_joins: bool = True

    # Там, где список участников собран целиком, история уже ничего не
    # добавит — не тратим на неё часы.
    skip_history_when_roster_done: bool = True

    # Перебирать список участников там, где он открыт. Выключено по умолчанию:
    # это единственная из трёх операций, которая реально притягивает PeerFlood.
    collect_roster: bool = False

    # Пересылать сообщения безтеговых пользователей в архивный канал.
    forward_untagged: bool = True

    skip_bots: bool = True
    skip_deleted: bool = True

    # --- охват ---

    # Для форум-групп: брать только самый активный топик вместо всех.
    # По умолчанию False — история форума читается одним проходом по всем
    # топикам сразу, так что ограничение одним топиком теряет людей бесплатно.
    forum_busiest_topic_only: bool = False

    # Топики, которые пропускаем (подстроки в названии, регистр не важен).
    excluded_topic_titles: list[str] = field(
        default_factory=lambda: ["флуд", "оффтоп", "offtop", "болталка", "куплю/продам"]
    )

    # Чаты, которые пропускаем (id или @username).
    excluded_chats: list[str] = field(default_factory=list)

    # Если непусто — обходим только эти чаты.
    included_chats: list[str] = field(default_factory=list)

    # Пропускать чаты меньше N участников (мелочь обычно нецелевая).
    min_participants: int = 0

    # Не заходить в архивные чаты. Архив — это то, что человек убрал с глаз,
    # и обходить его обычно не нужно.
    skip_archived: bool = True

    # --- темп и защита от флуда ---

    roster_calls_per_hour: int = 20
    history_calls_per_hour: int = 240
    # Пересылки идут в собственный канал и пачками, поэтому бюджет щедрее:
    # это не операция из «спамерского следа».
    write_calls_per_hour: int = 120

    min_delay_sec: float = 1.5
    max_delay_sec: float = 4.0

    # FloodWait длиннее порога не пересиживаем, а прерываем прогон.
    max_flood_wait_sec: int = 300

    # На сколько часов аккаунт выводится из работы после PeerFlood.
    peer_flood_cooldown_hours: int = 24

    # Множитель бюджета на время разгона: свежая сессия не должна сразу
    # выходить на полную скорость.
    warmup_factor: float = 0.25

    # Сколько успешных запросов должно пройти, чтобы разгон снялся.
    # Считаем запросы, а не прогоны: обход большого набора чатов идёт сутками
    # и до конца может не дойти ни разу, а разгон при этом не снимется никогда.
    warmup_calls_required: int = 200

    # Серверный потолок всё равно 10 000, но можно ограничить сильнее.
    roster_limit_per_chat: int = 10_000

    # Порций сообщений за один запрос истории.
    history_batch_size: int = 100

    # --- экспорт ---

    csv_delimiter: str = ";"
    csv_bom: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> ScanSettings:
        data = json.loads(raw)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(slots=True)
class Pace:
    """Действующие бюджеты с учётом накопленной статистики аккаунта.

    Разгон снимается по числу успешных запросов. Если Telegram уже присылал
    FloodWait, бюджет остаётся пониженным: это значит, что выбранный темп
    аккаунту не подошёл, и повышать его бессмысленно.
    """

    settings: ScanSettings
    calls_done: int = 0
    flood_events: int = 0

    @property
    def in_warmup(self) -> bool:
        return self.calls_done < self.settings.warmup_calls_required

    @property
    def throttled(self) -> bool:
        return self.in_warmup or self.flood_events > 0

    @property
    def reason(self) -> str | None:
        if self.flood_events:
            return (
                f"темп понижен: Telegram присылал FloodWait "
                f"{self.flood_events} раз"
            )
        if self.in_warmup:
            done = self.calls_done
            need = self.settings.warmup_calls_required
            return f"разгон: {done} из {need} запросов, бюджет {int(self.settings.warmup_factor * 100)}%"
        return None

    def _scaled(self, base: int, floor: int) -> int:
        if not self.throttled:
            return base
        return max(floor, int(base * self.settings.warmup_factor))

    @property
    def history(self) -> int:
        return self._scaled(self.settings.history_calls_per_hour, 30)

    @property
    def roster(self) -> int:
        return self._scaled(self.settings.roster_calls_per_hour, 1)

    @property
    def write(self) -> int:
        return self._scaled(self.settings.write_calls_per_hour, 20)


async def load_settings(session: AsyncSession, owner_id: int) -> ScanSettings:
    row = await session.scalar(
        select(Setting).where(Setting.owner_id == owner_id, Setting.key == SETTINGS_KEY)
    )
    if row is None:
        return ScanSettings()
    try:
        return ScanSettings.from_json(row.value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ScanSettings()


async def save_settings(
    session: AsyncSession, owner_id: int, settings: ScanSettings
) -> None:
    row = await session.scalar(
        select(Setting).where(Setting.owner_id == owner_id, Setting.key == SETTINGS_KEY)
    )
    if row is None:
        session.add(
            Setting(owner_id=owner_id, key=SETTINGS_KEY, value=settings.to_json())
        )
    else:
        row.value = settings.to_json()
    await session.flush()
