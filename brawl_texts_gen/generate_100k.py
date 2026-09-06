#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
100000 Brawl Stars promo texts — rebuilt from full chat rules.

Hard rules from chat:
- No: QR, подарок/подарки, бесплатно, em/en dash, отметка, раздел, списки изменений
- Бравл Старс only (Russian)
- Subjects: разработчики / Бравл Старс / Суперсэлл / создатели Бравл Старс /
  команда Бравл Старс / команда разработчиков
- Rewards x4 equal: ультраящик, ультрахаосдроп, Бравл Пасс, Бравл Пасс Плюс
- награда in ~50% texts
- раздача/раздавать rare
- календарь/изменения ~1/20
- Length: STRICT ±10% of THAT template's canonical length
- Adjacent texts: different template + different reward
- Ending style: «вам остаётся лишь забрать её/его» often
"""

from __future__ import annotations

import hashlib
import random
import shutil
import zipfile
from collections import defaultdict, deque
from pathlib import Path

OUT_DIR = Path("/tmp/brawl_txt_100k")
ZIP_ART = Path("/opt/cursor/artifacts/brawl_stars_texts_100000.zip")
ZIP_REPO = Path("/workspace/brawl_stars_texts_100000.zip")
TARGET = 100_000
SEED = 417042

FORBIDDEN = (
    "qr", "подарок", "подарки", "подарка", "подарков", "подароч",
    "бесплатн", "—", "–", "отметк", "раздел",
    "список изменений", "списке изменений",
)

# ---- approved banks ----
RECENT_ADV = [
    "недавно", "совсем недавно", "не так давно", "на днях",
    "только что", "буквально только что",
]
RECENT_OPEN = [
    "Совсем недавно стало известно",
    "Недавно появилась информация",
]
AGAIN = ["снова", "вновь", "опять", "в очередной раз"]
AGAIN_DID = ["снова решили", "вновь решили"]
BUT = ["но", "однако", "при этом", "вот только"]

FEW = [
    "мало кто это заметил",
    "почти никто этого не заметил",
    "немногие это заметили",
    "далеко не все это заметили",
    "лишь некоторые игроки это заметили",
    "небольшая часть игроков это заметила",
    "большинство игроков этого не заметило",
    "многие игроки этого не заметили",
    "об этом знают единицы",
    "информация дошла не до всех",
]

SHOW = [
    "Сейчас покажу",
    "Расскажу, что делать",
    "Объясню весь способ",
    "Покажу, как получить",
    "Расскажу, как забрать",
    "Покажу всё по порядку",
    "Объясню, что нужно сделать",
    "Покажу нужный способ",
]

NA = [
    "Награда доступна, вам остаётся лишь забрать её!",
    "Награда найдена, вам остаётся лишь забрать её!",
    "Награда уже доступна, вам остаётся лишь забрать её!",
    "Награда ждёт, вам остаётся лишь забрать её!",
]

# actions: (plural, singular), object case
ACT = [
    (("выдали", "выдала"), "acc"),
    (("добавили", "добавила"), "acc"),
    (("подготовили", "подготовила"), "acc"),
    (("решили выдать", "решила выдать"), "acc"),
    (("начали выдавать", "начала выдавать"), "acc"),
    (("дали возможность забрать", "дала возможность забрать"), "acc"),
    (("запустили выдачу", "запустила выдачу"), "gen"),
]
ACT_RARE = [(("раздают", "раздаёт"), "acc")]

SUBJ = [
    {"nom": "Разработчики", "low": "разработчики", "pl": True},
    {"nom": "Бравл Старс", "low": "Бравл Старс", "pl": True},
    {"nom": "Суперсэлл", "low": "Суперсэлл", "pl": True},
    {"nom": "Создатели Бравл Старс", "low": "создатели Бравл Старс", "pl": True},
    {"nom": "Команда Бравл Старс", "low": "команда Бравл Старс", "pl": False},
    {"nom": "Команда разработчиков", "low": "команда разработчиков", "pl": False},
]

REWARDS = [
    {"id": "box", "acc": "ультраящик", "gen": "ультраящика", "ins": "ультраящиком", "few": "ультраящика",
     "gpl": "ультраящиков", "apl": "ультраящики", "pron": "его", "pass": False},
    {"id": "drop", "acc": "ультрахаосдроп", "gen": "ультрахаосдропа", "ins": "ультрахаосдропом", "few": "ультрахаосдропа",
     "gpl": "ультрахаосдропов", "apl": "ультрахаосдропы", "pron": "его", "pass": False},
    {"id": "pass", "acc": "Бравл Пасс", "gen": "Бравл Пасс", "ins": "Бравл Пасс", "few": "Бравл Пасс",
     "gpl": "Бравл Пасс", "apl": "Бравл Пасс", "pron": "его", "pass": True},
    {"id": "plus", "acc": "Бравл Пасс Плюс", "gen": "Бравл Пасс Плюс", "ins": "Бравл Пасс Плюс", "few": "Бравл Пасс Плюс",
     "gpl": "Бравл Пасс Плюс", "apl": "Бравл Пасс Плюс", "pron": "его", "pass": True},
]


def V(s, pair):
    return pair[0] if s["pl"] else pair[1]


def action(rng, s, allow_raz=True):
    pool = list(ACT)
    if allow_raz and rng.random() < 0.035:
        pool = list(ACT_RARE)
    pair, case = rng.choice(pool)
    return V(s, pair), case


def rw(reward, case="acc", rng=None, qty=None, style=0):
    """Render reward phrase."""
    if reward["pass"]:
        return reward["acc"]
    rng = rng or random.Random(0)
    if qty is not None:
        if qty == 1:
            return f"один {reward['acc']}"
        if qty in (2, 3, 4):
            return f"{qty} {reward['few']}"
        return f"{qty} {reward['gpl']}"
    # style variants approved-ish
    if style == 1 and not reward["pass"]:
        # новый
        if case == "gen":
            return f"нового {reward['gen']}"
        return f"новый {reward['acc']}"
    if style == 2 and reward["id"] == "drop":
        if case == "gen":
            return f"дополнительного {reward['gen']}"
        return f"дополнительный {reward['acc']}"
    if style == 3 and not reward["pass"]:
        return f"сразу несколько {reward['gpl']}" if case == "acc" else reward["gpl"]
    if case == "gen":
        return reward["gen"]
    return reward["acc"]


def end(rng, reward, use_na):
    if use_na:
        return rng.choice(NA)
    return rng.choice([
        f"Вам остаётся лишь забрать {reward['pron']}!",
        "Сейчас покажу, как его забрать!",
        "Покажу нужный способ!",
        "Объясню весь способ!",
        "Расскажу, что делать!",
        "Покажу всё по порядку!",
        f"Я уже разобрался. Вам остаётся лишь забрать {reward['pron']}!",
        "Сейчас покажу всё вам!",
        "Показываю вам, скорее забирайте!",
    ])


def norm(t: str) -> str:
    t = t.replace("—", ",").replace("–", ",")
    t = " ".join(t.split())
    # word-order fixes for compound actions
    for a, b in [
        ("про получение новый ", "про получение "),
        ("про получение дополнительный ", "про получение "),
        ("с ультраящик!", "с ультраящиком!"),
        ("с ультрахаосдроп!", "с ультрахаосдропом!"),
        ("с новый ультраящик", "с ультраящиком"),
        ("с новый ультрахаосдроп", "с ультрахаосдропом"),
        ("дали возможность забрать игрокам ", "дали игрокам возможность забрать "),
        ("дала возможность забрать игрокам ", "дала игрокам возможность забрать "),
        ("дали возможность забрать каждому ", "дали каждому возможность забрать "),
        ("дала возможность забрать каждому ", "дала каждому возможность забрать "),
        ("начало выдавать для игроков ", "начала выдавать игрокам "),
        ("начали выдавать для игроков ", "начали выдавать игрокам "),
        ("начала выдавать для игроков ", "начала выдавать игрокам "),
        ("решили выдать для игроков ", "решили выдать игрокам "),
        ("решила выдать для игроков ", "решила выдать игрокам "),
        ("выдали для игроков ", "выдали игрокам "),
        ("выдала для игроков ", "выдала игрокам "),
        ("добавили для игроков ", "добавили игрокам "),
        ("добавила для игроков ", "добавила игрокам "),
        ("подготовили для игроков ", "подготовили игрокам "),
        ("подготовила для игроков ", "подготовила игрокам "),
        ("запустили выдачу для игроков ", "запустили выдачу "),
        ("запустила выдачу для игроков ", "запустила выдачу "),
    ]:
        t = t.replace(a, b)
    return t.strip()


def bad(t: str) -> bool:
    low = t.lower()
    return any(f in low for f in FORBIDDEN)


def has_raz(t: str) -> bool:
    low = t.lower()
    return any(x in low for x in ("раздач", "раздава", "раздают", "раздаёт"))


# ===================== TEMPLATES =====================
# Each returns text. Canonical length measured with fixed seed fill.

def T01(rng, s, r, use_na, allow_raz):
    # birthday / fighter day — user template 1
    act, case = action(rng, s, allow_raz)
    qty = None if r["pass"] else rng.choice([None, 5, 10, None])
    st = rng.choice([0, 0, 1])
    rr = rw(r, case, rng, qty=qty, style=st if qty is None else 0)
    lead = rng.choice([
        f"{s['nom']} {V(s, ('объявили', 'объявила'))} о новой акции!",
        f"{s['nom']} {rng.choice(RECENT_ADV)} {V(s, ('запустили', 'запустила'))} особую акцию!",
        f"{s['nom']} {rng.choice(AGAIN)} {V(s, ('порадовали', 'порадовала'))} игроков!",
    ])
    mid = rng.choice([
        f"Бравл Старс {V(s, ('запустили', 'запустила')) if False else 'запустили'} её в честь дня рождения одного из бойцов, {rng.choice(BUT)} далеко не все игроки успели забрать {rw(r, 'acc', rng, qty=qty or (5 if not r['pass'] else None), style=0) if not r['pass'] else r['acc']}.",
        f"В честь дня рождения бойца игрокам {act} {rr}, {rng.choice(BUT)} {rng.choice(FEW)}.",
        f"Повод простой: день рождения бойца. Игрокам {act} {rr}, {rng.choice(BUT)} {rng.choice(FEW)}.",
    ])
    # fix first mid branch - don't use broken V
    mid = rng.choice([
        f"Бравл Старс запустили её в честь дня рождения одного из бойцов, {rng.choice(BUT)} далеко не все игроки успели забрать {rw(r,'acc',rng, qty=(5 if not r['pass'] else None)) if not r['pass'] else r['acc']}.",
        f"В честь дня рождения бойца игрокам {act} {rr}, {rng.choice(BUT)} {rng.choice(FEW)}.",
        f"Повод простой: день рождения бойца. Игрокам {act} {rr}, {rng.choice(BUT)} {rng.choice(FEW)}.",
    ])
    if use_na:
        tail = rng.choice([
            "Если вы тоже всё пропустили, то награда уже найдена, вам остаётся лишь забрать её!",
            f"Я уже всё нашёл. {rng.choice(NA)}",
        ])
    else:
        tail = end(rng, r, False)
    return f"{lead} {mid} {tail}"


def T02(rng, s, r, use_na, allow_raz):
    # bloggers confirmed — user template 2
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        f"{s['nom']} {V(s, ('начали выдавать', 'начала выдавать'))} {rw(r,'acc',rng)}!",
        f"{s['nom']} {act} {rr}!",
        f"{s['nom']} {rng.choice(AGAIN)} {act} {rr}!",
    ])
    mid = rng.choice([
        "Об этом почти никто не слышал, хотя информацию уже подтвердили многие блогеры по Бравл Старс.",
        "Об этом мало кто слышал, хотя блогеры по Бравл Старс уже всё подтвердили.",
        "Новость тихая, но блогеры по Бравл Старс уже проверили информацию.",
    ])
    if use_na:
        return f"{lead} {mid} Я самостоятельно разобрался во всём. {rng.choice(NA)}"
    return f"{lead} {mid} Я самостоятельно разобрался во всём и нашёл нужный способ получения. Показываю вам, скорее забирайте!"


def T03(rng, s, r, use_na, allow_raz):
    # lost among publications — user template 3
    if r["pass"]:
        get = r["acc"]
    else:
        get = rw(r, "acc", rng, qty=rng.choice([5, 10, None]), style=rng.choice([0, 1, 3]))
        if get.startswith("сразу"):
            pass
        elif " " not in get or get.split()[0] in ("новый", "дополнительный", "один"):
            pass
        else:
            # ensure readable
            get = get
    lead = rng.choice([
        f"{s['nom']} {rng.choice(AGAIN_DID)} порадовать игроков!" if s["pl"] else f"{s['nom']} {rng.choice(['снова решила','вновь решила'])} порадовать игроков!",
        f"{s['nom']} {rng.choice(AGAIN)} {V(s, ('подготовили', 'подготовила'))} кое-что для игроков!",
        f"{s['nom']} {rng.choice(AGAIN)} {V(s, ('сделали', 'сделала'))} приятное для игроков!",
    ])
    mid = rng.choice([
        f"На этот раз в Бравл Старс можно получить {get}, {rng.choice(BUT)} информация об этом затерялась среди новых публикаций.",
        f"В Бравл Старс можно забрать {get}, {rng.choice(BUT)} детали затерялись среди свежих новостей.",
        f"Игрокам доступен {rw(r,'acc',rng, style=rng.choice([0,1]))}, {rng.choice(BUT)} почти все пролистали свежую публикацию.",
    ])
    if use_na:
        return f"{lead} {mid} Я уже нашёл всё необходимое. {rng.choice(NA)}"
    return f"{lead} {mid} Я уже нашёл всё необходимое. Вам остаётся лишь забрать {r['pron']}!"


def T04(rng, s, r, use_na, allow_raz):
    # recently said everyone can get — user template 4
    rr = rw(r, "acc", rng, style=rng.choice([0, 1]))
    recent = rng.choice(RECENT_ADV)
    lead = rng.choice([
        f"Бравл Старс {rng.choice(AGAIN)} удивляют игроков!",
        f"Бравл Старс {rng.choice(AGAIN)} радуют сообщество!",
        f"{s['nom']} {rng.choice(AGAIN)} {V(s, ('удивили', 'удивила'))} игроков!",
    ])
    mid = rng.choice([
        f"{recent.capitalize()} {s['low']} {V(s, ('сообщили', 'сообщила'))}, что каждый сможет получить {rr}.",
        f"{s['nom']} {recent} {V(s, ('сообщили', 'сообщила'))}: игрокам доступен {rr}.",
        f"{rng.choice(RECENT_OPEN)}, что каждый игрок сможет {rng.choice(['получить','забрать','активировать','успеть забрать'])} {rr}.",
    ])
    mid2 = rng.choice([
        f"Большинство ещё ничего не знает об этом, {rng.choice(BUT)} я уже самостоятельно во всём разобрался.",
        f"{rng.choice(FEW).capitalize()}, {rng.choice(BUT)} я уже всё проверил.",
        f"Пока об этом знают единицы, {rng.choice(BUT)} я уже нашёл способ получения.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T05(rng, s, r, use_na, allow_raz):
    # hidden in publication — user template 5
    rr = rw(r, "acc", rng, style=rng.choice([0, 1]))
    recent = rng.choice(RECENT_ADV)
    lead = rng.choice([
        f"{s['nom']} {V(s, ('сообщили', 'сообщила'))} игрокам о новой акции!",
        f"{s['nom']} {recent} {V(s, ('опубликовали', 'опубликовала'))} важную запись!",
        f"{recent.capitalize()} {s['low']} {V(s, ('оставили', 'оставила'))} важную деталь для игроков!",
    ])
    mid = rng.choice([
        f"Недавно Бравл Старс опубликовали запись, в которой спрятали способ получения {rr}.",
        f"В свежей публикации спрятали способ получения {rr}.",
        f"Среди обычных деталей публикации спрятали {rr}.",
    ])
    mid2 = rng.choice([
        f"Почти никто этого не заметил, {rng.choice(BUT)} я уже всё нашёл.",
        f"{rng.choice(FEW).capitalize()}, {rng.choice(BUT)} я уже разобрался.",
        f"Большинство прошло мимо, {rng.choice(BUT)} я внимательно всё изучил.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T06(rng, s, r, use_na, allow_raz):
    # fresh publication — user template 6
    rr = rw(r, "acc", rng, style=rng.choice([0, 1]))
    src = rng.choice([
        "в свежей публикации", "в свежем посте", "в сообщении", "в новости",
        "в официальной записи", "в объявлении",
    ])
    lead = rng.choice([
        f"Бравл Старс {rng.choice(AGAIN)} радуют своих игроков!",
        f"Бравл Старс {rng.choice(AGAIN)} делятся приятным с игроками!",
        f"{s['nom']} {rng.choice(AGAIN)} {V(s, ('радуют', 'радует'))} игроков!",
    ])
    mid = rng.choice([
        f"{s['nom']} {V(s, ('разместили', 'разместила'))} свежую публикацию про получение {r['gen']}, {rng.choice(BUT)} большинство пользователей прошло мимо неё.",
        f"{src.capitalize()} появилась возможность получить {rw(r,'acc',rng)}, {rng.choice(BUT)} многие пролистали её.",
        f"{s['nom']} {V(s, ('опубликовали', 'опубликовала'))} новость про {rr}, {rng.choice(BUT)} большинство прошло мимо.",
    ])
    if use_na:
        return f"{lead} {mid} Я внимательно всё изучил. {rng.choice(NA)}"
    return f"{lead} {mid} Я внимательно всё изучил и нашёл способ получения. Вам остаётся лишь забрать {r['pron']}!"


def T07(rng, s, r, use_na, allow_raz):
    # secret in publication — approved new
    rr = rw(r, "acc", rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        f"Бравл Старс {rng.choice(AGAIN)} оставили секрет в свежей публикации!",
        f"{s['nom']} {V(s, ('оставили', 'оставила'))} важную деталь в свежей публикации по Бравл Старс!",
        f"В свежей публикации по Бравл Старс спрятали кое-что ценное!",
    ])
    mid = rng.choice([
        f"Среди обычных деталей {s['low']} {V(s, ('спрятали', 'спрятала'))} {rr}, {rng.choice(BUT)} большинство игроков прошло мимо.",
        f"Там спрятали {rr}, {rng.choice(BUT)} {rng.choice(FEW)}.",
        f"{s['nom']} {V(s, ('спрятали', 'спрятала'))} {rr} среди обычных деталей, {rng.choice(BUT)} почти никто не обратил внимания.",
    ])
    if use_na:
        return f"{lead} {mid} Я уже нашёл нужную подсказку. {rng.choice(NA)}"
    return f"{lead} {mid} Я уже нашёл нужную подсказку и понял, как его получить. Сейчас покажу всё вам!"


def T08(rng, s, r, use_na, allow_raz):
    # tech break end
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        f"{s['nom']} {V(s, ('завершили', 'завершила'))} технический перерыв в Бравл Старс!",
        f"Бравл Старс {rng.choice(AGAIN)} стали доступны после технического перерыва!",
        f"Технический перерыв в Бравл Старс завершён!",
    ])
    mid = rng.choice([
        f"После возвращения в игру появился {ra}, хотя отдельно о нём нигде не сообщали.",
        f"Вместе с запуском {s['low']} {V(s, ('добавили', 'добавила'))} {ra}, {rng.choice(BUT)} не {V(s, ('стали', 'стала'))} рассказывать о нём отдельно.",
        f"После возвращения {s['low']} {act} игрокам {rr}, {rng.choice(BUT)} отдельно об этом почти не писали.",
    ])
    mid2 = rng.choice([
        f"Многие игроки этого не заметили, {rng.choice(BUT)} я уже всё проверил.",
        f"Поэтому многие игроки прошли мимо. Я уже разобрался.",
        f"{rng.choice(FEW).capitalize()}, {rng.choice(BUT)} я уже во всём разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T09(rng, s, r, use_na, allow_raz):
    # community event early
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    lead = rng.choice([
        "Игроки Бравл Старс завершили общее событие раньше срока!",
        "Сообщество Бравл Старс выполнило общую цель раньше срока!",
        "Игроки Бравл Старс добрались до финальной цели общего события!",
    ])
    mid = rng.choice([
        f"После достижения финальной цели {s['low']} {act} {rr} для всех участников.",
        f"За завершение события {s['low']} {act} участникам {ra}.",
        f"После этого {s['low']} {act} {rr}, {rng.choice(BUT)} многие уже перестали следить за результатами.",
    ])
    mid2 = rng.choice([
        f"Многие решили, что получить его уже нельзя, {rng.choice(BUT)} я всё проверил.",
        f"Многие игроки не знали, что его уже можно получить, {rng.choice(BUT)} я всё проверил.",
        "Я вовремя всё заметил и разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T10(rng, s, r, use_na, allow_raz):
    # stream
    ra = rw(r, "acc", rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        f"{s['nom']} {V(s, ('провели', 'провела'))} новую трансляцию по Бравл Старс!",
        "Бравл Старс показали новую трансляцию для игроков!",
        f"{s['nom']} {V(s, ('провели', 'провела'))} свежую трансляцию по Бравл Старс!",
    ])
    mid = rng.choice([
        f"В самом конце они неожиданно сообщили, что игрокам доступен {ra}.",
        f"Перед завершением эфира они объявили, что игрокам решили выдать {ra}.",
        f"Почти в самом конце {s['low']} {V(s, ('сообщили', 'сообщила'))} о том, что можно получить {ra}.",
    ])
    mid2 = rng.choice([
        f"Большинство не досмотрело эфир до этого момента, {rng.choice(BUT)} я уже нашёл способ получения.",
        f"Большинство зрителей уже ушло и пропустило эту новость, {rng.choice(BUT)} я всё запомнил.",
        "Многие не стали досматривать эфир. Я увидел объявление и уже понял, что нужно сделать.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T11(rng, s, r, use_na, allow_raz):
    # voting
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        "Бравл Старс подвели итоги недавнего голосования среди игроков!",
        f"{s['nom']} {V(s, ('опубликовали', 'опубликовала'))} результаты недавнего опроса по Бравл Старс!",
        "Бравл Старс подвели итоги голосования среди игроков!",
    ])
    mid = rng.choice([
        f"Вместе с результатами {s['low']} {act} {rr}, {rng.choice(BUT)} отдельно о нём не сообщили.",
        f"В честь завершения голосования {s['low']} {act} игрокам {rr}.",
        f"Вместе с итогами {s['low']} {act} игрокам {rr}, {rng.choice(BUT)} отдельно об этом почти не рассказывали.",
    ])
    mid2 = rng.choice([
        "Эту деталь заметили далеко не все.",
        "Большинство заметило только победителя опроса.",
        "Многие прочитали только итоги и пропустили самое важное.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA)}"
    return f"{lead} {mid} {mid2} Я всё заметил и {rng.choice(SHOW).lower()}!"


def T12(rng, s, r, use_na, allow_raz):
    # tech glitch compensation
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    recent = rng.choice(RECENT_ADV)
    lead = rng.choice([
        f"В Бравл Старс {recent} произошёл технический сбой!",
        f"В Бравл Старс {recent} обнаружили техническую ошибку!",
        f"{s['nom']} {V(s, ('завершили', 'завершила'))} устранение сбоя в Бравл Старс!",
    ])
    mid = rng.choice([
        f"{s['nom']} {V(s, ('извинились', 'извинилась'))} перед игроками и {act} каждому {ra}.",
        f"{s['nom']} быстро {V(s, ('устранили', 'устранила'))} проблему и {act} игрокам {rr}.",
        f"В качестве компенсации {s['low']} {act} игрокам {rr}, {rng.choice(BUT)} отдельно об этом почти не сообщали.",
    ])
    mid2 = rng.choice([
        f"Многие подумали, что он появится автоматически, {rng.choice(BUT)} для получения нужно выполнить одно действие.",
        f"Многие уже вернулись в игру, {rng.choice(BUT)} не заметили сообщение о получении.",
        "Поэтому многие даже не проверили получение. Я уже во всём разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T13(rng, s, r, use_na, allow_raz):
    # new brawler
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    lead = rng.choice([
        f"{s['nom']} {V(s, ('представили', 'представила'))} нового бойца в Бравл Старс!",
        "Бравл Старс официально представили нового бойца!",
        f"{s['nom']} {V(s, ('показали', 'показала'))} способности нового бойца Бравл Старс!",
    ])
    mid = rng.choice([
        f"В честь его появления игрокам {act} {rr}, {rng.choice(BUT)} об этом упомянули только в конце публикации.",
        f"В честь его выхода {s['low']} {act} для игроков {ra}. Информацию добавили в конец публикации.",
        f"Вместе с его презентацией игрокам {act} {rr}, {rng.choice(BUT)} об этом сказали всего одной фразой.",
    ])
    # subjectless "игрокам {act}" with singular is bad — force include subject when not pl by rewriting:
    if not s["pl"]:
        mid = rng.choice([
            f"В честь его появления {s['low']} {act} игрокам {rr}, {rng.choice(BUT)} об этом упомянули только в конце публикации.",
            f"В честь его выхода {s['low']} {act} для игроков {ra}. Информацию добавили в конец публикации.",
            f"Вместе с его презентацией {s['low']} {act} игрокам {rr}, {rng.choice(BUT)} об этом сказали всего одной фразой.",
        ])
    mid2 = rng.choice([
        "Большинство не дочитало запись до конца.",
        "Поэтому большинство прошло мимо.",
        "Мало кто обратил на неё внимание.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} Я всё заметил. {rng.choice(NA)}"
    return f"{lead} {mid} {mid2} Я всё заметил и сейчас покажу, как его получить!"


def T14(rng, s, r, use_na, allow_raz):
    # record
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    lead = rng.choice([
        "Бравл Старс достигли нового рекорда благодаря своим игрокам!",
        "Сообщество Бравл Старс установило новый общий рекорд!",
        "Бравл Старс достигли новой высоты благодаря активности игроков!",
    ])
    mid = rng.choice([
        f"{s['nom']} {V(s, ('решили', 'решила'))} отметить это событие и выдать {ra}.",
        f"{s['nom']} {V(s, ('поблагодарили', 'поблагодарила'))} игроков и {act} {rr} в честь этого результата.",
        f"{s['nom']} {V(s, ('решили', 'решила'))} отметить этот результат и выдать {ra} всему сообществу.",
    ])
    mid2 = rng.choice([
        f"Новость появилась {rng.choice(RECENT_ADV)}, поэтому о ней знают ещё не все.",
        f"Новость быстро затерялась среди других публикаций, {rng.choice(BUT)} я её нашёл.",
        "Многие не увидели сообщение и ничего не получили. Я уже проверил информацию.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T15(rng, s, r, use_na, allow_raz):
    # challenge
    ra = rw(r, "acc", rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        f"В Бравл Старс появилось новое испытание с {r['ins']}!",
        f"{s['nom']} {V(s, ('добавили', 'добавила'))} новое испытание в Бравл Старс!",
        f"В Бравл Старс запустили короткое испытание с {r['ins']}!",
    ])
    mid = rng.choice([
        "Для его получения нужно выполнить простое условие, которое многие игроки не заметили.",
        f"За выполнение простого условия каждый игрок сможет получить {ra}. Большинство сразу начало играть и не прочитало главное правило.",
        "Получить его можно после выполнения одного условия, которое указали в конце описания.",
    ])
    mid2 = rng.choice([
        "Я уже завершил испытание и проверил результат.",
        "Я уже завершил всё сам.",
        "Многие игроки его не заметили. Я уже всё выполнил.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA)}"
    return f"{lead} {mid} {mid2} Сейчас расскажу, что именно нужно сделать!"


def T16(rng, s, r, use_na, allow_raz):
    # championship
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    lead = rng.choice([
        f"{s['nom']} {V(s, ('подвели', 'подвела'))} итоги чемпионата по Бравл Старс!",
        "Завершился очередной чемпионат по Бравл Старс!",
        f"{s['nom']} {V(s, ('опубликовали', 'опубликовала'))} результаты чемпионата по Бравл Старс!",
    ])
    mid = rng.choice([
        f"После завершения финала {s['low']} {act} участникам события {rr}, {rng.choice(BUT)} многие забыли проверить результат.",
        f"После финального матча {s['low']} {act} участникам события {ra}.",
        f"Игрокам, следившим за финальными матчами, {s['low']} {act} {rr}.",
    ])
    mid2 = rng.choice([
        "Я уже нашёл всё необходимое.",
        "Многие посмотрели результаты и сразу закрыли публикацию, пропустив главное.",
        f"Не все поняли, где его нужно получить, {rng.choice(BUT)} я уже разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T17(rng, s, r, use_na, allow_raz):
    # new season
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        "В Бравл Старс стартовал новый сезон!",
        "Бравл Старс представили новый сезон для игроков!",
        f"{s['nom']} {V(s, ('объявили', 'объявила'))} о начале нового сезона Бравл Старс!",
    ])
    mid = rng.choice([
        f"Вместе с ним {s['low']} {act} {rr} для всех игроков, {rng.choice(BUT)} условие получения указали только в конце анонса.",
        f"Вместе с его запуском {s['low']} {act} {rr}, {rng.choice(BUT)} условие получения спрятали в конце публикации.",
        f"Помимо новинок сезона {s['low']} {act} игрокам {rr}. Об этом коротко упомянули в конце анонса.",
    ])
    mid2 = rng.choice([
        "Многие прочитали лишь основную часть и прошли мимо.",
        "Большинство прочитало только основные новости.",
        "Поэтому многие ничего не заметили.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA)}"
    return f"{lead} {mid} {mid2} Я уже всё нашёл и покажу, как его получить!"


def T18(rng, s, r, use_na, allow_raz):
    # collab
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    lead = rng.choice([
        f"{s['nom']} {V(s, ('объявили', 'объявила'))} о новой коллаборации в Бравл Старс!",
        "Бравл Старс официально объявили о новой коллаборации!",
        f"{s['nom']} {V(s, ('представили', 'представила'))} новую коллаборацию в Бравл Старс!",
    ])
    if rng.random() < 0.05:
        mid = f"В честь её запуска {s['low']} {act} игрокам {rr}. Главное условие показали только на втором изображении, поэтому большинство его не заметило."
    else:
        mid = rng.choice([
            f"В честь её запуска {s['low']} {act} игрокам {rr}. Главное условие спрятали в конце публикации, поэтому большинство его не заметило.",
            f"Вместе с её запуском {s['low']} {act} для игроков {ra}. Условие получения показали только в конце, поэтому его почти никто не заметил.",
            f"Помимо тематических обликов {s['low']} {act} игрокам {rr}. Главную информацию спрятали среди деталей публикации.",
        ])
    mid2 = rng.choice(["Я уже всё нашёл.", "Я всё заметил.", "Многие прошли мимо. Я уже всё нашёл."])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T19(rng, s, r, use_na, allow_raz):
    # trophy path
    ra = rw(r, "acc", rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        "Бравл Старс расширили трофейный путь для игроков!",
        f"{s['nom']} {V(s, ('обновили', 'обновила'))} трофейный путь в Бравл Старс!",
        "Бравл Старс расширили трофейный путь для всех игроков!",
    ])
    mid = rng.choice([
        f"За достижение нового рубежа {s['low']} {V(s, ('добавили', 'добавила'))} {ra}, {rng.choice(BUT)} упомянули об этом всего одной строкой.",
        f"За достижение одного из новых рубежей игроки смогут получить {ra}. Об этом упомянули только в конце описания.",
        f"Среди новых рубежей {s['low']} {V(s, ('разместили', 'разместила'))} {ra}, {rng.choice(BUT)} отдельно о нём не рассказали.",
    ])
    mid2 = rng.choice([
        f"Многие прошли мимо этой информации, {rng.choice(BUT)} я всё проверил.",
        "Поэтому почти никто не обратил внимания.",
        "Многие уже достигли нужного количества трофеев и прошли мимо. Я всё проверил.",
    ])
    return f"{lead} {mid} {mid2} {end(rng, r, use_na)}"


def T20(rng, s, r, use_na, allow_raz):
    # mode return
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    lead = rng.choice([
        f"{s['nom']} {V(s, ('вернули', 'вернула'))} популярный режим в Бравл Старс!",
        f"В Бравл Старс {rng.choice(AGAIN)} появился популярный режим!",
        f"{s['nom']} {V(s, ('вернули', 'вернула'))} один из старых режимов Бравл Старс!",
    ])
    mid = rng.choice([
        f"В честь его возвращения {s['low']} {act} каждому игроку {rr} после одного завершённого боя.",
        f"За первый завершённый бой {s['low']} {act} игрокам {rr}. Условие указали короткой фразой в публикации.",
        f"В честь его возвращения {s['low']} {act} {rr} для каждого участника. Чтобы получить его, достаточно завершить один бой.",
    ])
    mid2 = rng.choice([
        "Об этом упомянули совсем коротко, поэтому многие ничего не заметили.",
        "Поэтому его заметили далеко не все.",
        "Об этом знают ещё не все.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA)}"
    return f"{lead} {mid} {mid2} Я уже всё проверил и сейчас покажу вам!"


def T21(rng, s, r, use_na, allow_raz):
    # rare calendar/changes
    act, case = action(rng, s, allow_raz)
    rr = rw(r, case, rng, style=rng.choice([0, 1]))
    ra = rw(r, "acc", rng)
    lead = rng.choice([
        f"{s['nom']} {V(s, ('внесли', 'внесла'))} свежие изменения в Бравл Старс!",
        "В календаре событий Бравл Старс появилось кое-что важное!",
        "Бравл Старс обновили календарь событий!",
    ])
    mid = rng.choice([
        f"Вместе с изменениями {s['low']} {act} игрокам {rr}, {rng.choice(BUT)} отдельно об этом почти не писали.",
        f"Среди пунктов календаря спрятали {ra}, {rng.choice(BUT)} большинство игроков прошло мимо.",
        f"После обновления календаря стал доступен {ra}, {rng.choice(BUT)} {rng.choice(FEW)}.",
    ])
    if use_na:
        return f"{lead} {mid} Я всё проверил. {rng.choice(NA)}"
    return f"{lead} {mid} Я всё проверил и покажу нужный способ!"


TEMPLATES = [T01, T02, T03, T04, T05, T06, T07, T08, T09, T10,
             T11, T12, T13, T14, T15, T16, T17, T18, T19, T20]


USER_CANON_LEN = {
    0: 247,
    1: 242,
    2: 251,
    3: 241,
    4: 242,
    5: 244,
    6: 229,
    7: 250,
    8: 260,
    9: 244,
    10: 230,
    11: 272,
    12: 248,
    13: 241,
    14: 231,
    15: 247,
    16: 259,
    17: 257,
    18: 265,
    19: 267,
    20: 205,
}

def measure_canonical(tid: int, builder) -> int:
    return USER_CANON_LEN[tid]


def in_band(n: int, canon: int) -> bool:
    lo = int(canon * 0.90)
    hi = int(canon * 1.10)
    return lo <= n <= hi


def order_diverse(items):
    buckets = defaultdict(deque)
    for it in items:
        buckets[(it[0], it[1])].append(it)
    ordered = []
    last_r, last_t, last_s = -1, -1, -1
    rnd = random.Random(SEED)
    while buckets:
        avail = [k for k, q in buckets.items() if q]
        if not avail:
            break
        cand = avail if len(avail) <= 100 else rnd.sample(avail, 100)
        best, best_sc = None, -10**9
        for k in cand:
            it = buckets[k][0]
            sc = 0
            if it[0] != last_r:
                sc += 50
            if it[1] != last_t:
                sc += 30
            if it[2] != last_s:
                sc += 15
            sc += min(len(buckets[k]), 5)
            sc += rnd.random()
            if sc > best_sc:
                best_sc, best = sc, k
        it = buckets[best].popleft()
        if not buckets[best]:
            del buckets[best]
        ordered.append(it)
        last_r, last_t, last_s = it[0], it[1], it[2]
    return ordered


def main():
    print("Measuring canonical lengths per template...", flush=True)
    canons = {}
    for tid, b in enumerate(TEMPLATES):
        canons[tid] = measure_canonical(tid, b)
        lo, hi = int(canons[tid] * 0.9), int(canons[tid] * 1.1)
        print(f"  T{tid+1:02d}: canon={canons[tid]} band=[{lo}..{hi}]", flush=True)
    canons[20] = measure_canonical(20, T21)
    print(f"  T21: canon={canons[20]} band=[{int(canons[20]*0.9)}..{int(canons[20]*1.1)}]", flush=True)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    seen = set()
    texts = []
    per = TARGET // 4
    counts = [0, 0, 0, 0]
    raz_n = 0
    cal_n = 0
    base = random.Random(SEED)
    attempts = 0
    limit = TARGET * 200
    rejected_len = 0

    while sum(counts) < TARGET and attempts < limit:
        attempts += 1
        ri = min(range(4), key=lambda i: (counts[i], base.random()))
        if counts[ri] >= per:
            if all(c >= per for c in counts):
                break
            continue
        reward = REWARDS[ri]
        use_cal = cal_n < TARGET // 20 and base.random() < 0.05
        if use_cal:
            tid, builder = 20, T21
        else:
            tid = base.randrange(len(TEMPLATES))
            builder = TEMPLATES[tid]
        si = base.randrange(len(SUBJ))
        subj = SUBJ[si]
        use_na = base.random() < 0.50
        allow_raz = raz_n < TARGET // 25
        rng = random.Random(base.randint(1, 2**31 - 1))
        text = norm(builder(rng, subj, reward, use_na, allow_raz))
        if bad(text):
            continue
        if reward["acc"] not in text:
            continue
        if not in_band(len(text), canons[tid]):
            rejected_len += 1
            continue
        if has_raz(text) and not allow_raz:
            continue
        if ("календар" in text.lower() or (tid == 20)) and cal_n >= TARGET // 20:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if has_raz(text):
            raz_n += 1
        if tid == 20 or "календар" in text.lower():
            cal_n += 1
        texts.append((ri, tid, si, text))
        counts[ri] += 1
        if sum(counts) % 10000 == 0:
            print(f"gen {sum(counts)} attempts={attempts} rej_len={rejected_len}", flush=True)

    print(f"phase1 {len(texts)} counts={counts} raz={raz_n} cal={cal_n} rej_len={rejected_len}", flush=True)

    # Aggressive fill with more attempts per remaining
    fill = 0
    while len(texts) < TARGET and fill < limit * 2:
        fill += 1
        ri = min(range(4), key=lambda i: counts[i])
        reward = REWARDS[ri]
        tid = fill % len(TEMPLATES)
        builder = TEMPLATES[tid]
        si = (fill * 7) % len(SUBJ)
        use_na = (fill % 2 == 0)
        rng = random.Random(50_000_000 + fill)
        text = norm(builder(rng, SUBJ[si], reward, use_na, False))
        if bad(text) or reward["acc"] not in text:
            continue
        if not in_band(len(text), canons[tid]):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        texts.append((ri, tid, si, text))
        counts[ri] += 1
        if len(texts) % 10000 == 0:
            print(f"fill {len(texts)}", flush=True)

    if len(texts) < TARGET:
        print(f"WARNING only {len(texts)} texts, widening fill with synonym micro-edits", flush=True)
        # last resort: take existing and do safe synonym swaps of similar length
        extras = []
        src = list(texts)
        fi = 0
        while len(texts) + len(extras) < TARGET and fi < len(src) * 30:
            fi += 1
            it = src[fi % len(src)]
            t = it[3]
            swaps = [
                ("но ", "однако "), ("однако ", "при этом "), ("при этом ", "вот только "),
                ("вот только ", "но "), ("снова ", "вновь "), ("вновь ", "опять "),
                ("опять ", "в очередной раз "), ("недавно ", "на днях "),
                ("на днях ", "совсем недавно "), ("Сейчас покажу", "Покажу нужный способ"),
                ("Покажу нужный способ", "Объясню весь способ"),
            ]
            a, b = swaps[fi % len(swaps)]
            if a not in t:
                continue
            nt = norm(t.replace(a, b, 1))
            # keep same template band
            if not in_band(len(nt), canons[it[1]]):
                continue
            if bad(nt) or nt.lower() in seen:
                continue
            if REWARDS[it[0]]["acc"] not in nt:
                continue
            seen.add(nt.lower())
            extras.append((it[0], it[1], it[2], nt))
        texts.extend(extras)
        # recount
        counts = [0, 0, 0, 0]
        for it in texts:
            counts[it[0]] += 1
        print(f"after extras {len(texts)} counts={counts}", flush=True)

    # Balance rewards if uneven after extras
    texts = texts[:TARGET]
    # If still short, fail loudly
    if len(texts) < TARGET:
        raise SystemExit(f"Failed to reach {TARGET}, got {len(texts)}")

    # Ensure equal rewards by trimming overflow from overfull and... we generated equal ideally
    by_r = [[] for _ in range(4)]
    for it in texts:
        by_r[it[0]].append(it)
    # rebalance
    final = []
    for ri in range(4):
        final.extend(by_r[ri][:per])
    # if some short, take from others that might have more - shouldn't happen
    while len(final) < TARGET:
        for ri in range(4):
            if len(by_r[ri]) > per:
                # already took per
                pass
        break
    if len(final) < TARGET:
        # use remaining from any
        used = set(id(x) for x in final)
        for it in texts:
            if len(final) >= TARGET:
                break
            if id(it) not in used:
                final.append(it)
    texts = final[:TARGET]

    random.Random(SEED + 1).shuffle(texts)
    print("ordering...", flush=True)
    ordered = order_diverse(texts)

    # Verify ALL lengths in band
    bad_len = sum(1 for it in ordered if not in_band(len(it[3]), canons[it[1]]))
    print(f"ordered={len(ordered)} out_of_band={bad_len}", flush=True)
    if bad_len:
        # drop and shouldn't happen
        ordered = [it for it in ordered if in_band(len(it[3]), canons[it[1]])]
        raise SystemExit(f"length band failed: kept {len(ordered)}")

    same_t = sum(1 for a, b in zip(ordered, ordered[1:]) if a[1] == b[1])
    same_r = sum(1 for a, b in zip(ordered, ordered[1:]) if a[0] == b[0])
    lens = [len(x[3]) for x in ordered]
    print(f"adj same_t={same_t} same_r={same_r} len {min(lens)}/{sum(lens)//len(lens)}/{max(lens)}")

    print("writing...", flush=True)
    for i, it in enumerate(ordered, 1):
        (OUT_DIR / f"{i:06d}.txt").write_text(it[3] + "\n", encoding="utf-8")

    print("zipping...", flush=True)
    for p in (ZIP_ART, ZIP_REPO):
        if p.exists():
            p.unlink()
    with zipfile.ZipFile(ZIP_ART, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i in range(1, len(ordered) + 1):
            zf.write(OUT_DIR / f"{i:06d}.txt", arcname=f"{i:06d}.txt")
    shutil.copy2(ZIP_ART, ZIP_REPO)

    # final report
    na = sum(1 for it in ordered if "награда" in it[3].lower())
    print(f"DONE files={len(ordered)} zip={ZIP_ART.stat().st_size} na={na} unique={len(set(x[3] for x in ordered))}")
    # per-template compliance sample
    for tid in range(21):
        subset = [len(it[3]) for it in ordered if it[1] == tid]
        if not subset:
            continue
        c = canons[tid]
        ok = sum(1 for n in subset if in_band(n, c))
        print(f"  T{tid+1:02d}: n={len(subset)} ok={ok}/{len(subset)} canon={c} actual[{min(subset)}..{max(subset)}]")


if __name__ == "__main__":
    main()
