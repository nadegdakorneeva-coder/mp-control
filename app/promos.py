# -*- coding: utf-8 -*-
"""Маркетинг → Акции: в каких акциях сейчас товары на WB и Ozon.

WB — «Календарь акций» (категория «Цены и скидки»): список акций и товары, которые в них участвуют
(inAction=true). Для автоакций WB не отдаёт состав — они показываются отдельным списком.
Ozon — акции из ответа цен (/v5/product/info/prices → marketing_actions), их пишет collector.oz_prices."""
import datetime as dt
import json
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS promos(
  mp TEXT, article TEXT, promo_id TEXT, name TEXT, date_from TEXT, date_to TEXT, kind TEXT,
  price REAL, plan_price REAL, discount REAL, plan_discount REAL, loaded_at TEXT);
CREATE INDEX IF NOT EXISTS promos_mp ON promos(mp, article);
CREATE TABLE IF NOT EXISTS promo_seen(
  mp TEXT, article TEXT, promo_id TEXT, first_seen TEXT, PRIMARY KEY(mp, article, promo_id));
CREATE TABLE IF NOT EXISTS promo_list(
  mp TEXT, promo_id TEXT, name TEXT, date_from TEXT, date_to TEXT, kind TEXT, in_count INTEGER, note TEXT, loaded_at TEXT,
  PRIMARY KEY(mp, promo_id));
"""
# у Ozon в «акциях» товара бывают служебные программы — не скидки для покупателя
OZ_SERVICE = ("рассрочк", "кредит", "семплинг", "балл", "реф. программ", "лутбокс", "призолов")
CAL = "https://dp-calendar-api.wildberries.ru/api/v1/calendar"


def init(con):
    con.executescript(SCHEMA)
    con.commit()


def _mark_seen(con, mp, rows):
    """Запомнить, когда товар впервые замечен в акции — для отметки «новое» и красной цифры в меню.
    При самой первой загрузке всё считается уже просмотренным."""
    first = not con.execute("SELECT 1 FROM meta WHERE key='promos_viewed'").fetchone()
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con.executemany("INSERT OR IGNORE INTO promo_seen VALUES(?,?,?,?)",
                    [(mp, r[1].lower(), r[2], ts) for r in rows if r[6] != "service"])
    if first:
        con.execute("INSERT OR REPLACE INTO meta VALUES('promos_viewed', ?)", (ts,))


def active_counts(con):
    """Сколько артикулов сейчас в акциях (идущих, не будущих; без служебных программ Ozon) — для кружков в меню."""
    try:
        init(con)
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        out = {"wb": 0, "ozon": 0}
        for mp, n in con.execute("""SELECT mp, COUNT(DISTINCT lower(article)) FROM promos WHERE kind != 'service'
                                    AND (date_from IS NULL OR date_from <= ?) AND (date_to IS NULL OR date_to >= ?) GROUP BY mp""", (now, now)):
            out[mp] = n
        return out
    except Exception:
        return {"wb": 0, "ozon": 0}


def new_count(con):
    try:
        init(con)
        v = (con.execute("SELECT value FROM meta WHERE key='promos_viewed'").fetchone() or [None])[0]
        if not v:
            return 0
        return con.execute("""SELECT COUNT(*) FROM promos p JOIN promo_seen s ON s.mp=p.mp AND s.article=lower(p.article) AND s.promo_id=p.promo_id
                              WHERE p.kind != 'service' AND s.first_seen > ?""", (v,)).fetchone()[0]
    except Exception:
        return 0


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _d(s):
    return (s or "")[:16].replace("T", " ") or None


def load_wb(con, http, headers, log=print, raw=None):
    """http(method, url, headers, body=None, **kw) — функция запросов collector'а."""
    init(con)
    now = dt.datetime.utcnow()
    url = (f"{CAL}/promotions?startDateTime={_iso(now - dt.timedelta(days=1))}&endDateTime={_iso(now + dt.timedelta(days=30))}"
           f"&allPromo=true&limit=1000&offset=0")
    r = http("GET", url, headers, wait429=7) or {}
    promos = (r.get("data") or {}).get("promotions") or []
    if raw:
        raw("wb_promotions_sample.json", promos[:10])
    nm2art = {str(a): b for a, b in con.execute("SELECT mp_sku, article FROM products WHERE mp='wb'")}
    rows, lst = [], []
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for p in promos:
        pid, kind = str(p.get("id")), p.get("type") or ""
        n, note = 0, ""
        if kind == "auto":
            note = "автоакция: WB не отдаёт состав участников через API"
        else:
            off = 0
            while True:
                time.sleep(0.7)   # лимит календаря — 10 запросов за 6 секунд
                try:
                    q = http("GET", f"{CAL}/promotions/nomenclatures?promotionID={pid}&inAction=true&limit=1000&offset={off}",
                             headers, wait429=7) or {}
                except Exception as e:
                    note = f"состав не получен: {str(e)[:120]}"
                    break
                items = (q.get("data") or {}).get("nomenclatures") or []
                for it in items:
                    art = nm2art.get(str(it.get("id")), str(it.get("id")))
                    rows.append(("wb", art, pid, p.get("name"), _d(p.get("startDateTime")), _d(p.get("endDateTime")), kind,
                                 it.get("price"), it.get("planPrice"), it.get("discount"), it.get("planDiscount"), ts))
                    n += 1
                if len(items) < 1000:
                    break
                off += 1000
        lst.append(("wb", pid, p.get("name"), _d(p.get("startDateTime")), _d(p.get("endDateTime")), kind, n, note, ts))
    con.execute("DELETE FROM promos WHERE mp='wb'")
    con.execute("DELETE FROM promo_list WHERE mp='wb'")
    con.executemany("INSERT INTO promos VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT OR REPLACE INTO promo_list VALUES(?,?,?,?,?,?,?,?,?)", lst)
    _mark_seen(con, "wb", rows)
    con.execute("INSERT OR REPLACE INTO meta VALUES('promos_wb_checked', ?)", (dt.datetime.now().strftime("%d.%m.%Y %H:%M"),))
    con.commit()
    log(f"WB акции: {len(promos)} акций, товаров в акциях: {len(rows)}")


