#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate 100000 unique Brawl Stars promo captions per chat-learned rules."""

from __future__ import annotations

import hashlib
import random
import shutil
import zipfile
from collections import defaultdict, deque
from pathlib import Path

OUT_DIR = Path("/tmp/brawl_txt_100k")
ZIP_PATH = Path("/opt/cursor/artifacts/brawl_stars_texts_100000.zip")
REPO_ZIP = Path("/workspace/brawl_stars_texts_100000.zip")
TARGET = 100_000

FORBIDDEN_SUB = [
    "qr",
    "подарок",
    "подарки",
    "подарка",
    "подарков",
    "подароч",
    "бесплатн",
    "—",
    "–",
    "отметк",
    "раздел",
    "список изменений",
    "списке изменений",
]

REWARDS = [
    {
        "key": "box",
        "nom": "ультраящик",
        "acc": "ультраящик",
        "gen": "ультраящика",
        "gen_plur": "ультраящиков",
        "acc_plur": "ультраящики",
        "few": "ультраящика",
        "pron": "его",
        "pass": False,
    },
    {
        "key": "drop",
        "nom": "ультрахаосдроп",
        "acc": "ультрахаосдроп",
        "gen": "ультрахаосдропа",
        "gen_plur": "ультрахаосдропов",
        "acc_plur": "ультрахаосдропы",
        "few": "ультрахаосдропа",
        "pron": "его",
        "pass": False,
    },
    {
        "key": "pass",
        "nom": "Бравл Пасс",
        "acc": "Бравл Пасс",
        "gen": "Бравл Пасс",
        "gen_plur": "Бравл Пасс",
        "acc_plur": "Бравл Пасс",
        "few": "Бравл Пасс",
        "pron": "его",
        "pass": True,
    },
    {
        "key": "passplus",
        "nom": "Бравл Пасс Плюс",
        "acc": "Бравл Пасс Плюс",
        "gen": "Бравл Пасс Плюс",
        "gen_plur": "Бравл Пасс Плюс",
        "acc_plur": "Бравл Пасс Плюс",
        "few": "Бравл Пасс Плюс",
        "pron": "его",
        "pass": True,
    },
]

# Subjects: plural vs feminine singular (team)
SUBJECTS = [
    {"nom": "Разработчики", "low": "разработчики", "plural": True},
    {"nom": "Бравл Старс", "low": "Бравл Старс", "plural": True},
    {"nom": "Суперсэлл", "low": "Суперсэлл", "plural": True},
    {"nom": "Создатели Бравл Старс", "low": "создатели Бравл Старс", "plural": True},
    {"nom": "Команда Бравл Старс", "low": "команда Бравл Старс", "plural": False},
    {"nom": "Команда разработчиков", "low": "команда разработчиков", "plural": False},
]

RECENT_ADV = [
    "недавно",
    "совсем недавно",
    "не так давно",
    "на днях",
    "только что",
    "буквально только что",
]
RECENT_CLAUSE = [
    "Совсем недавно стало известно",
    "Недавно появилась информация",
]

AGAIN = ["снова", "вновь", "опять", "в очередной раз"]

BUT = ["но", "однако", "при этом", "вот только"]

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

NA_ENDS = [
    "Награда доступна, вам остаётся лишь забрать её!",
    "Награда найдена, вам остаётся лишь забрать её!",
    "Награда уже доступна, вам остаётся лишь забрать её!",
    "Награда ждёт, вам остаётся лишь забрать её!",
]

# Developer actions: (plural, singular), and whether object needs genitive
ACTIONS = [
    (("выдали", "выдала"), "acc"),
    (("добавили", "добавила"), "acc"),
    (("подготовили", "подготовила"), "acc"),
    (("решили выдать", "решила выдать"), "acc"),
    (("начали выдавать", "начала выдавать"), "acc"),
    (("дали возможность забрать", "дала возможность забрать"), "acc"),
    (("запустили выдачу", "запустила выдачу"), "gen"),
]

ACTIONS_RARE = [(("раздают", "раздаёт"), "acc")]

PLAYER = ["получить", "забрать", "активировать", "успеть забрать"]

SOURCES = [
    # (prep_phrase, noun_acc_short, gender adj for свежий)
    ("в свежей публикации", "публикация", "f"),
    ("в свежем посте", "пост", "m"),
    ("в сообщении", "сообщение", "n"),
    ("в новости", "новость", "f"),
    ("в ролике", "ролик", "m"),
    ("в объявлении", "объявление", "n"),
    ("в официальной записи", "официальная запись", "f"),
    ("в трансляции", "трансляция", "f"),
    ("в эфире", "эфир", "m"),
]


def v(subj: dict, pair: tuple[str, str]) -> str:
    return pair[0] if subj["plural"] else pair[1]


def pick_action(rng: random.Random, subj: dict, rare_ok: bool = True, force_plural: bool = False):
    pool = list(ACTIONS)
    if rare_ok and rng.random() < 0.04:
        pool = ACTIONS_RARE
    pair, case = rng.choice(pool)
    if force_plural:
        return pair[0], case
    return v(subj, pair), case


