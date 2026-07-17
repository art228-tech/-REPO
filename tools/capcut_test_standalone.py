# -*- coding: utf-8 -*-
"""
Автономный тест сборки CapCut (без установки зависимостей и без GitHub).

Что делает:
  1) находит папку проектов CapCut на этом компьютере;
  2) берёт твой проект с самым «тяжёлым» draft_content.json (тот, что с монтажом);
  3) делает его КОПИЮ в проект 'autoshorts_test' и меняет там только субтитры
     на тестовый текст (оригинал не трогается);
  4) ты открываешь CapCut и проверяешь, что проект открывается и стиль на месте.

Запуск: сохрани этот файл как capcut_test.py и выполни:
    python capcut_test.py
"""
import copy
import json
import os
import shutil
import time
from pathlib import Path


def find_projects_dir():
    cands = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(Path(la) / "CapCut/User Data/Projects/com.lveditor.draft")
        cands.append(Path(la) / "CapCut/User Data/Projects")
    home = Path.home()
    cands.append(home / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft")
    cands.append(home / "AppData/Local/CapCut/User Data/Projects")
    for c in cands:
        if c.exists():
            return c
    return None


def mat_by_id(draft, mid):
    for cat in draft.get("materials", {}):
        for it in draft["materials"][cat] or []:
            if isinstance(it, dict) and it.get("id") == mid:
                return it
    return None


def find_text_track(draft):
    for t in draft.get("tracks", []):
        if t.get("type") == "text" and t.get("segments"):
            return t
    return None


def build_word_info(tokens, dur_ms):
    n = max(len(tokens), 1)
    step = dur_ms / n
    words, parts, ranges, loc = [], [], [], 0
    for i, tok in enumerate(tokens):
        st, en = int(i * step), int((i + 1) * step)
        if i > 0:
            words.append({"text": " ", "start_time": words[-1]["end_time"],
                          "end_time": words[-1]["end_time"]})
            parts.append(" ")
            loc += 1
        words.append({"text": tok, "start_time": st, "end_time": en})
        ranges.append({"location": loc, "length": len(tok),
                       "source_type": "unknown"})
        parts.append(tok)
        loc += len(tok)
    text = "".join(parts)
    end_ms = words[-1]["end_time"] if words else 0
    return text, {"text": text, "start_time": 0, "end_time": end_ms,
                  "words": words}, ranges


def set_text_content(tmat, text):
    try:
        c = json.loads(tmat.get("content") or "{}")
        c["text"] = text
        for st in c.get("styles", []):
            st["range"] = [0, len(text)]
        tmat["content"] = json.dumps(c, ensure_ascii=False)
    except Exception:
        pass


def main():
    print("== Тест сборки CapCut ==")
    pdir = find_projects_dir()
    if not pdir:
        print("[X] Не нашёл папку проектов CapCut.")
        print("    Ожидалось: %LOCALAPPDATA%\\CapCut\\User Data\\Projects")
        return
    print("[i] Папка проектов:", pdir)

    # выбрать проект с самым большим draft_content.json (там монтаж)
    best, best_size = None, 0
    for sub in pdir.iterdir():
        if not sub.is_dir():
            continue
        f = sub / "draft_content.json"
        if f.exists() and f.stat().st_size > best_size:
            best, best_size = sub, f.stat().st_size
    if not best:
        print("[X] Не нашёл ни одного проекта с draft_content.json.")
        return
    print(f"[i] Беру проект-эталон: '{best.name}' ({best_size} байт)")

    # копия проекта целиком (со всеми служебными файлами)
    out = pdir / "autoshorts_test"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(best, out)

    draft = json.loads((out / "draft_content.json").read_text(encoding="utf-8"))
    ttrack = find_text_track(draft)
    if not ttrack:
        print("[!] В проекте нет дорожки субтитров — возьми проект с субтитрами.")
    else:
        phrases = ["автосборка тест", "субтитры меняются", "стиль сияние",
                   "работает как надо", "готово к запуску", "проверка связи",
                   "ещё одна строка", "финальная реплика"]
        changed = 0
        for i, seg in enumerate(ttrack["segments"]):
            tpl = mat_by_id(draft, seg.get("material_id"))
            if not tpl:
                continue
            dur_ms = int(seg.get("target_timerange", {}).get("duration", 1_000_000) / 1000)
            text, info, ranges = build_word_info(phrases[i % len(phrases)].split(), dur_ms)
            if "current_word_info" in tpl:
                tpl["current_word_info"] = copy.deepcopy(info)
            if "origin_word_info" in tpl:
                tpl["origin_word_info"] = copy.deepcopy(info)
            tpl["material_text_ranges"] = ranges
            for tir in tpl.get("text_info_resources", []):
                tm = mat_by_id(draft, tir.get("text_material_id"))
                if tm:
                    set_text_content(tm, text)
            changed += 1
        print(f"[i] Заменено субтитров: {changed}")

    draft["name"] = "autoshorts_test"
    (out / "draft_content.json").write_text(
        json.dumps(draft, ensure_ascii=False), encoding="utf-8")

    meta_path = out / "draft_meta_info.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    except Exception:
        meta = {}
    meta.update({"draft_name": "autoshorts_test",
                 "draft_fold_path": str(out),
                 "tm_draft_modified": int(time.time() * 1000)})
    meta.setdefault("tm_draft_create", int(time.time() * 1000))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    print("\n[OK] Готово! Создан проект: autoshorts_test")
    print("     Папка:", out)
    print("\nЧто дальше:")
    print(" 1) Полностью закрой CapCut и открой заново.")
    print(" 2) Найди в списке проект 'autoshorts_test'.")
    print(" 3) Открой его и проверь: субтитры со стилем на месте, ошибок нет.")
    print("    (Текст субтитров будет тестовый — 'автосборка тест' и т.п.)")


if __name__ == "__main__":
    main()
