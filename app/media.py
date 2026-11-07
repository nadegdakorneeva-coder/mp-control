# -*- coding: utf-8 -*-
"""Маркетинг → Фотоконтент: фото карточек WB и Ozon, замена фото WB прямо из программы.

Чтение — основной ключ WB с категорией «Контент» и ключ Ozon. Запись (замена фото WB) — ключ из
[wb] content_token (категория «Контент» без «только чтение»), если его нет — основной ключ.
Перед любой заменой текущие фото карточки скачиваются в data/media_backup/<nmID>/<время>/ —
по ним работает «Откатить» (загружает старые файлы обратно на те же места)."""
import datetime as dt
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import uuid

import db

WB_CONTENT = "https://content-api.wildberries.ru"
BACKUP_DIR = os.path.join(db.DATA_DIR, "media_backup")
KEEP_BACKUPS = 5
MAX_FILE = 20 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards_media(
  mp TEXT NOT NULL, article TEXT NOT NULL, nm_id TEXT, title TEXT, photos TEXT, video TEXT, updated TEXT,
  PRIMARY KEY(mp, article));
CREATE TABLE IF NOT EXISTS media_log(
  id INTEGER PRIMARY KEY, ts TEXT, user TEXT, mp TEXT, article TEXT, nm_id TEXT, action TEXT, detail TEXT, ok INTEGER);
