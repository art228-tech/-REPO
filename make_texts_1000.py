#!/usr/bin/env python3
"""Generate 1000 unique promo-text variants as .txt files.

Rules:
- total length within +-10% of the reference text;
- first sentence length within +-10% of the reference's first sentence;
- exactly one reward term per text (no mixing);
- no YouTube-trigger words (бесплатно, раздают, etc.);
- all texts unique.
"""
import os
import random
import re
import sys

REFERENCE = (
    "Где разработчики оставили нам ультрахаосдроп? Совсем Недавно на своих "
    "каналах суперсэлл оставили нам пасхалку, в которой как они говорят "
    "спрятана награда для всех! Но сколько же хаос ящиков нам дадут и где "
    "найти пасхалку? Я уже все сделал и нашел их, держите!"
)

TRIGGER_RE = re.compile(r"бесплатн|раздают|раздача|раздают|халяв", re.IGNORECASE)

TERMS = {
    "uhd": {"nom": "ультра хаос дропы", "gen": "ультра хаос дропов", "plural": True},
    "hd": {"nom": "хаосдропы", "gen": "хаосдропов", "plural": True},
    "uy": {"nom": "ультра ящики", "gen": "ультра ящиков", "plural": True},
    "bp": {"nom": "бравл пасс", "gen": "бравл пасс", "plural": False},
}

# Hook templates: first sentence. {nom} is replaced by the reward term.
HOOKS_GENERIC = [
    "Суперсэлл опять запустили охоту за секретами!",
    "Вы не поверите, что устроили нам суперсэлл!",
    "Слышали уже про новую пасхалку от суперсэлл?",
    "Такого поворота от суперсэлл никто точно не ждал!",
    "Охота за секретом суперсэлл официально началась!",
    "Суперсэлл тихо спрятали в постах новую пасхалку!",
    "Разработчики подкинули игрокам новую загадку!",
    "Кажется, суперсэлл снова решили нас удивить!",
    "Новая пасхалка от суперсэлл уже наделала шума!",
    "В соцсетях суперсэлл появилась странная пасхалка!",
    "Где спрятана новая пасхалка от разработчиков?",
    "Игроки всю неделю ищут пасхалку от суперсэлл!",
    "Суперсэлл спрятали сюрприз прямо у нас под носом!",
    "Вся лента обсуждает новую загадку от суперсэлл!",
    "Разработчики приготовили квест для всех игроков!",
]

HOOKS_TERM = [
    "Каждый игрок может получить {nom}!",
    "{Nom} за пасхалку — это реально?",
    "{Nom} за простую пасхалку — это реально?",
    "Суперсэлл приготовили {nom} для всех?",
    "Где разработчики спрятали для нас {nom}?",
    "Как получить {nom} за пасхалку суперсэлл?",
    "Куда суперсэлл запрятали {nom} для игроков?",
]

BODIES = [
    "Недавно разработчики оставили на своих каналах пасхалку и пообещали награду каждому, кто её разгадает.",
    "Совсем недавно суперсэлл спрятали в своих соцсетях пасхалку, внутри которой лежит награда для всех игроков.",
    "На днях разработчики опубликовали на своих каналах загадку и намекнули, что нашедших ждёт награда.",
    "Прямо на официальных каналах суперсэлл появилась пасхалка, а внутри неё — награда для каждого игрока.",
    "Буквально на днях суперсэлл выложили на своих каналах секрет, за разгадку которого обещают награду.",
    "Разработчики запрятали на своих каналах хитрую пасхалку и заявили, что награда ждёт всех без исключения.",
    "Суперсэлл устроили настоящий квест: на их каналах спрятана пасхалка, и каждый нашедший получит награду.",
    "В свежих постах суперсэлл спряталась пасхалка, о которой разработчики говорят: награда достанется всем.",
]

MIDDLES_PLURAL = [
    "Но сколько {gen} нам дадут и где найти пасхалку?",
    "Сколько же {gen} нам приготовили и где спрятан секрет?",
    "Осталось понять, где искать и сколько {gen} нам достанется.",
    "Но где прячется секрет и сколько {gen} нас ждёт?",
    "Вопрос один: где искать пасхалку и сколько {gen} дадут?",
]

