# -*- coding: utf-8 -*-
"""Контроль цен: минимальная розничная цена (МРЦ, в коде — таблица rrp) против цены на сайте.

WB: цена для покупателя = ваша текущая цена из API (до СПП) × (1 − обычная СПП). Обычная СПП — медиана
по последним заказам (1 − finishedPrice / priceWithDisc): отдельный заказ бывает с персональной скидкой покупателя
и сильно ниже витрины, поэтому одному последнему заказу не верим. Ozon: цена с акциями из API, иначе последний заказ.
"""
import datetime as dt
import io
import re

MP_NAMES = {"wb": "Wildberries", "ozon": "Ozon"}


def init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS rrp(mp TEXT NOT NULL DEFAULT 'all', article TEXT NOT NULL, price REAL NOT NULL,
                                   updated_at TEXT, PRIMARY KEY(mp, article));
    CREATE TABLE IF NOT EXISTS cur_prices(mp TEXT NOT NULL, article TEXT NOT NULL, mp_sku TEXT,
                   seller_price REAL, buyer_price REAL, base_price REAL, discount REAL, ts TEXT, PRIMARY KEY(mp, article));
    """)
    con.commit()
    # стартовые МРЦ из прайс-листа MOCHEQI Professional (колонка «МРЦ»), один раз, если таблица пустая
    import json, os
    seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rrp_seed.json")
    if os.path.exists(seed) and not con.execute("SELECT 1 FROM rrp").fetchone() and \
            not con.execute("SELECT 1 FROM meta WHERE key='rrp_seeded'").fetchone():
        save_rrp(con, json.load(open(seed, encoding="utf-8")))
        con.execute("INSERT OR REPLACE INTO meta VALUES('rrp_seeded', '1')")
        con.commit()


def _meta(con, k, d=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r and r[0] is not None else d


def settings(con):
    return {"tolerance": float(_meta(con, "price_tolerance", 0)), "warn": float(_meta(con, "price_warn", 5)),
            "hours": int(float(_meta(con, "price_hours", 24)))}


def save_settings(con, b):
    if "tolerance" in b:
        con.execute("INSERT OR REPLACE INTO meta VALUES('price_tolerance', ?)", (str(max(0.0, float(b["tolerance"]))),))
    if "warn" in b:
        con.execute("INSERT OR REPLACE INTO meta VALUES('price_warn', ?)", (str(max(0.0, float(b["warn"]))),))
    if "hours" in b:
        con.execute("INSERT OR REPLACE INTO meta VALUES('price_hours', ?)", (str(max(1, int(float(b["hours"])))),))
    con.commit()
    return settings(con)


def norm_art(a):
    return (a or "").strip()


def save_rrp(con, rows, replace=False):
    """rows: [{article, price, mp?}]"""
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if replace:
        con.execute("DELETE FROM rrp")
    n = 0
    for r in rows:
        a, mp = norm_art(r.get("article")), (r.get("mp") or "all")
        if not a:
            continue
        p = r.get("price")
        if p in (None, "", 0, "0"):
            con.execute("DELETE FROM rrp WHERE mp=? AND article=?", (mp, a))
            continue
        con.execute("INSERT OR REPLACE INTO rrp VALUES(?,?,?,?)", (mp, a, float(str(p).replace(",", ".").replace(" ", "")), now))
        n += 1
    con.commit()
    return n


def parse_rrp_text(text):
    """Строки «артикул  цена» (разделитель — пробелы, ; или таб). Цена — последнее число в строке."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.+?)[\s;\t]+([\d\s]+(?:[.,]\d+)?)\s*(?:₽|руб\.?|р\.?)?$", line)
        if m:
            price = float(m.group(2).replace(" ", "").replace(",", "."))
            if price > 0:
                rows.append({"article": m.group(1).strip(" ;\t"), "price": price})
    return rows