def store_ozon(con, items):
    """items — ответ /v5/product/info/prices; пишем действующие и ближайшие (14 дней) акции товара."""
    init(con)
    now = dt.datetime.utcnow()
    soon = _iso(now + dt.timedelta(days=14))
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows, names = [], {}
    for it in items:
        for a in ((it.get("marketing_actions") or {}).get("actions") or []):
            df, dto = a.get("date_from") or "", a.get("date_to") or ""
            if (dto and dto < _iso(now)) or (df and df > soon):
                continue
            title = (a.get("title") or "").strip()
            kind = "service" if any(w in title.lower() for w in OZ_SERVICE) else "discount"
            pid = title.lower()
            rows.append(("ozon", it.get("offer_id"), pid, title, _d(df), _d(dto), kind, None, None, a.get("value"), None, ts))
            names.setdefault(pid, [title, _d(df), _d(dto), kind, 0])[4] += 1
    con.execute("DELETE FROM promos WHERE mp='ozon'")
    con.execute("DELETE FROM promo_list WHERE mp='ozon'")
    con.executemany("INSERT INTO promos VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    _mark_seen(con, "ozon", rows)
    con.executemany("INSERT OR REPLACE INTO promo_list VALUES('ozon',?,?,?,?,?,?,'',?)",
                    [(k, v[0], v[1], v[2], v[3], v[4], ts) for k, v in names.items()])
    con.execute("INSERT OR REPLACE INTO meta VALUES('promos_oz_checked', ?)", (dt.datetime.now().strftime("%d.%m.%Y %H:%M"),))
    con.commit()


def report(con, mark_viewed=False):
    init(con)
    m = lambda k: (con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone() or [None])[0]
    viewed = m("promos_viewed") or "9999"
    seen = {(r[0], r[1], r[2]): r[3] for r in con.execute("SELECT * FROM promo_seen")}
    arts = {}
    for mp, a in con.execute("""SELECT DISTINCT mp, article FROM products WHERE article IS NOT NULL
                                UNION SELECT DISTINCT mp, article FROM promos"""):
        arts.setdefault(a.lower(), {"article": a, "wb": [], "ozon": [], "has": {}})["has"][mp] = True
    for r in con.execute("SELECT * FROM promos ORDER BY date_from"):
        x = arts.setdefault(r["article"].lower(), {"article": r["article"], "wb": [], "ozon": [], "has": {r["mp"]: True}})
        d = {k: r[k] for k in ("promo_id", "name", "date_from", "date_to", "kind", "price", "plan_price", "discount", "plan_discount")}
        fs = seen.get((r["mp"], r["article"].lower(), r["promo_id"]))
        d["new"] = bool(fs and fs > viewed and r["kind"] != "service")
        d["first_seen"] = fs
        x[r["mp"]].append(d)
    # остатки: товары без остатка и без акций — в конец
    stock = {}
    try:
        for mp, a, q in con.execute("""SELECT mp, lower(article), SUM(qty) FROM stocks s WHERE snap_date=(SELECT MAX(snap_date) FROM stocks s2 WHERE s2.mp=s.mp)
                                       GROUP BY 1, 2"""):
            stock[(mp, a)] = q or 0
    except Exception:
        pass
    rows = []
    for k, x in arts.items():
        x["stock"] = {mp: stock.get((mp, k)) for mp in ("wb", "ozon")}
        rows.append(x)
    rows.sort(key=lambda x: (-(len(x["wb"]) + len([p for p in x["ozon"] if p["kind"] != "service"])), x["article"]))
    lists = [dict(r) for r in con.execute("SELECT * FROM promo_list ORDER BY mp, date_from")]
    if mark_viewed:
        con.execute("INSERT OR REPLACE INTO meta VALUES('promos_viewed', ?)", (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        con.commit()
    return {"rows": rows, "promos": lists, "wb_checked": m("promos_wb_checked"), "oz_checked": m("promos_oz_checked"),
            "wb_error": m("promos_wb_error")}