MIDDLES_SINGULAR = [
    "Но правда ли наградой стал бравл пасс и где искать пасхалку?",
    "Неужели внутри спрятан бравл пасс и где прячется секрет?",
    "Говорят, наградой будет бравл пасс — но где его искать?",
    "Вопрос один: где пасхалка и точно ли внутри бравл пасс?",
]

CLOSERS = [
    "Я уже всё сделал и нашёл ответ — держите!",
    "Я потратил вечер, но разгадал её — показываю!",
    "Я всё проверил сам и готов поделиться, ловите!",
    "Я справился первым, так что смотрите до конца!",
    "Я уже прошёл весь квест — забирайте ответ!",
    "Я всё выяснил и рассказываю прямо сейчас!",
]

OUT_DIR = "texts_1000"
TARGET = 1000


def first_sentence(text: str) -> str:
    match = re.match(r".*?[.!?]", text)
    return match.group(0) if match else text


def fill(template: str, term: dict) -> str:
    nom = term["nom"]
    return template.replace("{Nom}", nom[0].upper() + nom[1:]).replace(
        "{nom}", nom).replace("{gen}", term["gen"])


def main() -> int:
    ref_len = len(REFERENCE)
    ref_fs = len(first_sentence(REFERENCE))
    lo, hi = ref_len * 0.9, ref_len * 1.1
    fs_lo, fs_hi = ref_fs * 0.9, ref_fs * 1.1
    print(f"Reference: total {ref_len} (allowed {lo:.0f}-{hi:.0f}), "
          f"first sentence {ref_fs} (allowed {fs_lo:.0f}-{fs_hi:.0f})")

    rng = random.Random(42)
    per_term_texts = {}
    for key, term in TERMS.items():
        hooks = []
        for h in HOOKS_GENERIC + [fill(t, term) for t in HOOKS_TERM]:
            if fs_lo <= len(h) <= fs_hi:
                hooks.append(h)
        middles = [fill(m, term)
                   for m in (MIDDLES_PLURAL if term["plural"] else MIDDLES_SINGULAR)]
        combos = []
        for hook in hooks:
            for body in BODIES:
                for middle in middles:
                    for closer in CLOSERS:
                        text = " ".join([hook, body, middle, closer])
                        if lo <= len(text) <= hi and not TRIGGER_RE.search(text):
                            combos.append(text)
        rng.shuffle(combos)
        per_term_texts[key] = combos
        print(f"term '{term['nom']}': {len(hooks)} hooks, {len(combos)} valid combos")

    # Round-robin across terms for an even mix, dedupe, take TARGET.
    selected = []
    seen = set()
    idx = 0
    keys = list(per_term_texts)
    while len(selected) < TARGET:
        progressed = False
        for key in keys:
            pool = per_term_texts[key]
            if idx < len(pool):
                text = pool[idx]
                if text not in seen:
                    seen.add(text)
                    selected.append(text)
                    progressed = True
                    if len(selected) == TARGET:
                        break
        if not progressed and all(idx >= len(p) for p in per_term_texts.values()):
            print(f"ERROR: only {len(selected)} unique texts available", file=sys.stderr)
            return 1
        idx += 1

    os.makedirs(OUT_DIR, exist_ok=True)
    for i, text in enumerate(selected, 1):
        with open(os.path.join(OUT_DIR, f"text_{i:04d}.txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")

    lengths = [len(t) for t in selected]
    fs_lengths = [len(first_sentence(t)) for t in selected]
    print(f"Wrote {len(selected)} files to {OUT_DIR}/")
    print(f"Total length: min {min(lengths)}, max {max(lengths)} (allowed {lo:.0f}-{hi:.0f})")
    print(f"First sentence: min {min(fs_lengths)}, max {max(fs_lengths)} "
          f"(allowed {fs_lo:.0f}-{fs_hi:.0f})")
    print(f"Unique texts: {len(set(selected))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