"""


def init(con):
    con.executescript(SCHEMA)
    con.commit()


def _cfg():
    return db.config()


def wb_token(write=False):
    c = _cfg()
    main = c.get("wb", "token", fallback="").strip()
    return (c.get("wb", "content_token", fallback="").strip() or main) if write else main


def _req(method, url, headers, body=None, raw=None, ctype=None, timeout=60):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers)
    if data is not None:
        h["Content-Type"] = ctype or "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read()
                return r.status, (json.loads(txt) if txt[:1] in (b"{", b"[") else txt)
        except urllib.error.HTTPError as e:
            txt = e.read()[:800].decode("utf-8", "replace")
            if e.code == 429 and attempt < 3:
                time.sleep(6)
                continue
            return e.code, txt
        except Exception as e:
            if attempt < 3:
                time.sleep(3)
                continue
            return 0, str(e)
    return 0, "нет ответа"


# ---------------- загрузка списка фото ----------------
def _photo(p):
    """WB отдаёт несколько размеров; храним большую (для замены и бэкапа) и маленькую (для плиток)."""
    return {"big": p.get("big") or p.get("hq") or "", "small": p.get("c246x328") or p.get("tm") or p.get("square") or p.get("big") or ""}


def _wb_store(con, card):
    con.execute("INSERT OR REPLACE INTO cards_media VALUES('wb',?,?,?,?,?,?)",
                (card.get("vendorCode") or str(card.get("nmID")), str(card.get("nmID")), card.get("title") or "",
                 json.dumps([_photo(p) for p in card.get("photos") or []], ensure_ascii=False), card.get("video") or "",
                 dt.datetime.now().strftime("%Y-%m-%d %H:%M")))


def load_wb(con, log=print, text=None):
    """Все карточки WB (или одна — по nmID/артикулу в text) с фото."""
    init(con)
    tok = wb_token()
    if not tok:
        raise RuntimeError("не задан ключ WB")
    cursor, n, seen = {"limit": 100}, 0, set()
    for _ in range(200):
        body = {"settings": {"cursor": cursor, "filter": {"withPhoto": -1, **({"textSearch": str(text)} if text else {})}}}
        code, r = _req("POST", f"{WB_CONTENT}/content/v2/get/cards/list", {"Authorization": tok}, body)
        if code != 200:
            raise RuntimeError(f"WB карточки: HTTP {code} {str(r)[:200]}" + (" — у ключа нет категории «Контент»" if code in (401, 403) else ""))
        cards = r.get("cards") or []
        if n == 0 and cards and not text:
            try:
                os.makedirs(os.path.join(db.DATA_DIR, "raw"), exist_ok=True)
                json.dump(cards[:2], open(os.path.join(db.DATA_DIR, "raw", "wb_cards_sample.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            except Exception:
                pass
        for c in cards:
            _wb_store(con, c)
            seen.add(str(c.get("nmID")))
        n += len(cards)
        cur = r.get("cursor") or {}
        if text or len(cards) < cursor["limit"] or not cur.get("nmID"):
            break
        cursor = {"limit": 100, "updatedAt": cur.get("updatedAt"), "nmID": cur.get("nmID")}
        time.sleep(0.7)
    if not text and seen:   # убрать удалённые карточки
        con.execute(f"DELETE FROM cards_media WHERE mp='wb' AND nm_id NOT IN ({','.join('?' * len(seen))})", list(seen))
    con.execute("INSERT OR REPLACE INTO meta VALUES('media_checked', ?)", (dt.datetime.now().strftime("%d.%m.%Y %H:%M"),))
    con.commit()
    log(f"WB фото карточек: {n}")
    return n


def _oz(path, body):
    c = _cfg()
    h = {"Client-Id": c.get("ozon", "client_id", fallback="").strip(), "Api-Key": c.get("ozon", "api_key", fallback="").strip()}
    if not h["Client-Id"] or not h["Api-Key"]:
        raise RuntimeError("не задан ключ Ozon")
    code, r = _req("POST", "https://api-seller.ozon.ru" + path, h, body)
    if code != 200:
        raise RuntimeError(f"Ozon {path}: HTTP {code} {str(r)[:200]}")
    return r


def load_ozon(con, log=print):
    """Фото товаров Ozon (только просмотр): /v3/product/info/list по offer_id."""
    init(con)
    oz = _oz
    arts = [r[0] for r in con.execute("SELECT DISTINCT article FROM products WHERE mp='ozon' AND article IS NOT NULL")]
    n = 0
    for i in range(0, len(arts), 100):
        r = oz("/v3/product/info/list", {"offer_id": arts[i:i + 100]}) or {}
        for it in r.get("items") or []:
            imgs = it.get("images") or []
            prim = it.get("primary_image") or []
            prim = [prim] if isinstance(prim, str) else prim
            urls = [u for u in list(prim) + list(imgs) if u]
            urls = list(dict.fromkeys(urls))
            con.execute("INSERT OR REPLACE INTO cards_media VALUES('ozon',?,?,?,?,?,?)",
                        (it.get("offer_id"), str(it.get("id") or ""), it.get("name") or "",
                         json.dumps([{"big": u, "small": u} for u in urls], ensure_ascii=False), "",
                         dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
            n += 1
    con.commit()
    log(f"Ozon фото товаров: {n}")


# ---------------- отчёт для страницы ----------------
def report(con):
    init(con)
    rows = []
    for r in con.execute("SELECT * FROM cards_media ORDER BY article, mp"):
        x = dict(r)
        x["photos"] = json.loads(x["photos"] or "[]")
        x["backups"] = backups(x["nm_id"]) if x["mp"] == "wb" else []
        rows.append(x)
    last = [dict(r) for r in con.execute("SELECT * FROM media_log ORDER BY id DESC LIMIT 30")]
    m = lambda k: (con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone() or [None])[0]
    c = _cfg()
    return {"rows": rows, "log": last, "checked": m("media_checked"), "error": m("media_error"),
            "write_key": bool(c.get("wb", "content_token", fallback="").strip())}


# ---------------- резервные копии ----------------
def backups(nm):
    d = os.path.join(BACKUP_DIR, str(nm))
    if not os.path.isdir(d):
        return []
    out = []
    for ts in sorted(os.listdir(d), reverse=True):
        files = sorted(os.listdir(os.path.join(d, ts)), key=lambda x: int(x.split(".")[0]) if x.split(".")[0].isdigit() else 999)
        out.append({"ts": ts, "count": len(files)})
    return out


def _download(url):
    code, data = _req("GET", url, {}, timeout=60)
    return data if code == 200 and isinstance(data, bytes) else None


def backup_card(con, nm):
    """Скачать текущие фото карточки (одна копия на 10 минут — серия замен подряд не плодит копии)."""
    r = con.execute("SELECT photos FROM cards_media WHERE mp='wb' AND nm_id=?", (str(nm),)).fetchone()
    photos = json.loads(r["photos"] or "[]") if r else []
    if not photos:
        return None
    root = os.path.join(BACKUP_DIR, str(nm))
    os.makedirs(root, exist_ok=True)
    ex = sorted(os.listdir(root))
    if ex and (time.time() - os.path.getmtime(os.path.join(root, ex[-1]))) < 600:
        return ex[-1]
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = os.path.join(root, ts)
    os.makedirs(d)
    for i, p in enumerate(photos, 1):
        data = _download(p["big"])
        if data:
            ext = os.path.splitext(p["big"].split("?")[0])[1] or ".jpg"
            open(os.path.join(d, f"{i}{ext}"), "wb").write(data)
    for old in sorted(os.listdir(root))[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    return ts


# ---------------- запись ----------------
def _log(con, user, mp, art, nm, action, detail, ok):
    con.execute("INSERT INTO media_log(ts, user, mp, article, nm_id, action, detail, ok) VALUES(?,?,?,?,?,?,?,?)",
                (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, mp, art, str(nm), action, detail, 1 if ok else 0))
    con.commit()


def _upload_wb(nm, n, data, filename, ctype):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"uploadfile\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype or 'image/jpeg'}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return _req("POST", f"{WB_CONTENT}/content/v3/media/file",
                {"Authorization": wb_token(write=True), "X-Nm-Id": str(nm), "X-Photo-Number": str(n)},
                raw=body, ctype=f"multipart/form-data; boundary={b}")


def replace_photo(con, user, nm, n, data, filename, ctype):
    """Записать файл на место n (1 — главное фото). n больше числа фото — добавится в конец."""
    init(con)
    if not data:
        raise ValueError("пустой файл")
    if len(data) > MAX_FILE:
        raise ValueError("файл больше 20 МБ")
    r = con.execute("SELECT article FROM cards_media WHERE mp='wb' AND nm_id=?", (str(nm),)).fetchone()
    art = r["article"] if r else ""
    ts = backup_card(con, nm)
    code, resp = _upload_wb(nm, n, data, filename, ctype)
    ok = code == 200 and not (isinstance(resp, dict) and resp.get("error"))
    err = "" if ok else (resp.get("errorText") if isinstance(resp, dict) else str(resp))[:300]
    if code in (401, 403):
        err = "нет права записи: нужен ключ WB с категорией «Контент» без «только чтение» (Настройки → WB: ключ для изменения фото)"
    _log(con, user, "wb", art, nm, f"замена фото {n}", filename + ("" if ok else f" — {err}"), ok)
    if not ok:
        raise RuntimeError(f"WB не принял фото: {err or code}")
    return {"ok": True, "backup": ts}


def refresh_card(con, nm):
    """Перечитать одну карточку после замены (WB обрабатывает фото несколько секунд)."""
    load_wb(con, log=lambda *a: None, text=str(nm))
    r = con.execute("SELECT photos FROM cards_media WHERE mp='wb' AND nm_id=?", (str(nm),)).fetchone()
    return {"photos": json.loads(r["photos"] or "[]") if r else []}


def keep_first(con, user, nm, k):
    """Оставить первые k фото (лишние старые удалить): /content/v3/media/save со ссылками на первые k."""
    refresh_card(con, nm)
    r = con.execute("SELECT article, photos FROM cards_media WHERE mp='wb' AND nm_id=?", (str(nm),)).fetchone()
    photos = json.loads(r["photos"] or "[]") if r else []
    if len(photos) <= k:
        return {"ok": True, "removed": 0}
    backup_card(con, nm)
    code, resp = _req("POST", f"{WB_CONTENT}/content/v3/media/save", {"Authorization": wb_token(write=True)},
                      {"nmId": int(nm), "data": [p["big"] for p in photos[:k]]})
    ok = code == 200 and not (isinstance(resp, dict) and resp.get("error"))
    _log(con, user, "wb", r["article"] if r else "", nm, f"оставить {k} фото", f"удалено {len(photos) - k}", ok)
    if not ok:
        raise RuntimeError(f"WB: {str(resp)[:300]}")
    return {"ok": True, "removed": len(photos) - k}


def restore(con, user, nm, ts):
    """Откатить: загрузить фото из резервной копии на те же места, лишние новые удалить."""
    d = os.path.join(BACKUP_DIR, str(nm), os.path.basename(ts))
    if not os.path.isdir(d):
        raise ValueError("резервная копия не найдена")
    files = sorted([f for f in os.listdir(d) if f.split(".")[0].isdigit()], key=lambda x: int(x.split(".")[0]))
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        ctype = {".webp": "image/webp", ".png": "image/png"}.get(ext, "image/jpeg")
        code, resp = _upload_wb(nm, int(f.split(".")[0]), open(os.path.join(d, f), "rb").read(), f, ctype)
        if code != 200:
            _log(con, user, "wb", "", nm, "откат", f"ошибка на фото {f}: {str(resp)[:200]}", False)
            raise RuntimeError(f"WB не принял фото {f}: {str(resp)[:200]}")
        time.sleep(0.7)
    _log(con, user, "wb", "", nm, "откат", f"копия {ts}: {len(files)} фото", True)
    time.sleep(3)
    try:
        keep_first(con, user, nm, len(files))
    except Exception:
        pass
    return {"ok": True, "count": len(files)}