def reward_form(reward: dict, case: str, rng: random.Random, qty=None, mod=None) -> str:
    if reward["pass"]:
        return reward["acc"]
    if qty is not None:
        if qty == 1:
            return f"один {reward['acc']}"
        if qty in (2, 3, 4):
            return f"{qty} {reward['few']}"
        # 5+
        return f"{qty} {reward['gen_plur']}"
    if mod is None:
        if reward["key"] == "box":
            mod = rng.choice(["", "", "новый "])
        else:
            mod = rng.choice(["", "", "новый ", "дополнительный "])
    base = reward["gen"] if case == "gen" else reward["acc"]
    # "новый" agrees; for gen use нового
    if mod.startswith("новый"):
        mod = "нового " if case == "gen" else "новый "
    elif mod.startswith("дополнительный"):
        mod = "дополнительного " if case == "gen" else "дополнительный "
    if case == "gen" and qty is None and not mod:
        # запустили выдачу ультраящика
        return reward["gen"]
    if case == "gen":
        return f"{mod}{reward['gen']}".strip()
    return f"{mod}{base}".strip()


def few_notice(rng: random.Random) -> str:
    """Return a grammatical 'few noticed' clause."""
    choice = rng.randrange(10)
    if choice == 0:
        return "мало кто это заметил"
    if choice == 1:
        return "почти никто этого не заметил"
    if choice == 2:
        return "немногие это заметили"
    if choice == 3:
        return "далеко не все это заметили"
    if choice == 4:
        return "лишь некоторые игроки это заметили"
    if choice == 5:
        return "небольшая часть игроков это заметила"
    if choice == 6:
        return "большинство игроков этого не заметило"
    if choice == 7:
        return "многие игроки этого не заметили"
    if choice == 8:
        return "об этом знают единицы"
    return "информация дошла не до всех"


def end_block(rng: random.Random, reward: dict, use_na: bool) -> str:
    if use_na:
        return rng.choice(NA_ENDS)
    style = rng.randrange(5)
    if style == 0:
        return f"Вам остаётся лишь забрать {reward['pron']}!"
    if style == 1:
        return "Сейчас покажу, как его забрать!"
    if style == 2:
        return f"{rng.choice(SHOW)}!"
    if style == 3:
        return f"Я уже разобрался. Вам остаётся лишь забрать {reward['pron']}!"
    return f"Я уже всё проверил. Вам остаётся лишь забрать {reward['pron']}!"


def normalize(text: str) -> str:
    text = text.replace("—", ",").replace("–", ",")
    text = " ".join(text.split())
    text = text.replace(" ,", ",").replace("..", ".")
    # Fix subjectless singular verbs in mid-clauses
    repls = [
        ("игрокам запустила выдачу", "игрокам запустили выдачу"),
        ("игрокам начала выдавать", "игрокам начали выдавать"),
        ("игрокам начала выдавать", "игрокам начали выдавать"),
        ("игрокам выдала ", "игрокам выдали "),
        ("игрокам добавила ", "игрокам добавили "),
        ("игрокам подготовила ", "игрокам подготовили "),
        ("игрокам решила выдать", "игрокам решили выдать"),
        ("игрокам дала возможность забрать", "игрокам дали возможность забрать"),
        ("игрокам раздаёт ", "игрокам раздают "),
        (" радуют игроков Бравл Старс!", " радуют игроков!"),
        (" удивили игроков Бравл Старс!", " удивили игроков!"),
        (" удивила игроков Бравл Старс!", " удивила игроков!"),
        (" радует игроков Бравл Старс!", " радует игроков!"),
    ]
    for a, b in repls:
        text = text.replace(a, b)
    return text.strip()


def forbidden(text: str) -> bool:
    low = text.lower()
    for f in FORBIDDEN_SUB:
        if f in low:
            return True
    return False


def raz_count(text: str) -> int:
    low = text.lower()
    return sum(low.count(x) for x in ("раздач", "раздава", "раздают", "раздаёт"))


# -------------------- templates --------------------

