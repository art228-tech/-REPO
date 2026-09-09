"""Статистика: что из признаков ролика даёт больше просмотров.

Считаются не просмотры, а **просмотры в сутки**. Пять тысяч за день лучше
десяти тысяч за неделю, а по одним только просмотрам выходило бы наоборот:
ролик, который просто дольше лежит, всегда обгонял бы свежий.

Возраст берётся от скачивания: когда человек выложил ролик, бот не знает.
Ролики моложе суток считаются за сутки — иначе замер, сделанный через час после
скачивания, дал бы двадцатичетырёхкратную величину и один такой ролик перекосил
бы всю группу.

Рядом со средним всегда стоит количество роликов. Без него «чёрный фон — 4200,
размытый — 3100» выглядит как вывод, хотя за первым числом могло стоять три
ролика, и завтра оно станет другим.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import parse

# Шаг группировки числовых признаков. Длительность роликов держится около
# десяти-шестнадцати секунд, поэтому двухсекундный шаг даёт три-четыре группы —
# достаточно, чтобы увидеть разницу, и не так мелко, чтобы в каждой оказалось
# по одному ролику.
DURATION_STEP_S = 2.0
QR_STEP_S = 1.0

MIN_AGE_DAYS = 1.0


@dataclass
class Group:
    label: str
    count: int = 0
    views: int = 0
    per_day: float = 0.0
    order: float = 0.0


@dataclass
class Section:
    title: str
    groups: list[Group] = field(default_factory=list)


def age_days(row) -> float:
    """Сколько ролик прожил к моменту замера, но не меньше суток."""
    taken = parse(row["taken_at"])
    measured = parse(row["measured_at"])
    if not taken or not measured:
        return MIN_AGE_DAYS
    days = (measured - taken).total_seconds() / 86400
    return max(days, MIN_AGE_DAYS)


def per_day(row) -> float:
    return float(row["views"]) / age_days(row)


def bucket(value: float, step: float) -> tuple[float, str]:
    """Группа для числа: «10–12 с». Возвращает ещё и низ группы для сортировки."""
    if value <= 0:
        return -1.0, "не указано"
    low = int(value / step) * step
    high = low + step
    return low, f"{_number(low)}–{_number(high)} с"


def _number(value: float) -> str:
    return f"{value:g}"


def _label_background(value: str) -> str:
    return {"black": "чёрный", "blur": "размытый"}.get(value, value or "не указан")


def _label_music(value) -> str:
    return "есть" if value else "нет"


def report(rows) -> list[Section]:
    """Собирает разбивку по каждому признаку.

    На вход идут только ролики с вписанными просмотрами: без замера ролик в
    статистике не участвует.
    """
    sections = [
        Section("Фон"),
        Section("Папка озвучки"),
        Section("Фоновая музыка"),
        Section("Длительность ролика"),
        Section("Длительность QR"),
    ]
    keys: list[dict[str, Group]] = [{} for _ in sections]

    for row in rows:
        speed = per_day(row)
        views = int(row["views"])

        pairs = [
            (_label_background(row["background"]), 0.0),
            (row["voice_folder"] or "не указана", 0.0),
            (_label_music(row["music"]), 0.0 if row["music"] else 1.0),
            bucket(float(row["duration_s"]), DURATION_STEP_S)[::-1],
            bucket(float(row["qr_s"]), QR_STEP_S)[::-1],
        ]

        for index, (label, order) in enumerate(pairs):
            group = keys[index].get(label)
            if group is None:
                group = Group(label=label, order=float(order))
                keys[index][label] = group
                sections[index].groups.append(group)
            group.count += 1
            group.views += views
            group.per_day += speed

    for section in sections:
        for group in section.groups:
            group.per_day = group.per_day / group.count if group.count else 0.0
        section.groups.sort(key=lambda item: (item.order, item.label))
    return sections


def describe(sections: list[Section], total: int, skipped: int) -> str:
    """Текст статистики для сообщения в боте."""
    if not total:
        return (
            "Пока не по чему считать: ни в одном ролике не вписаны просмотры.\n\n"
            "Ролик попадает в статистику, когда человек указал по нему просмотры."
        )

    lines = [f"Роликов с просмотрами: {total}"]
    if skipped:
        lines.append(f"Без просмотров, не в счёт: {skipped}")
    lines.append("")
    lines.append("Просмотров в сутки, в скобках — сколько роликов:")

    for section in sections:
        if not section.groups:
            continue
        lines.append("")
        lines.append(f"<b>{section.title}</b>")
        best = max(group.per_day for group in section.groups)
        for group in section.groups:
            mark = " ←" if group.per_day == best and len(section.groups) > 1 else ""
            lines.append(
                f"  {group.label}: {group.per_day:,.0f} ({group.count}){mark}"
                .replace(",", " ")
            )

    thin = [f"{section.title.lower()}" for section in sections
            if any(0 < group.count < 5 for group in section.groups)]
    if thin:
        lines.append("")
        lines.append(
            "Где роликов меньше пяти, разница — скорее случайность, чем правило: "
            + ", ".join(thin) + "."
        )
    return "\n".join(lines)