def parse_rrp_xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    head_i, a_col, p_col = None, None, None
    for i, r in enumerate(rows[:15]):
        cells = [str(c or "").strip().lower() for c in r]
        for j, c in enumerate(cells):
            if a_col is None and ("артикул" in c or c in ("sku", "код")):
                a_col = j
            if p_col is None and ("мрц" in c or "ррц" in c or "рекоменд" in c or "минимальн" in c or c.startswith("цена")):
                p_col = j
        if a_col is not None and p_col is not None:
            head_i = i
            break
    if head_i is None:
        head_i, a_col, p_col = -1, 0, 1
    out = []
    for r in rows[head_i + 1:]:
        if r is None or len(r) <= max(a_col, p_col):
            continue
        a, p = r[a_col], r[p_col]
        try:
            p = float(str(p).replace(" ", "").replace(",", "."))
        except (TypeError, ValueError):
            continue
        if a and p > 0:
            out.append({"article": str(a).strip(), "price": p})
    return out


SPP_ORDERS = 10        # по скольким последним заказам считать обычную СПП WB


def report(con, q=None):
    q = q or {}
    s = settings(con)
    tol, hours = s["tolerance"], s["hours"]
    since = (dt.datetime.now() - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    since_day = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    rrp = {}
    for r in con.execute("SELECT * FROM rrp"):
        rrp[(r["mp"], r["article"].lower())] = r["price"]
    names, skus = {}, {}
    for r in con.execute("SELECT mp, article, MAX(name) name, MAX(mp_sku) sku FROM products WHERE article IS NOT NULL GROUP BY 1, 2"):
        if r["name"]:
            names[(r["mp"], r["article"].lower())] = r["name"]
        skus[(r["mp"], r["article"].lower())] = r["sku"]
    cur = {(r["mp"], (r["article"] or "").lower()): dict(r) for r in con.execute("SELECT * FROM cur_prices")}
    # остатки из последнего снимка (если он свежий): товара нет в наличии — цену на витрине не проверяем
    stock = {}
    fresh = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    for r in con.execute("""SELECT mp, lower(article) a, SUM(qty) q FROM stocks s WHERE article IS NOT NULL
                            AND snap_date = (SELECT MAX(snap_date) FROM stocks s2 WHERE s2.mp = s.mp) AND snap_date >= ?
                            GROUP BY 1, 2""", (fresh,)):
        stock[(r["mp"], r["a"])] = r["q"] or 0
    stock_mps = {mp for (mp, _) in stock}
    # последние заказы за неделю: последний, минимум за окно часов
    last, win, spps = {}, {}, {}
    for r in con.execute("""SELECT mp, article, mp_sku, REPLACE(COALESCE(ts, dt), ' ', 'T') ts, dt, price, paid, is_cancel FROM orders
                            WHERE dt >= ? AND article IS NOT NULL AND paid > 0 ORDER BY REPLACE(COALESCE(ts, dt), ' ', 'T')""", (since_day,)):
        k = (r["mp"], r["article"].lower())
        last[k] = r
        if r["mp"] == "wb" and r["price"] and r["price"] > r["paid"] and not r["is_cancel"]:
            spps.setdefault(k, []).append(1 - r["paid"] / r["price"])
        if (r["ts"] or r["dt"]) >= since:
            w = win.setdefault(k, {"min": r["paid"], "n": 0, "sum": 0.0})
            w["min"] = min(w["min"], r["paid"]); w["n"] += 1; w["sum"] += r["paid"]
    arts = {}
    for (mp, a) in set(last) | set(cur) | {k for k in rrp if k[0] != "all"}:
        arts[(mp, a)] = True
    for (mp, a) in [k for k in rrp if k[0] == "all"]:
        for m in ("wb", "ozon"):
            if (m, a) in last or (m, a) in cur:
                arts[(m, a)] = True
    rows = []
    for (mp, a) in arts:
        if q.get("mp") and q["mp"] != mp:
            continue
        target = rrp.get((mp, a)) or rrp.get(("all", a))
        lr, c, w = last.get((mp, a)), cur.get((mp, a)), win.get((mp, a))
        art = (lr["article"] if lr else None) or (c["article"] if c else None) or a
        seller = (c or {}).get("seller_price") or (lr["price"] if lr else None)
        buyer_api = (c or {}).get("buyer_price")
        buyer = lr["paid"] if lr else None
        spp = None
        if mp == "wb":
            sp = sorted((spps.get((mp, a)) or [])[-SPP_ORDERS:])
            if sp:
                spp = sp[len(sp) // 2] if len(sp) % 2 else (sp[len(sp) // 2 - 1] + sp[len(sp) // 2]) / 2
            if spp is not None and seller:
                buyer = round(seller * (1 - spp))   # что видит обычный покупатель сейчас
        src = (c or {}).get("buyer_src")
        if mp == "ozon" and buyer_api:
            buyer = buyer_api        # Ozon: цена на сайте по индексу цен (со скидкой за счёт Ozon), иначе предельная цена
            if src in ("index", "similar", "median") and seller and buyer < seller:
                spp = 1 - buyer / seller
        status, reason, dev = "norrp", "", None
        in_stock = stock.get((mp, a), 0) if mp in stock_mps else None
        if target and in_stock == 0:
            status, reason = "nostock", "нет на складах — на сайте не продаётся"
        elif target:
            if not buyer and seller and seller < target * (1 - tol / 100):
                status, dev, reason = "low", (seller - target) / target * 100, "ваша цена ниже МРЦ (заказов не было)"
            elif not buyer:
                status = "nodata"
            else:
                dev = (buyer - target) / target * 100
                if dev < -tol:
                    status = "low"
                    if seller and seller < target * (1 - tol / 100):
                        reason = "ваша цена ниже МРЦ"
                    elif mp == "wb":
                        reason = "СПП WB"
                    else:
                        reason = "акции Ozon"
                elif dev < s["warn"]:
                    status = "near"          # выше МРЦ, но запас меньше порога предупреждения
                else:
                    status = "ok"
        sku = (lr["mp_sku"] if lr else None) or skus.get((mp, a)) or (c["mp_sku"] if (c and mp == "wb") else None)
        rows.append({"mp": mp, "article": art, "name": names.get((mp, a), ""), "sku": sku,
                     "product_id": (c or {}).get("mp_sku") if mp == "ozon" else None, "rrp": target, "seller_price": seller,
                     "buyer_price": buyer, "last_order": (lr["ts"] or lr["dt"]) if lr else None,
                     "min_window": w["min"] if w else None, "orders_window": w["n"] if w else 0,
                     "api_ts": (c or {}).get("ts"), "dev": dev, "status": status, "reason": reason,
                     "spp": spp * 100 if spp is not None else None, "spp_n": len((spps.get((mp, a)) or [])[-SPP_ORDERS:]),
                     "last_paid": lr["paid"] if lr else None, "stock": in_stock, "buyer_src": src if mp == "ozon" else None,
                     "order_below": bool(target and w and w["min"] < target * (1 - tol / 100))})
    order = {"low": 0, "near": 1, "nodata": 2, "ok": 3, "nostock": 4, "norrp": 5}
    rows.sort(key=lambda r: (order[r["status"]], r["dev"] if r["dev"] is not None else 0, r["article"]))
    cnt = {k: sum(1 for r in rows if r["status"] == k) for k in order}
    return {"rows": rows, "counts": cnt, "settings": s, "checked": _meta(con, "prices_checked"),
            "wb_prices_access": _meta(con, "wb_prices_access"), "rrp_count": con.execute("SELECT COUNT(*) FROM rrp").fetchone()[0]}


def alert_count(con):
    try:
        if not con.execute("SELECT 1 FROM rrp LIMIT 1").fetchone():
            return 0
        return report(con)["counts"]["low"]
    except Exception:
        return 0