def T01(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    qty = None if reward["pass"] else rng.choice([None, None, 5, 10])
    r = reward_form(reward, case, rng, qty=qty)
    lead = rng.choice([
        f"{subj['nom']} {v(subj, ('объявили', 'объявила'))} о новой акции!",
        f"{subj['nom']} {rng.choice(RECENT_ADV)} запустили особую акцию!" if subj["plural"] else f"{subj['nom']} {rng.choice(RECENT_ADV)} запустила особую акцию!",
        f"{subj['nom']} {rng.choice(AGAIN)} порадовали игроков!" if subj["plural"] else f"{subj['nom']} {rng.choice(AGAIN)} порадовала игроков!",
    ])
    mid = rng.choice([
        f"В честь дня рождения бойца игрокам {act} {r}, {rng.choice(BUT)} {few_notice(rng)}.",
        f"Бравл Старс отметили день рождения одного из бойцов, и игрокам {act} {r}, {rng.choice(BUT)} {few_notice(rng)}.",
        f"Повод простой: день рождения бойца. Игрокам {act} {r}, {rng.choice(BUT)} {few_notice(rng)}.",
    ])
    if use_na:
        bridge = rng.choice([
            "Если вы тоже всё пропустили, то награда уже найдена, вам остаётся лишь забрать её!",
            f"Я уже всё нашёл. {rng.choice(NA_ENDS)}",
        ])
        return f"{lead} {mid} {bridge}"
    return f"{lead} {mid} {end_block(rng, reward, False)}"


def T02(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    lead = rng.choice([
        f"{subj['nom']} {v(subj, ('начали выдавать', 'начала выдавать'))} {reward_form(reward, 'acc', rng)}!",
        f"{subj['nom']} {act} {r}!",
        f"{subj['nom']} {rng.choice(AGAIN)} {act} {r}!",
    ])
    mid = rng.choice([
        "Об этом почти никто не слышал, хотя информацию уже подтвердили многие блогеры по Бравл Старс.",
        "Об этом мало кто слышал, хотя блогеры по Бравл Старс уже всё подтвердили.",
        "Новость тихая, но блогеры по Бравл Старс уже проверили информацию.",
    ])
    if use_na:
        return f"{lead} {mid} Я самостоятельно разобрался во всём. {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} Я самостоятельно разобрался во всём и нашёл нужный способ получения. Показываю вам, скорее забирайте!"


def T03(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    if reward["pass"]:
        r = reward["acc"]
        r_get = reward["acc"]
    else:
        qty = rng.choice([5, 10, None])
        if qty:
            r_get = reward_form(reward, "acc", rng, qty=qty)
        else:
            r_get = rng.choice([
                reward["acc"],
                f"сразу несколько {reward['gen_plur']}",
                f"новый {reward['acc']}",
            ])
        r = r_get
    src = rng.choice(SOURCES)
    lead = rng.choice([
        f"{subj['nom']} вновь решили порадовать игроков!" if subj["plural"] else f"{subj['nom']} вновь решила порадовать игроков!",
        f"{subj['nom']} {rng.choice(AGAIN)} подготовили кое-что для игроков!" if subj["plural"] else f"{subj['nom']} {rng.choice(AGAIN)} подготовила кое-что для игроков!",
        f"{subj['nom']} {rng.choice(AGAIN)} сделали приятное для игроков!" if subj["plural"] else f"{subj['nom']} {rng.choice(AGAIN)} сделала приятное для игроков!",
    ])
    mid = rng.choice([
        f"На этот раз в Бравл Старс можно получить {r_get}, {rng.choice(BUT)} информация об этом затерялась среди новых публикаций.",
        f"В Бравл Старс можно забрать {r_get}, {rng.choice(BUT)} детали затерялись среди свежих новостей.",
        f"Игрокам доступен {reward_form(reward, 'acc', rng)}, {rng.choice(BUT)} почти все пролистали {src[0].replace('в ', '', 1)}.",
    ])
    # fix awkward "пролистали свежей публикации" - use noun
    mid = rng.choice([
        f"На этот раз в Бравл Старс можно получить {r_get}, {rng.choice(BUT)} информация об этом затерялась среди новых публикаций.",
        f"В Бравл Старс можно забрать {r_get}, {rng.choice(BUT)} детали затерялись среди свежих новостей.",
        f"Игрокам доступен {reward_form(reward, 'acc', rng)}, {rng.choice(BUT)} почти все пролистали свежую публикацию.",
    ])
    if use_na:
        return f"{lead} {mid} Я уже нашёл всё необходимое. {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} Я уже нашёл всё необходимое. Вам остаётся лишь забрать {reward['pron']}!"


def T04(rng, subj, reward, use_na):
    r = reward_form(reward, "acc", rng)
    recent = rng.choice(RECENT_ADV)
    lead = rng.choice([
        f"Бравл Старс {rng.choice(AGAIN)} удивляют игроков!",
        f"Бравл Старс {rng.choice(AGAIN)} радуют сообщество!",
        f"{subj['nom']} {rng.choice(AGAIN)} удивили игроков Бравл Старс!" if subj["plural"] else f"{subj['nom']} {rng.choice(AGAIN)} удивила игроков Бравл Старс!",
    ])
    mid = rng.choice([
        f"{recent.capitalize()} {subj['low']} {v(subj, ('сообщили', 'сообщила'))}, что каждый сможет получить {r}.",
        f"{subj['nom']} {recent} {v(subj, ('сообщили', 'сообщила'))}: игрокам доступен {r}.",
        f"{rng.choice(RECENT_CLAUSE)}, что каждый игрок сможет {rng.choice(PLAYER)} {r}.",
    ])
    mid2 = rng.choice([
        f"Большинство ещё ничего не знает об этом, {rng.choice(BUT)} я уже самостоятельно во всём разобрался.",
        f"{few_notice(rng).capitalize()}, {rng.choice(BUT)} я уже всё проверил.",
        f"Пока об этом знают единицы, {rng.choice(BUT)} я уже нашёл способ получения.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T05(rng, subj, reward, use_na):
    r = reward_form(reward, "acc", rng)
    recent = rng.choice(RECENT_ADV)
    src = rng.choice(SOURCES[:7])
    lead = rng.choice([
        f"{subj['nom']} {v(subj, ('сообщили', 'сообщила'))} игрокам о новой акции!",
        f"{subj['nom']} {recent} {v(subj, ('опубликовали', 'опубликовала'))} важную запись!",
        f"{recent.capitalize()} {subj['low']} оставили важную деталь для игроков!" if subj["plural"] else f"{recent.capitalize()} {subj['low']} оставила важную деталь для игроков!",
    ])
    mid = rng.choice([
        f"Недавно Бравл Старс опубликовали запись, в которой спрятали способ получения {r}.",
        f"{src[0].capitalize()} спрятали способ получения {r}." if False else f"В записи спрятали способ получения {r}.",
        f"Среди обычных деталей спрятали {r}.",
    ])
    mid = rng.choice([
        f"Недавно Бравл Старс опубликовали запись, в которой спрятали способ получения {r}.",
        f"{src[0].capitalize()} есть способ получения {r}.",
        f"Среди обычных деталей публикации спрятали {r}.",
    ])
    mid2 = rng.choice([
        f"Почти никто этого не заметил, {rng.choice(BUT)} я уже всё нашёл.",
        f"{few_notice(rng).capitalize()}, {rng.choice(BUT)} я уже разобрался.",
        f"Большинство прошло мимо, {rng.choice(BUT)} я внимательно всё изучил.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T06(rng, subj, reward, use_na):
    r = reward_form(reward, "acc", rng)
    src = rng.choice(SOURCES)
    lead = rng.choice([
        f"Бравл Старс {rng.choice(AGAIN)} радуют своих игроков!",
        f"Бравл Старс {rng.choice(AGAIN)} делятся приятным с игроками!",
        f"{subj['nom']} {rng.choice(AGAIN)} радуют игроков Бравл Старс!" if subj["plural"] else f"{subj['nom']} {rng.choice(AGAIN)} радует игроков Бравл Старс!",
    ])
    mid = rng.choice([
        f"{subj['nom']} разместили свежую публикацию про получение {r}, {rng.choice(BUT)} большинство пользователей прошло мимо неё." if subj["plural"] else f"{subj['nom']} разместила свежую публикацию про получение {r}, {rng.choice(BUT)} большинство пользователей прошло мимо неё.",
        f"{src[0].capitalize()} появилась возможность получить {r}, {rng.choice(BUT)} многие пролистали её.",
        f"{subj['nom']} {v(subj, ('опубликовали', 'опубликовала'))} новость про {r}, {rng.choice(BUT)} большинство прошло мимо.",
    ])
    if use_na:
        return f"{lead} {mid} Я внимательно всё изучил. {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} Я внимательно всё изучил и нашёл способ получения. Вам остаётся лишь забрать {reward['pron']}!"


def T07(rng, subj, reward, use_na):
    r = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"Бравл Старс {rng.choice(AGAIN)} оставили секрет в свежей публикации!",
        f"{subj['nom']} оставили важную деталь в свежей публикации по Бравл Старс!" if subj["plural"] else f"{subj['nom']} оставила важную деталь в свежей публикации по Бравл Старс!",
        f"В свежей публикации по Бравл Старс спрятали кое-что ценное!",
    ])
    mid = rng.choice([
        f"Среди обычных деталей {subj['low']} спрятали {r}, {rng.choice(BUT)} большинство игроков прошло мимо." if subj["plural"] else f"Среди обычных деталей {subj['low']} спрятала {r}, {rng.choice(BUT)} большинство игроков прошло мимо.",
        f"Там спрятали {r}, {rng.choice(BUT)} {few_notice(rng)}.",
        f"{subj['nom']} спрятали {r} среди обычных деталей, {rng.choice(BUT)} почти никто не обратил внимания." if subj["plural"] else f"{subj['nom']} спрятала {r} среди обычных деталей, {rng.choice(BUT)} почти никто не обратил внимания.",
    ])
    if use_na:
        return f"{lead} {mid} Я уже нашёл нужную подсказку. {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} Я уже нашёл нужную подсказку и понял, как его получить. Сейчас покажу всё вам!"


def T08(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"{subj['nom']} завершили технический перерыв в Бравл Старс!" if subj["plural"] else f"{subj['nom']} завершила технический перерыв в Бравл Старс!",
        f"Бравл Старс {rng.choice(AGAIN)} стали доступны после технического перерыва!",
        f"Технический перерыв в Бравл Старс завершён!",
    ])
    mid = rng.choice([
        f"После возвращения в игру появился {r_acc}, хотя отдельно о нём нигде не сообщали.",
        f"Вместе с запуском {subj['low']} {v(subj, ('добавили', 'добавила'))} {r_acc}, {rng.choice(BUT)} не стали рассказывать о нём отдельно.",
        f"После возвращения игрокам {act} {r}, {rng.choice(BUT)} отдельно об этом почти не писали.",
    ])
    mid2 = rng.choice([
        f"Многие игроки этого не заметили, {rng.choice(BUT)} я уже всё проверил.",
        f"Поэтому многие игроки прошли мимо. Я уже разобрался.",
        f"{few_notice(rng).capitalize()}, {rng.choice(BUT)} я уже во всём разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T09(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    lead = rng.choice([
        "Игроки Бравл Старс завершили общее событие раньше срока!",
        "Сообщество Бравл Старс выполнило общую цель раньше срока!",
        "Игроки Бравл Старс добрались до финальной цели общего события!",
    ])
    mid = rng.choice([
        f"После достижения финальной цели {subj['low']} {act} {r} для всех участников.",
        f"За завершение события {subj['low']} {act} участникам {reward_form(reward, 'acc', rng)}.",
        f"После этого {subj['low']} {act} {r}, {rng.choice(BUT)} многие уже перестали следить за результатами.",
    ])
    mid2 = rng.choice([
        f"Многие решили, что получить его уже нельзя, {rng.choice(BUT)} я всё проверил.",
        f"Многие игроки не знали, что его уже можно получить, {rng.choice(BUT)} я всё проверил.",
        "Я вовремя всё заметил и разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T10(rng, subj, reward, use_na):
    r = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"{subj['nom']} провели новую трансляцию по Бравл Старс!" if subj["plural"] else f"{subj['nom']} провела новую трансляцию по Бравл Старс!",
        "Бравл Старс показали новую трансляцию для игроков!",
        f"{subj['nom']} провели свежую трансляцию по Бравл Старс!" if subj["plural"] else f"{subj['nom']} провела свежую трансляцию по Бравл Старс!",
    ])
    mid = rng.choice([
        f"В самом конце они неожиданно сообщили, что игрокам доступен {r}.",
        f"Перед завершением эфира они объявили, что игрокам решили выдать {r}.",
        f"Почти в самом конце {subj['low']} сообщили о том, что можно получить {r}." if subj["plural"] else f"Почти в самом конце {subj['low']} сообщила о том, что можно получить {r}.",
    ])
    mid2 = rng.choice([
        f"Большинство не досмотрело эфир до этого момента, {rng.choice(BUT)} я уже нашёл способ получения.",
        f"Большинство зрителей уже ушло и пропустило эту новость, {rng.choice(BUT)} я всё запомнил.",
        "Многие не стали досматривать эфир. Я увидел объявление и уже понял, что нужно сделать.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T11(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        "Бравл Старс подвели итоги недавнего голосования среди игроков!",
        f"{subj['nom']} опубликовали результаты недавнего опроса по Бравл Старс!" if subj["plural"] else f"{subj['nom']} опубликовала результаты недавнего опроса по Бравл Старс!",
        "Бравл Старс подвели итоги голосования среди игроков!",
    ])
    mid = rng.choice([
        f"Вместе с результатами {subj['low']} {act} {r}, {rng.choice(BUT)} отдельно о нём не сообщили.",
        f"В честь завершения голосования игрокам {act} {r}.",
        f"Вместе с итогами игрокам {act} {r}, {rng.choice(BUT)} отдельно об этом почти не рассказывали.",
    ])
    mid2 = rng.choice([
        "Эту деталь заметили далеко не все.",
        "Большинство заметило только победителя опроса.",
        "Многие прочитали только итоги и пропустили самое важное.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} {mid2} Я всё заметил и {rng.choice(SHOW).lower()}!"


def T12(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    recent = rng.choice(RECENT_ADV)
    lead = rng.choice([
        f"В Бравл Старс {recent} произошёл технический сбой!",
        f"В Бравл Старс {recent} обнаружили техническую ошибку!",
        f"{subj['nom']} завершили устранение сбоя в Бравл Старс!" if subj["plural"] else f"{subj['nom']} завершила устранение сбоя в Бравл Старс!",
    ])
    mid = rng.choice([
        f"{subj['nom']} извинились перед игроками и {act} каждому {reward_form(reward, 'acc', rng)}." if subj["plural"] else f"{subj['nom']} извинилась перед игроками и {act} каждому {reward_form(reward, 'acc', rng)}.",
        f"{subj['nom']} быстро устранили проблему и {act} игрокам {r}." if subj["plural"] else f"{subj['nom']} быстро устранила проблему и {act} игрокам {r}.",
        f"В качестве компенсации игрокам {act} {r}, {rng.choice(BUT)} отдельно об этом почти не сообщали.",
    ])
    mid2 = rng.choice([
        f"Многие подумали, что он появится автоматически, {rng.choice(BUT)} для получения нужно выполнить одно действие.",
        f"Многие уже вернулись в игру, {rng.choice(BUT)} не заметили сообщение о получении.",
        "Поэтому многие даже не проверили получение. Я уже во всём разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T13(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"{subj['nom']} представили нового бойца в Бравл Старс!" if subj["plural"] else f"{subj['nom']} представила нового бойца в Бравл Старс!",
        "Бравл Старс официально представили нового бойца!",
        f"{subj['nom']} показали способности нового бойца Бравл Старс!" if subj["plural"] else f"{subj['nom']} показала способности нового бойца Бравл Старс!",
    ])
    mid = rng.choice([
        f"В честь его появления игрокам {act} {r}, {rng.choice(BUT)} об этом упомянули только в конце публикации.",
        f"В честь его выхода {subj['low']} {act} для игроков {r_acc}. Информацию добавили в конец публикации.",
        f"Вместе с его презентацией игрокам {act} {r}, {rng.choice(BUT)} об этом сказали всего одной фразой.",
    ])
    mid2 = rng.choice([
        "Большинство не дочитало запись до конца.",
        "Поэтому большинство прошло мимо.",
        "Мало кто обратил на неё внимание.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} Я всё заметил. {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} {mid2} Я всё заметил и сейчас покажу, как его получить!"


def T14(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        "Бравл Старс достигли нового рекорда благодаря своим игрокам!",
        "Сообщество Бравл Старс установило новый общий рекорд!",
        "Бравл Старс достигли новой высоты благодаря активности игроков!",
    ])
    mid = rng.choice([
        f"{subj['nom']} решили отметить это событие и выдать {r_acc}." if subj["plural"] else f"{subj['nom']} решила отметить это событие и выдать {r_acc}.",
        f"{subj['nom']} поблагодарили игроков и {act} {r} в честь этого результата." if subj["plural"] else f"{subj['nom']} поблагодарила игроков и {act} {r} в честь этого результата.",
        f"{subj['nom']} решили отметить этот результат и выдать {r_acc} всему сообществу." if subj["plural"] else f"{subj['nom']} решила отметить этот результат и выдать {r_acc} всему сообществу.",
    ])
    mid2 = rng.choice([
        f"Новость появилась {rng.choice(RECENT_ADV)}, поэтому о ней знают ещё не все.",
        f"Новость быстро затерялась среди других публикаций, {rng.choice(BUT)} я её нашёл.",
        "Многие не увидели сообщение и ничего не получили. Я уже проверил информацию.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T15(rng, subj, reward, use_na):
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"В Бравл Старс появилось новое испытание с {r_acc}!",
        f"{subj['nom']} добавили новое испытание в Бравл Старс!" if subj["plural"] else f"{subj['nom']} добавила новое испытание в Бравл Старс!",
        f"В Бравл Старс запустили короткое испытание с {r_acc}!",
    ])
    mid = rng.choice([
        "Для его получения нужно выполнить простое условие, которое многие игроки не заметили.",
        f"За выполнение простого условия каждый игрок сможет получить {r_acc}. Большинство сразу начало играть и не прочитало главное правило.",
        f"Получить его можно после выполнения одного условия, которое указали в конце описания.",
    ])
    mid2 = rng.choice([
        "Я уже завершил испытание и проверил результат.",
        "Я уже завершил всё сам.",
        "Многие игроки его не заметили. Я уже всё выполнил.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} {mid2} Сейчас расскажу, что именно нужно сделать!"


def T16(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    lead = rng.choice([
        f"{subj['nom']} подвели итоги чемпионата по Бравл Старс!" if subj["plural"] else f"{subj['nom']} подвела итоги чемпионата по Бравл Старс!",
        "Завершился очередной чемпионат по Бравл Старс!",
        f"{subj['nom']} опубликовали результаты чемпионата по Бравл Старс!" if subj["plural"] else f"{subj['nom']} опубликовала результаты чемпионата по Бравл Старс!",
    ])
    mid = rng.choice([
        f"После завершения финала участникам события {act} {r}, {rng.choice(BUT)} многие забыли проверить результат.",
        f"После финального матча {subj['low']} {act} участникам события {reward_form(reward, 'acc', rng)}.",
        f"Игрокам, следившим за финальными матчами, {act} {r}.",
    ])
    mid2 = rng.choice([
        "Я уже нашёл всё необходимое.",
        "Многие посмотрели результаты и сразу закрыли публикацию, пропустив главное.",
        f"Не все поняли, где его нужно получить, {rng.choice(BUT)} я уже разобрался.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T17(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        "В Бравл Старс стартовал новый сезон!",
        "Бравл Старс представили новый сезон для игроков!",
        f"{subj['nom']} объявили о начале нового сезона Бравл Старс!" if subj["plural"] else f"{subj['nom']} объявила о начале нового сезона Бравл Старс!",
    ])
    mid = rng.choice([
        f"Вместе с ним {subj['low']} {act} {r} для всех игроков, {rng.choice(BUT)} условие получения указали только в конце анонса.",
        f"Вместе с его запуском {subj['low']} {act} {r}, {rng.choice(BUT)} условие получения спрятали в конце публикации.",
        f"Помимо новинок сезона игрокам {act} {r}. Об этом коротко упомянули в конце анонса.",
    ])
    mid2 = rng.choice([
        "Многие прочитали лишь основную часть и прошли мимо.",
        "Большинство прочитало только основные новости.",
        "Поэтому многие ничего не заметили.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} {mid2} Я уже всё нашёл и покажу, как его получить!"


def T18(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"{subj['nom']} объявили о новой коллаборации в Бравл Старс!" if subj["plural"] else f"{subj['nom']} объявила о новой коллаборации в Бравл Старс!",
        "Бравл Старс официально объявили о новой коллаборации!",
        f"{subj['nom']} представили новую коллаборацию в Бравл Старс!" if subj["plural"] else f"{subj['nom']} представила новую коллаборацию в Бравл Старс!",
    ])
    if rng.random() < 0.05:
        mid = f"В честь её запуска игрокам {act} {r}. Главное условие показали только на втором изображении, поэтому большинство его не заметило."
    else:
        mid = rng.choice([
            f"В честь её запуска игрокам {act} {r}. Главное условие спрятали в конце публикации, поэтому большинство его не заметило.",
            f"Вместе с её запуском {subj['low']} {act} для игроков {r_acc}. Условие получения показали только в конце, поэтому его почти никто не заметил.",
            f"Помимо тематических обликов игрокам {act} {r}. Главную информацию спрятали среди деталей публикации.",
        ])
    mid2 = rng.choice(["Я уже всё нашёл.", "Я всё заметил.", "Многие прошли мимо. Я уже всё нашёл."])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T19(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        "Бравл Старс расширили трофейный путь для игроков!",
        f"{subj['nom']} обновили трофейный путь в Бравл Старс!" if subj["plural"] else f"{subj['nom']} обновила трофейный путь в Бравл Старс!",
        "Бравл Старс расширили трофейный путь для всех игроков!",
    ])
    mid = rng.choice([
        f"За достижение нового рубежа {subj['low']} {v(subj, ('добавили', 'добавила'))} {r_acc}, {rng.choice(BUT)} упомянули об этом всего одной строкой.",
        f"За достижение одного из новых рубежей игроки смогут получить {r_acc}. Об этом упомянули только в конце описания.",
        f"Среди новых рубежей {subj['low']} разместили {r_acc}, {rng.choice(BUT)} отдельно о нём не рассказали." if subj["plural"] else f"Среди новых рубежей {subj['low']} разместила {r_acc}, {rng.choice(BUT)} отдельно о нём не рассказали.",
    ])
    mid2 = rng.choice([
        f"Многие прошли мимо этой информации, {rng.choice(BUT)} я всё проверил.",
        "Поэтому почти никто не обратил внимания.",
        "Многие уже достигли нужного количества трофеев и прошли мимо. Я всё проверил.",
    ])
    return f"{lead} {mid} {mid2} {end_block(rng, reward, use_na)}"


def T20(rng, subj, reward, use_na):
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"{subj['nom']} вернули популярный режим в Бравл Старс!" if subj["plural"] else f"{subj['nom']} вернула популярный режим в Бравл Старс!",
        f"В Бравл Старс {rng.choice(AGAIN)} появился популярный режим!",
        f"{subj['nom']} вернули один из старых режимов Бравл Старс!" if subj["plural"] else f"{subj['nom']} вернула один из старых режимов Бравл Старс!",
    ])
    mid = rng.choice([
        f"В честь его возвращения каждому игроку {act} {r} после одного завершённого боя.",
        f"За первый завершённый бой игрокам {act} {r}. Условие указали короткой фразой в публикации.",
        f"В честь его возвращения {subj['low']} {act} {r} для каждого участника. Чтобы получить его, достаточно завершить один бой.",
    ])
    mid2 = rng.choice([
        "Об этом упомянули совсем коротко, поэтому многие ничего не заметили.",
        "Поэтому его заметили далеко не все.",
        "Об этом знают ещё не все.",
    ])
    if use_na:
        return f"{lead} {mid} {mid2} {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} {mid2} Я уже всё проверил и сейчас покажу вам!"


def T21(rng, subj, reward, use_na):
    """Rare calendar/changes (~1/20)."""
    act, case = pick_action(rng, subj)
    r = reward_form(reward, case, rng)
    r_acc = reward_form(reward, "acc", rng)
    lead = rng.choice([
        f"{subj['nom']} внесли свежие изменения в Бравл Старс!" if subj["plural"] else f"{subj['nom']} внесла свежие изменения в Бравл Старс!",
        "В календаре событий Бравл Старс появилось кое-что важное!",
        "Бравл Старс обновили календарь событий!",
    ])
    mid = rng.choice([
        f"Вместе с изменениями игрокам {act} {r}, {rng.choice(BUT)} отдельно об этом почти не писали.",
        f"Среди пунктов календаря спрятали {r_acc}, {rng.choice(BUT)} большинство игроков прошло мимо.",
        f"После обновления календаря стал доступен {r_acc}, {rng.choice(BUT)} {few_notice(rng)}.",
    ])
    if use_na:
        return f"{lead} {mid} Я всё проверил. {rng.choice(NA_ENDS)}"
    return f"{lead} {mid} Я всё проверил и покажу нужный способ!"


TEMPLATES = [T01, T02, T03, T04, T05, T06, T07, T08, T09, T10, T11, T12, T13, T14, T15, T16, T17, T18, T19, T20]


def soft_len_ok(text: str) -> bool:
    return 175 <= len(text) <= 310


def has_reward(text: str, reward: dict) -> bool:
    return reward["nom"] in text


def order_diverse(items: list[tuple]) -> list[tuple]:
    """items: (reward_i, tid, subj_i, text)"""
    # Bucket by (reward, template)
    buckets: dict[tuple[int, int], deque] = defaultdict(deque)
    for it in items:
        buckets[(it[0], it[1])].append(it)

    keys = sorted(buckets.keys(), key=lambda k: (hashlib.md5(str(k).encode()).hexdigest()))
    # Round-robin over keys but greedily avoid last reward/template/subject
    ordered = []
    last_r, last_t, last_s = -1, -1, -1
    while buckets:
        best_key = None
        best_score = -10**9
        # evaluate a sample of available keys for speed
        avail = [k for k, q in buckets.items() if q]
        if not avail:
            break
        # score all if few, else sample
        if len(avail) > 80:
            cand = random.Random(len(ordered)).sample(avail, 80)
        else:
            cand = avail
        for k in cand:
            item = buckets[k][0]
            score = 0
            if item[0] != last_r:
                score += 50
            if item[1] != last_t:
                score += 30
            if item[2] != last_s:
                score += 15
            # prefer fuller buckets slightly for balance later
            score += min(len(buckets[k]), 5)
            score += random.Random(len(ordered) * 17 + k[0] * 3 + k[1]).random()
            if score > best_score:
                best_score = score
                best_key = k
        item = buckets[best_key].popleft()
        if not buckets[best_key]:
            del buckets[best_key]
        ordered.append(item)
        last_r, last_t, last_s = item[0], item[1], item[2]
        if len(ordered) % 20000 == 0:
            print(f"ordered {len(ordered)}", flush=True)
    return ordered


def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    seen: set[str] = set()
    texts: list[tuple] = []
    per_reward = TARGET // 4
    counts = [0, 0, 0, 0]
    raz_total = 0
    cal_total = 0
    base = random.Random(4170)
    attempts = 0
    limit = TARGET * 100

    while sum(counts) < TARGET and attempts < limit:
        attempts += 1
        reward_i = min(range(4), key=lambda i: (counts[i], base.random()))
        if counts[reward_i] >= per_reward:
            if all(c >= per_reward for c in counts):
                break
            continue

        reward = REWARDS[reward_i]
        # rare calendar template ~5% until cap 5%
        use_cal = cal_total < TARGET // 20 and base.random() < 0.05
        if use_cal:
            tid = 20
            builder = T21
        else:
            tid = base.randrange(len(TEMPLATES))
            builder = TEMPLATES[tid]

        subj_i = base.randrange(len(SUBJECTS))
        subj = SUBJECTS[subj_i]
        use_na = base.random() < 0.5
        allow_raz = raz_total < TARGET // 25
        rng = random.Random(base.randint(1, 2**31 - 1))

        # temporarily block rare action if over cap
        text = builder(rng, subj, reward, use_na)
        text = normalize(text)
        if forbidden(text):
            continue
        if not soft_len_ok(text):
            continue
        if not has_reward(text, reward):
            continue
        rc = raz_count(text)
        if rc and not allow_raz:
            continue
        if ("календар" in text.lower() or "изменения" in text.lower()) and cal_total >= TARGET // 20:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if rc:
            raz_total += 1
        if "календар" in text.lower() or tid == 20:
            cal_total += 1
        texts.append((reward_i, tid, subj_i, text))
        counts[reward_i] += 1
        if sum(counts) % 10000 == 0:
            print(f"gen {sum(counts)} attempts={attempts}", flush=True)

    print(f"generated {len(texts)} counts={counts} raz={raz_total} cal={cal_total}", flush=True)

    # Fill if short
    fill = 0
    while len(texts) < TARGET and fill < limit:
        fill += 1
        reward_i = min(range(4), key=lambda i: counts[i])
        reward = REWARDS[reward_i]
        tid = fill % len(TEMPLATES)
        subj_i = (fill * 5) % len(SUBJECTS)
        use_na = fill % 2 == 0
        rng = random.Random(9_000_000 + fill)
        text = normalize(TEMPLATES[tid](rng, SUBJECTS[subj_i], reward, use_na))
        salt = rng.choice([
            " Проверьте сами!",
            " Не упустите момент!",
            " Действуйте быстрее!",
            " Успейте первыми!",
            " Зайдите и проверьте!",
            " Сделайте это сейчас!",
        ])
        text = normalize(text + salt)
        if forbidden(text) or not soft_len_ok(text) or not has_reward(text, reward):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        texts.append((reward_i, tid, subj_i, text))
        counts[reward_i] += 1

    texts = texts[:TARGET]
    print(f"pre-order {len(texts)} counts={counts}", flush=True)

    # Shuffle within coarse groups then diverse order
    random.Random(99).shuffle(texts)
    ordered = order_diverse(texts)

    print("writing...", flush=True)
    for i, it in enumerate(ordered, 1):
        (OUT_DIR / f"{i:06d}.txt").write_text(it[3] + "\n", encoding="utf-8")
        if i % 20000 == 0:
            print(f"wrote {i}", flush=True)

    same_t = sum(1 for a, b in zip(ordered, ordered[1:]) if a[1] == b[1])
    same_r = sum(1 for a, b in zip(ordered, ordered[1:]) if a[0] == b[0])
    lens = [len(x[3]) for x in ordered[::500]]
    print(f"adj same_t={same_t} same_r={same_r} len {min(lens)}/{sum(lens)//len(lens)}/{max(lens)}")

    print("zipping...", flush=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i in range(1, len(ordered) + 1):
            zf.write(OUT_DIR / f"{i:06d}.txt", arcname=f"{i:06d}.txt")
            if i % 25000 == 0:
                print(f"zip {i}", flush=True)
    shutil.copy2(ZIP_PATH, REPO_ZIP)
    print(f"DONE {ZIP_PATH} bytes={ZIP_PATH.stat().st_size}")


if __name__ == "__main__":
    main()
