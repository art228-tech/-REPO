@echo off & chcp 65001 >nul & ( python -x "%~f0" || py -x "%~f0" || ( echo. & echo [!] Python ne nayden. Ustanovi s https://python.org/downloads i postav galochku "Add python.exe to PATH", potom zapusti fayl snova. & pause ) ) & exit /b
# capcut_test.bat -- double-click to run. Batch header above; Python below.
import copy, json, os, shutil, time, uuid
from pathlib import Path

LOG_LINES = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s); LOG_LINES.append(s)

def find_projects_dir():
    cands = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(Path(la) / "CapCut/User Data/Projects/com.lveditor.draft")
    home = Path.home()
    cands.append(home / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft")
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

def build_word_info(tokens, dur_ms):
    n = max(len(tokens), 1); step = dur_ms / n
    words, parts, ranges, loc = [], [], [], 0
    for i, tok in enumerate(tokens):
        st, en = int(i * step), int((i + 1) * step)
        if i > 0:
            words.append({"text": " ", "start_time": words[-1]["end_time"], "end_time": words[-1]["end_time"]})
            parts.append(" "); loc += 1
        words.append({"text": tok, "start_time": st, "end_time": en})
        ranges.append({"location": loc, "length": len(tok), "source_type": "unknown"})
        parts.append(tok); loc += len(tok)
    text = "".join(parts)
    return text, {"text": text, "start_time": 0, "end_time": (words[-1]["end_time"] if words else 0), "words": words}, ranges

def set_text_content(tmat, text):
    try:
        c = json.loads(tmat.get("content") or "{}")
        c["text"] = text
        for st in c.get("styles", []):
            st["range"] = [0, len(text)]
        tmat["content"] = json.dumps(c, ensure_ascii=False)
    except Exception:
        pass

def edit_subtitles(draft):
    """Меняем субтитры на тестовый текст (best-effort)."""
    phrases = ["test caption one", "captions change", "glow style ok",
               "works fine", "ready to go", "line five", "line six", "line seven"]
    tracks = [t for t in draft.get("tracks", []) if t.get("type") == "text" and t.get("segments")]
    changed = 0
    for tr in tracks:
        for i, seg in enumerate(tr["segments"]):
            tpl = mat_by_id(draft, seg.get("material_id"))
            if not tpl:
                continue
            dur_ms = int(seg.get("target_timerange", {}).get("duration", 1000000) / 1000)
            text, info, ranges = build_word_info(phrases[i % len(phrases)].split(), dur_ms)
            if "current_word_info" in tpl: tpl["current_word_info"] = copy.deepcopy(info)
            if "origin_word_info" in tpl: tpl["origin_word_info"] = copy.deepcopy(info)
            if "material_text_ranges" in tpl: tpl["material_text_ranges"] = ranges
            for tir in tpl.get("text_info_resources", []):
                tm = mat_by_id(draft, tir.get("text_material_id"))
                if tm: set_text_content(tm, text)
            changed += 1
    return changed

def try_edit_timeline_file(path):
    """Если файл — JSON с таймлайном CapCut, меняем в нём субтитры."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return False
    if not isinstance(data, dict) or "tracks" not in data:
        return False
    ch = edit_subtitles(data)
    data["name"] = "autoshorts_test"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    log("    edited timeline:", path.name, "(subtitles:", ch, ")")
    return True

def find_entry_list(obj):
    """Найти в root_meta_info список записей о проектах (list of dict с fold_path)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and \
               any("fold_path" in kk.lower() for kk in v[0]):
                return obj, k
        for v in obj.values():
            r = find_entry_list(v)
            if r: return r
    return None

def register_in_index(pdir, out, new_id):
    reg = pdir / "root_meta_info.json"
    if not reg.exists():
        log("[!] root_meta_info.json ne nayden -- proekt mozhet ne poyavitsya v spiske.")
        return False
    try:
        root = json.loads(reg.read_text(encoding="utf-8"))
    except Exception as e:
        log("[!] ne smog prochitat root_meta_info.json:", e); return False
    found = find_entry_list(root)
    if not found:
        log("[!] ne nashel spisok proektov v indekse."); return False
    container, key = found
    entries = container[key]
    # клонируем запись исходного проекта (по совпадению пути), иначе первую
    src = None
    for e in entries:
        for kk, vv in e.items():
            if "fold_path" in kk.lower() and isinstance(vv, str) and out.name != Path(vv).name and best_name in vv:
                src = e; break
        if src: break
    src = src or entries[0]
    ne = copy.deepcopy(src)
    now = int(time.time() * 1000)
    for kk in list(ne.keys()):
        low = kk.lower()
        if "fold_path" in low:
            ne[kk] = str(out)
        elif low in ("draft_id", "id") or low.endswith("_id"):
            ne[kk] = new_id
        elif "name" in low:
            ne[kk] = "autoshorts_test"
        elif "create" in low or "modified" in low or low.startswith("tm_"):
            ne[kk] = now
    reg.with_suffix(".json.bak").write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")
    entries.append(ne)
    reg.write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")
    log("[i] proekt zaregistrirovan v root_meta_info.json (bekap .bak sozdan)")
    return True

best_name = ""
def main():
    global best_name
    log("== CapCut test v2 ==")
    pdir = find_projects_dir()
    if not pdir:
        log("[X] Papka proektov CapCut ne naydena."); finish(None); return
    log("[i] Projects:", pdir)
    best, best_size = None, 0
    for sub in pdir.iterdir():
        if not sub.is_dir(): continue
        f = sub / "draft_content.json"
        if f.exists() and f.stat().st_size > best_size:
            best, best_size = sub, f.stat().st_size
    if not best:
        log("[X] Net proekta s draft_content.json"); finish(None); return
    best_name = best.name
    log("[i] Source project: '%s' (%d bytes)" % (best.name, best_size))

    out = pdir / "autoshorts_test"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(best, out)
    new_id = str(uuid.uuid4()).upper()

    # правим субтитры во всех файлах таймлайна проекта
    for fname in ("draft_content.json", "draft_info.json", "template-2.tmp", "template.tmp"):
        p = out / fname
        if p.exists():
            try_edit_timeline_file(p)
    # id в draft_content.json
    try:
        dc = out / "draft_content.json"
        d = json.loads(dc.read_text(encoding="utf-8")); d["id"] = new_id
        dc.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    # sidecar
    meta_path = out / "draft_meta_info.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    except Exception:
        meta = {}
    meta.update({"draft_name": "autoshorts_test", "draft_fold_path": str(out),
                 "draft_id": new_id, "tm_draft_modified": int(time.time() * 1000)})
    meta.setdefault("tm_draft_create", int(time.time() * 1000))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    register_in_index(pdir, out, new_id)
    finish(out)

def finish(out):
    # лог на рабочий стол
    try:
        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)
        (desktop / "capcut_test_log.txt").write_text("\n".join(LOG_LINES), encoding="utf-8")
    except Exception:
        pass
    if out:
        log("")
        log("[OK] Gotovo. Proekt: autoshorts_test")
        log("Dalshe: 1) polnostyu zakroy CapCut  2) otkroy zanovo  3) naydi 'autoshorts_test'")
        try:
            os.startfile(str(out))  # otkroem papku proekta v Provodnike
        except Exception:
            pass
    log("")
    log("(log sohranen na Rabochiy stol: capcut_test_log.txt -- prishli ego mne)")
    try:
        input("Nazhmi Enter dlya vyhoda...")
    except Exception:
        pass

if __name__ == "__main__":
    main()
