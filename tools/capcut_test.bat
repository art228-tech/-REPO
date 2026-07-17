@echo off & chcp 65001 >nul & ( python -x "%~f0" || py -x "%~f0" || ( echo. & echo [!] Python ne nayden. Ustanovi s https://python.org/downloads i postav galochku "Add python.exe to PATH", potom zapusti fayl snova. & pause ) ) & exit /b
# capcut_test.bat v3 -- double-click to run. Batch header above; Python below.
import copy, json, os, shutil, time, uuid, urllib.request
from pathlib import Path

LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); LOG.append(s)

def find_projects_dir():
    la = os.environ.get("LOCALAPPDATA")
    cands = []
    if la:
        cands.append(Path(la) / "CapCut/User Data/Projects/com.lveditor.draft")
    cands.append(Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft")
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

def build_sub(tokens, dur_ms):
    """Собрать все представления субтитра: текст, массивы words, word_info, ranges."""
    n = max(len(tokens), 1); step = dur_ms / n
    st, en, txt = [], [], []
    wi_words, ranges, loc = [], [], 0
    for i, tok in enumerate(tokens):
        if i > 0:
            st.append(en[-1]); en.append(en[-1]); txt.append(" ")
            wi_words.append({"text": " ", "start_time": en[-1], "end_time": en[-1]}); loc += 1
        s, e = int(i*step), int((i+1)*step)
        st.append(s); en.append(e); txt.append(tok)
        wi_words.append({"text": tok, "start_time": s, "end_time": e})
        ranges.append({"location": loc, "length": len(tok), "source_type": "unknown"}); loc += len(tok)
    full = "".join(txt)
    words_arr = {"start_time": st, "end_time": en, "text": txt}
    word_info = {"text": full, "start_time": 0, "end_time": (en[-1] if en else 0), "words": wi_words}
    return full, words_arr, word_info, ranges

def set_content_text(tmat, full):
    try:
        c = json.loads(tmat.get("content") or "{}"); c["text"] = full
        for stl in c.get("styles", []):
            stl["range"] = [0, len(full)]
        tmat["content"] = json.dumps(c, ensure_ascii=False)
    except Exception:
        pass

def apply_cue(draft, tpl, tokens, dur_ms):
    full, words_arr, word_info, ranges = build_sub(tokens, dur_ms)
    # шаблон
    if "current_word_info" in tpl: tpl["current_word_info"] = copy.deepcopy(word_info)
    if "origin_word_info" in tpl: tpl["origin_word_info"] = copy.deepcopy(word_info)
    if "material_text_ranges" in tpl: tpl["material_text_ranges"] = ranges
    if "merge_content" in tpl: tpl["merge_content"] = full
    # связанные текст-материалы (тут реально лежит отображаемый текст)
    for tir in tpl.get("text_info_resources", []):
        tm = mat_by_id(draft, tir.get("text_material_id"))
        if not tm:
            continue
        set_content_text(tm, full)
        if "recognize_text" in tm: tm["recognize_text"] = full
        if "words" in tm and isinstance(tm["words"], dict): tm["words"] = words_arr

def clear_subtitle_cache(draft):
    """Убрать кэш распознавания речи, чтобы CapCut взял текст из материалов."""
    ei = draft.get("extra_info")
    if isinstance(ei, dict) and isinstance(ei.get("subtitle_fragment_info_list"), list):
        ei["subtitle_fragment_info_list"] = []
    cfgc = draft.get("config")
    if isinstance(cfgc, dict):
        for k in ("subtitle_taskinfo", "lyrics_taskinfo"):
            if isinstance(cfgc.get(k), list): cfgc[k] = []
        for k in ("subtitle_recognition_id", "lyrics_recognition_id"):
            if k in cfgc: cfgc[k] = ""

def edit_subtitles(draft):
    phrases = ["ТЕСТ работает", "субтитры МЕНЯЮТСЯ", "стиль СИЯНИЕ", "всё СУПЕР",
               "готово К бою", "строка ПЯТЬ", "строка ШЕСТЬ", "строка СЕМЬ"]
    changed = 0
    for tr in draft.get("tracks", []):
        if tr.get("type") != "text" or not tr.get("segments"):
            continue
        for i, seg in enumerate(tr["segments"]):
            tpl = mat_by_id(draft, seg.get("material_id"))
            if not tpl:
                continue
            dur_ms = int(seg.get("target_timerange", {}).get("duration", 1000000) / 1000)
            apply_cue(draft, tpl, phrases[i % len(phrases)].split(), dur_ms)
            changed += 1
    clear_subtitle_cache(draft)
    return changed

def edit_all_timeline_files(folder, new_id):
    """Правим субтитры во ВСЕХ файлах проекта, похожих на таймлайн (для 8.7)."""
    edited = []
    for p in folder.iterdir():
        if not p.is_file() or p.stat().st_size > 8_000_000:
            continue
        if ".bak" in p.name.lower():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "tracks" not in data:
            continue
        ch = edit_subtitles(data)
        data["name"] = "autoshorts_test"
        if "id" in data: data["id"] = new_id
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        edited.append("%s(subs:%d)" % (p.name, ch))
    return edited

def find_entry_list(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and any("fold_path" in kk.lower() for kk in v[0]):
                return obj, k
        for v in obj.values():
            r = find_entry_list(v)
            if r: return r
    return None

def register(pdir, out, new_id):
    reg = pdir / "root_meta_info.json"
    if not reg.exists():
        log("[!] root_meta_info.json ne nayden"); return
    try:
        root = json.loads(reg.read_text(encoding="utf-8"))
    except Exception as e:
        log("[!] index unreadable:", e); return
    fl = find_entry_list(root)
    if not fl:
        log("[!] entry list not found in index"); return
    cont, key = fl; entries = cont[key]
    ne = copy.deepcopy(entries[0]); now = int(time.time()*1000)
    for kk in list(ne.keys()):
        low = kk.lower()
        if "fold_path" in low: ne[kk] = str(out)
        elif low.endswith("_id") or low in ("draft_id","id"): ne[kk] = new_id
        elif "name" in low: ne[kk] = "autoshorts_test"
        elif "create" in low or "modif" in low or low.startswith("tm_"): ne[kk] = now
    reg.with_suffix(".json.bak").write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")
    entries.append(ne)
    reg.write_text(json.dumps(root, ensure_ascii=False), encoding="utf-8")
    log("[i] registered in root_meta_info.json (backup .bak made)")

def upload_log():
    text = "\n".join(LOG)
    try:
        desktop = Path.home() / "Desktop"; desktop.mkdir(exist_ok=True)
        (desktop / "capcut_test_log.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass
    try:
        b = uuid.uuid4().hex
        body = (("--%s\r\n" % b).encode() +
                b'Content-Disposition: form-data; name="file"; filename="capcut_test_log.txt"\r\n' +
                b"Content-Type: text/plain\r\n\r\n" + text.encode("utf-8") + b"\r\n" +
                ("--%s--\r\n" % b).encode())
        req = urllib.request.Request("https://tmpfiles.org/api/v1/upload", data=body,
              headers={"Content-Type": "multipart/form-data; boundary=%s" % b, "User-Agent": "Mozilla/5.0"})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        return r["data"]["url"]
    except Exception as e:
        log("[!] log upload failed:", e); return None

def main():
    log("== CapCut test v3 ==  time:", time.strftime("%Y-%m-%d %H:%M:%S"))
    pdir = find_projects_dir()
    if not pdir:
        log("[X] CapCut projects folder not found"); return
    log("[i] Projects:", pdir)
    # выбираем САМЫЙ СВЕЖИЙ проект с контентом (не пустой, не autoshorts_test)
    best, best_mtime = None, -1
    for sub in sorted(pdir.iterdir()):
        if not sub.is_dir() or sub.name == "autoshorts_test":
            continue
        dc = sub / "draft_content.json"
        tmpl = sub / "template-2.tmp"
        has_content = (dc.exists() and dc.stat().st_size > 10000) or tmpl.exists()
        if not has_content:
            continue
        mt = max([f.stat().st_mtime for f in (dc, tmpl) if f.exists()] or [0])
        log("    project '%s' mtime=%s size=%s" % (sub.name, int(mt), dc.stat().st_size if dc.exists() else 0))
        if mt > best_mtime:
            best, best_mtime = sub, mt
    if not best:
        log("[X] No non-empty project found"); return
    log("[i] SELECTED latest project: '%s'" % best.name)

    out = pdir / "autoshorts_test"
    if out.exists(): shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(best, out)
    new_id = str(uuid.uuid4()).upper()

    edited = edit_all_timeline_files(out, new_id)
    log("[i] edited timeline files:", ", ".join(edited) if edited else "NONE (!)")

    meta_path = out / "draft_meta_info.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    except Exception:
        meta = {}
    meta.update({"draft_name": "autoshorts_test", "draft_fold_path": str(out), "draft_id": new_id, "tm_draft_modified": int(time.time()*1000)})
    meta.setdefault("tm_draft_create", int(time.time()*1000))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    register(pdir, out, new_id)
    log("[OK] done. Open CapCut (restart it) and find 'autoshorts_test'.")
    try: os.startfile(str(out))
    except Exception: pass

def run():
    try:
        main()
    except Exception as e:
        import traceback
        log("[X] ERROR:", e); log(traceback.format_exc())
    url = upload_log()
    print("")
    if url:
        print("=== SKINH ETU SSYLKU (log dlya menya): ===")
        print("   ", url)
    else:
        print("Log na Rabochem stole: capcut_test_log.txt -- prishli ego mne.")
    try: input("\nNazhmi Enter dlya vyhoda...")
    except Exception: pass

if __name__ == "__main__":
    run()
