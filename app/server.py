# -*- coding: utf-8 -*-
"""Локальный веб-сервер дашборда: http://127.0.0.1:8766"""
import base64, datetime as dt, io, json, os, subprocess, sys, threading, time, uuid, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import db, metrics, auth, wbplan, prices, monthly, today, supplies, appconfig, media, promos

PORT = 8766
LAN_URL = None  # адрес для других устройств в сети, если включён [server] network = 1
STATIC = os.path.join(db.APP_DIR, "static")
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon"}


# ---------------- вспомогательное ----------------
def d(s):
    return dt.date.fromisoformat(s)


def prev_period(f, t):
    a, b = d(f), d(t)
    n = (b - a).days + 1
    return (a - dt.timedelta(days=n)).isoformat(), (a - dt.timedelta(days=1)).isoformat()


def months_between(f, t):
    a, b = d(f).replace(day=1), d(t).replace(day=1)
    res = []
    while a <= b:
        res.append(a.strftime("%Y-%m"))
        a = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return res


def filters(q):
    flt = {}
    if q.get("mp"):
        flt["mp"] = q["mp"]
    if q.get("articles"):
        flt["articles"] = [a for a in q["articles"].split("|") if a]
    if q.get("scheme") in ("FBO", "FBS"):
        flt["scheme"] = q["scheme"]
    return flt


def guess_mp(sku):
    s = str(sku).strip()
    return "ozon" if len(s) >= 10 else "wb"


# ---------------- себестоимость ----------------
def import_costs_rows(con, rows, valid_from="2000-01-01", replace_all=False):
    if replace_all:
        con.execute("DELETE FROM costs")
    n = 0
    for r in rows:
        sku = str(r.get("mp_sku") or "").strip()
        if not sku:
            continue
        con.execute("""INSERT OR REPLACE INTO costs(mp, mp_sku, article, barcode, scheme, cost, fulfillment, nds, valid_from)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (r.get("mp") or guess_mp(sku), sku, (r.get("article") or "").strip(),
                     str(r.get("barcode") or "").strip(), (r.get("scheme") or "FBO").upper(),
                     num(r.get("cost")), num(r.get("fulfillment")), num(r.get("nds")),
                     r.get("valid_from") or valid_from))
        n += 1
    con.commit()
    return n


def num(v):
    try:
        return float(str(v).replace(" ", "").replace(",", ".")) if v not in (None, "", "-") else 0.0
    except ValueError:
        return 0.0


def parse_costs_xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    rows = []
    for ws in wb.worksheets:
        title = ws.title.upper()
        scheme = "FBS" if ("ФБС" in title or "FBS" in title) else "FBO"
        header_idx, cols = None, {}
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            cells = [str(c).strip().lower() if c is not None else "" for c in row]
            if header_idx is None:
                if any("артикул продавца" in c for c in cells):
                    header_idx = i
                    for j, c in enumerate(cells):
                        if "артикул продавца" in c: cols["article"] = j
                        elif "артикул маркетплейса" in c: cols["mp_sku"] = j
                        elif "баркод" in c: cols["barcode"] = j
                        elif "себестоимость" in c: cols["cost"] = j
                        elif "фулфилмент" in c: cols["fulfillment"] = j
                        elif c.startswith("ндс"): cols["nds"] = j
                continue
            rec = {k: row[j] if j < len(row) else None for k, j in cols.items()}
            if rec.get("mp_sku"):
                rec["scheme"] = scheme
                rows.append(rec)
    return rows


def costs_list(con, q):
    sql = """SELECT c.*, COALESCE(p.name, '') AS name FROM costs c
             LEFT JOIN products p ON p.mp_sku = c.mp_sku
             WHERE c.valid_from = (SELECT MAX(valid_from) FROM costs c2 WHERE c2.mp_sku = c.mp_sku AND c2.scheme = c.scheme)"""
    args = []
    if q.get("scheme"):
        sql += " AND c.scheme = ?"; args.append(q["scheme"])
    if q.get("mp"):
        sql += " AND c.mp = ?"; args.append(q["mp"])
    if q.get("empty") == "1":
        sql += " AND (c.cost IS NULL OR c.cost = 0)"
    sql += " ORDER BY c.article, c.mp"
    res = [dict(r) for r in con.execute(sql, args)]
    # товары, которые продаются, но которых нет в таблице себестоимости
    known = {(r["mp_sku"]) for r in con.execute("SELECT DISTINCT mp_sku FROM costs")}
    missing = [dict(r) for r in con.execute("""SELECT f.mp, f.mp_sku, MAX(f.article) article, SUM(f.qty) qty
        FROM fin f WHERE f.metric='realization' AND f.dt >= date('now','-60 day') GROUP BY f.mp, f.mp_sku""")
               if r["mp_sku"] not in known]
    return {"rows": res, "missing": missing}


# ---------------- операции / ДДС ----------------
OP_FIELDS = ["kind", "amount", "nds", "pay_date", "accrual_date", "distribute_months", "account_id",
             "to_account_id", "category_id", "counterparty", "project", "purpose", "is_planned", "official"]


def add_months(s, k):
    x = d(s)
    m = x.month - 1 + k
    y = x.year + m // 12
    m = m % 12 + 1
    import calendar
    return dt.date(y, m, min(x.day, calendar.monthrange(y, m)[1])).isoformat()


def save_operation(con, body, op_id=None):
    vals = {k: body.get(k) for k in OP_FIELDS}
    vals["amount"] = abs(num(vals["amount"]))
    vals["nds"] = num(vals.get("nds"))
    vals["distribute_months"] = int(num(vals.get("distribute_months")) or 1)
    vals["accrual_date"] = vals.get("accrual_date") or vals["pay_date"]
    for k in ("is_planned", "official"):
        vals[k] = 1 if vals.get(k) else 0
    for k in ("account_id", "to_account_id", "category_id"):
        vals[k] = int(vals[k]) if vals.get(k) not in (None, "", 0, "0") else None
    if op_id:
        con.execute(f"UPDATE operations SET {', '.join(k + '=?' for k in OP_FIELDS)} WHERE id=?",
                    [vals[k] for k in OP_FIELDS] + [op_id])
        con.commit()
        return [op_id]
    repeat = int(num(body.get("repeat_months")) or 1)
    series = uuid.uuid4().hex[:8] if repeat > 1 else None
    ids = []
    for i in range(repeat):
        v = dict(vals)
        if i:
            v["pay_date"] = add_months(vals["pay_date"], i)
            v["accrual_date"] = add_months(vals["accrual_date"], i)
            v["is_planned"] = 1 if d(v["pay_date"]) > dt.date.today() else v["is_planned"]
        cur = con.execute(f"INSERT INTO operations({', '.join(OP_FIELDS)}, series_id) VALUES({', '.join('?' * len(OP_FIELDS))}, ?)",
                          [v[k] for k in OP_FIELDS] + [series])
        ids.append(cur.lastrowid)
    con.commit()
    return ids


def operations_list(con, q):
    sql = """SELECT o.*, c.name AS category, a.name AS account, a2.name AS to_account
             FROM operations o LEFT JOIN categories c ON c.id = o.category_id
             LEFT JOIN accounts a ON a.id = o.account_id LEFT JOIN accounts a2 ON a2.id = o.to_account_id
             WHERE o.pay_date BETWEEN ? AND ?"""
    args = [q.get("from", "2000-01-01"), q.get("to", "2100-01-01")]
    for key, col in (("kind", "o.kind"), ("account_id", "o.account_id"), ("category_id", "o.category_id")):
        if q.get(key):
            sql += f" AND {col} = ?"; args.append(q[key])
    sql += " ORDER BY o.pay_date DESC, o.id DESC"
    return [dict(r) for r in con.execute(sql, args)]


def account_balances(con, upto, planned):
    res = {}
    for a in con.execute("SELECT * FROM accounts"):
        bal = a["opening_balance"] or 0
        for o in con.execute("""SELECT kind, amount, account_id, to_account_id FROM operations
                                WHERE pay_date <= ? AND pay_date >= ? AND (is_planned = 0 OR ?)
                                AND (account_id = ? OR to_account_id = ?)""",
                             (upto, a["opening_date"] or "2000-01-01", 1 if planned else 0, a["id"], a["id"])):
            if o["kind"] == "income" and o["account_id"] == a["id"]:
                bal += o["amount"]
            elif o["kind"] == "expense" and o["account_id"] == a["id"]:
                bal -= o["amount"]
            elif o["kind"] == "transfer":
                if o["account_id"] == a["id"]:
                    bal -= o["amount"]
                if o["to_account_id"] == a["id"]:
                    bal += o["amount"]
        res[a["id"]] = {"name": a["name"], "balance": bal}
    return res


def dds_report(con, q):
    f, t = q["from"], q["to"]
    planned = q.get("planned") == "1"
    months = months_between(f, t)
    cats = {c["id"]: dict(c) for c in con.execute("SELECT * FROM categories")}
    cells = {}
    for o in con.execute("""SELECT kind, amount, pay_date, category_id FROM operations
                            WHERE pay_date BETWEEN ? AND ? AND kind != 'transfer' AND (is_planned = 0 OR ?)""",
                         (f, t, 1 if planned else 0)):
        m = o["pay_date"][:7]
        cid = o["category_id"] or 0
        sign = 1 if o["kind"] == "income" else -1
        cells.setdefault(cid, {}).setdefault(m, 0)
        cells[cid][m] += sign * o["amount"]
    groups = {"operating": "Операционная деятельность", "financial": "Финансовая деятельность",
              "investing": "Инвестиционная деятельность"}
    out = []
    for g, gname in groups.items():
        lines = []
        for cid, vals in cells.items():
            c = cats.get(cid, {"name": "Без статьи", "dds_group": "operating", "kind": ""})
            if c["dds_group"] != g:
                continue
            lines.append({"name": c["name"], "kind": c.get("kind"), "values": [vals.get(m, 0) for m in months],
                          "total": sum(vals.values())})
        lines.sort(key=lambda x: (x["kind"] != "income", x["name"]))
        tot = [sum(l["values"][i] for l in lines) for i in range(len(months))]
        out.append({"group": gname, "lines": lines, "values": tot, "total": sum(tot)})
    opening = []
    closing = []
    for m in months:
        start = max(f, m + "-01")
        prev_day = (d(start) - dt.timedelta(days=1)).isoformat()
        opening.append(sum(v["balance"] for v in account_balances(con, prev_day, planned).values()))
        end = min(t, add_months(m + "-01", 1))
        end = (d(end) - dt.timedelta(days=1)).isoformat() if end != t else t
        closing.append(sum(v["balance"] for v in account_balances(con, end, planned).values()))
    return {"months": months, "groups": out, "opening": opening, "closing": closing,
            "accounts": list(account_balances(con, dt.date.today().isoformat(), False).values())}


# ---------------- ОПиУ ----------------
PNL_LINES = [
    ("realization", "Реализация", 0), ("spp", "Скидка за счёт МП (СПП, баллы)", 1),
    ("sales", "Фактические продажи", 0), ("direct", "Прямые расходы", 0),
    ("cost", "Себестоимость продаж", 1), ("logistics", "Логистика", 1), ("commission", "Номинальная комиссия", 1),
    ("acquiring", "Эквайринг", 1), ("penalty", "Штрафы", 1), ("storage", "Хранение", 1),
    ("ads", "Внутренняя реклама", 1), ("other", "Прочие удержания", 1), ("acceptance", "Платная приёмка", 1),
    ("compensation", "Компенсации", 0), ("gross", "Валовая прибыль", 0), ("opex", "Операционные расходы", 0),
    ("ebitda", "Операционная прибыль (EBITDA)", 0), ("below_income", "Доходы ниже операционной прибыли", 0),
    ("below_expense", "Расходы ниже операционной прибыли", 0), ("tax", "Налоги", 0),
    ("tax_usn", "УСН (по ставке)", 1), ("tax_nds", "НДС (по ставке)", 1), ("tax_fact", "Налог ИП (факт из операций)", 1),
    ("net", "Чистая прибыль", 0), ("dividends", "Дивиденды / вывод собственникам", 0),
    ("retained", "Остаётся в бизнесе", 0),
]


def ops_by_month_line(con, months):
    """Операции по месяцам начисления по статьям ОПиУ (кроме opex — он считается в metrics)."""
    res = {}
    for o in con.execute("""SELECT o.amount, COALESCE(o.accrual_date, o.pay_date) ad, COALESCE(o.distribute_months,1) n, c.pnl_line
                            FROM operations o JOIN categories c ON c.id = o.category_id
                            WHERE c.pnl_line IN ('fin_income','inv_income','fin_expense','inv_expense','dividends')"""):
        n = max(1, int(o["n"]))
        for i in range(n):
            m = add_months(o["ad"][:7] + "-01", i)[:7]
            if m in months:
                line = {"fin_income": "below_income", "inv_income": "below_income", "fin_expense": "below_expense",
                        "inv_expense": "below_expense", "dividends": "dividends"}[o["pnl_line"]]
                res.setdefault(m, {}).setdefault(line, 0)
                res[m][line] += o["amount"] / n
    return res


def pnl_report(con, q):
    f, t = q["from"], q["to"]
    flt = filters(q)
    months = months_between(f, t)
    by_m = metrics.compute(con, f, t, flt, "month")
    total = metrics.compute(con, f, t, flt, "all").get("all")
    extra = ops_by_month_line(con, months)
    cols = []
    for m in list(reversed(months)):
        cols.append((m, by_m.get(m)))
    cols = [("total", total)] + cols
    rows = []
    for key, name, level in PNL_LINES:
        vals = []
        for m, dd in cols:
            dd = dd or {}
            e = extra.get(m, {}) if m != "total" else {k: sum(extra.get(x, {}).get(k, 0) for x in months)
                                                         for k in ("below_income", "below_expense", "dividends")}
            if key == "ebitda":
                v = dd.get("gross", 0) - dd.get("opex", 0)
            elif key == "net":
                v = dd.get("gross", 0) - dd.get("opex", 0) + e.get("below_income", 0) - e.get("below_expense", 0) - dd.get("tax", 0)
            elif key in ("below_income", "below_expense", "dividends"):
                v = e.get(key, 0)
            elif key == "retained":
                v = dd.get("gross", 0) - dd.get("opex", 0) + e.get("below_income", 0) - e.get("below_expense", 0) \
                    - dd.get("tax", 0) - e.get("dividends", 0)
            else:
                v = dd.get(key, 0)
            real = dd.get("realization", 0)
            vals.append({"v": v, "pct": v / real * 100 if real else 0})
        mode = (total or {}).get("tax_mode", "rates")
        if (key in ("tax_usn", "tax_nds") and mode == "actual") or (key == "tax_fact" and mode != "actual"):
            continue
        rows.append({"key": key, "name": name, "level": level, "values": vals})
    return {"columns": [c[0] for c in cols], "rows": rows}


# ---------------- дашборд и сводный ----------------
def dashboard(con, q):
    f, t = q["from"], q["to"]
    flt = filters(q)
    pf, pt = prev_period(f, t)
    days = (d(t) - d(f)).days + 1
    cur = metrics.compute(con, f, t, flt).get("all") or metrics.derive(metrics.compute(con, "1900-01-01", "1900-01-01").get("all") or empty(), db.tax_settings())
    prv = metrics.compute(con, pf, pt, flt).get("all") or empty_derived()
    metrics.add_stock_metrics(cur, metrics.stocks_summary(con, t, flt), days)
    metrics.add_stock_metrics(prv, metrics.stocks_summary(con, pt, flt), days)
    daily = metrics.compute(con, f, t, flt, "day")
    series = [{"day": day, **{k: (daily.get(day) or {}).get(k, 0) for k in
               ("orders_sum", "orders_qty", "sales", "realization", "profit", "logistics", "storage", "price_before_spp", "ads", "returns")}}
              for day in metrics._days(f, t)]
    arts = metrics.compute(con, f, t, flt, "article")
    parts = metrics.compute(con, pf, pt, flt, "article")
    st = metrics.stocks_summary(con, t, flt, by_article=True)
    names = {r["article"]: r for r in con.execute("SELECT article, MAX(name) name, MAX(mp) mp, MAX(mp_sku) mp_sku, MAX(photo) photo, MAX(category) category FROM products GROUP BY article")}
    table = []
    for a, v in arts.items():
        metrics.add_stock_metrics(v, st.get(a, {}), days)
        pv = parts.get(a, {})
        v["profit_prev"] = pv.get("profit", 0)
        v["orders_qty_prev"] = pv.get("orders_qty", 0)
        info = names.get(a, {})
        table.append({"article": a, "name": info["name"] if info else "", "category": info["category"] if info else "", **v})
    total_profit = sum(r["profit"] for r in table if r["profit"] > 0)
    for r in table:
        r["profit_share"] = r["profit"] / total_profit * 100 if total_profit and r["profit"] > 0 else 0
        r["revenue_share"] = r["realization"] / cur["realization"] * 100 if cur["realization"] else 0
    abc(table, "profit", "abc_profit"); abc(table, "realization", "abc_revenue")
    table.sort(key=lambda r: -r["realization"])
    top = sorted([r for r in table if r["profit"]], key=lambda r: -r["profit"])[:5]
    # WB по схемам: FBO (склады WB) и FBS (свой склад) — отдельные строки для сравнения
    schemes = None
    if flt.get("mp") in (None, "wb") and not flt.get("scheme"):
        keys = ("orders_qty", "orders_sum", "sales_qty", "realization", "logistics", "cost", "profit", "returns_qty")
        schemes = {}
        for sc in ("FBO", "FBS"):
            v = metrics.compute(con, f, t, {**flt, "mp": "wb", "scheme": sc}).get("all") or {}
            schemes[sc] = {k: v.get(k, 0) or 0 for k in keys}
        schemes["all"] = {k: schemes["FBO"][k] + schemes["FBS"][k] for k in keys}
        if not any(schemes["FBS"].values()):
            schemes = None
    return {"from": f, "to": t, "prev_from": pf, "prev_to": pt, "cur": cur, "prev": prv, "series": series,
            "top": top, "table": table, "missing_days": missing_days(con, f, t, flt), "wb_schemes": schemes}


CHART_KEYS = ("orders_sum", "orders_qty", "sales", "realization", "profit", "profit_wo_opex", "logistics", "storage", "ads", "returns", "cost")


def chart(con, q):
    """Ряды для графика «Динамика»: по дням, неделям или месяцам за свой период."""
    f, t, g = q["from"], q["to"], q.get("group", "day")
    if g not in ("day", "week", "month"):
        g = "day"
    flt = filters(q)
    data = metrics.compute(con, f, t, flt, g)
    keys = []
    for day in metrics._days(f, t):
        k = metrics._key_of_day(day, g)
        if not keys or keys[-1] != k:
            keys.append(k)
    series = [{"key": k, **{m: (data.get(k) or {}).get(m, 0) for m in CHART_KEYS}} for k in keys]
    return {"from": f, "to": t, "group": g, "series": series}


def abc(rows, key, out):
    rows_sorted = sorted(rows, key=lambda r: -r[key])
    total = sum(max(r[key], 0) for r in rows_sorted)
    acc = 0
    for r in rows_sorted:
        acc += max(r[key], 0)
        share = acc / total if total else 1
        r[out] = "A" if share <= 0.8 else ("B" if share <= 0.95 else "C")


def missing_days(con, f, t, flt):
    have = {r[0] for r in con.execute("SELECT DISTINCT dt FROM fin WHERE dt BETWEEN ? AND ?", (f, t))}
    if not have:
        return None
    return len([x for x in metrics._days(f, t) if x not in have])


def empty():
    return {m: 0.0 for m in metrics.FIN_METRICS} | {"sales_qty": 0.0, "returns_qty": 0.0, "refusal_qty": 0.0,
            "cost": 0.0, "no_cost_qty": 0.0, "orders_sum": 0.0, "orders_qty": 0.0, "orders_paid": 0.0,
            "cancel_qty": 0.0, "opex": 0.0}


def empty_derived():
    return metrics.derive(empty(), db.tax_settings())


def summary(con, q):
    f, t = q["from"], q["to"]
    g = q.get("group", "week")
    flt = filters(q)
    data = metrics.compute(con, f, t, flt, g)
    keys = sorted(data.keys(), reverse=True)
    total = metrics.compute(con, f, t, flt, "all").get("all") or empty_derived()
    rows = []
    for i, k in enumerate(keys):
        cur = data[k]
        prev = data.get(keys[i + 1]) if i + 1 < len(keys) else None
        rows.append({"key": k, "cur": cur, "prev": prev})
    return {"group": g, "rows": rows, "total": total}


def meta(con):
    arts = [r[0] for r in con.execute("""SELECT article FROM (SELECT article FROM costs UNION SELECT article FROM products
                                         UNION SELECT DISTINCT article FROM fin) WHERE article IS NOT NULL AND article != '' ORDER BY 1""")]
    m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    rng = con.execute("SELECT MIN(dt), MAX(dt) FROM fin").fetchone()
    return {"articles": arts, "shops": [dict(r) for r in con.execute("SELECT * FROM shops")],
            "last_update": m.get("last_update"), "update_status": m.get("update_status"), "gsheet_import": m.get("gsheet_import"),
            "data_from": rng[0], "data_to": rng[1], "tax": db.tax_settings(),
            "accounts": [dict(r) for r in con.execute("SELECT * FROM accounts ORDER BY archived, id")],
            "categories": [dict(r) for r in con.execute("SELECT * FROM categories ORDER BY kind DESC, name")]}


# ---------------- склады ----------------
def _plan_cell(qty_period, days, stock, target, in_way=0):
    per_day = qty_period / days if days else 0
    cover = stock / per_day if per_day > 0 else (None if stock == 0 else 999)
    need = max(0.0, per_day * target - stock - in_way)
    return {"orders": qty_period, "per_day": per_day, "stock": stock, "cover": cover, "need": need, "in_way": in_way}


def wh_ozon(con, q):
    days = int(q.get("days") or 14)
    target = float(q.get("target") or 30)
    to = q.get("to") or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    f = (d(to) - dt.timedelta(days=days - 1)).isoformat()
    snap = con.execute("SELECT MAX(snap_date) FROM wh_stocks WHERE mp='ozon'").fetchone()[0]
    stock, names = {}, {}
    if snap:
        for r in con.execute("""SELECT COALESCE(s.article, p.article, s.mp_sku) a, COALESCE(s.cluster, c.cluster, s.warehouse) cl,
                                       SUM(s.free) fr, SUM(s.promised) pr, SUM(s.reserved) rs, MAX(s.name) nm
                                FROM wh_stocks s LEFT JOIN wh_cluster c ON c.mp='ozon' AND c.warehouse=s.warehouse
                                LEFT JOIN products p ON p.mp='ozon' AND p.mp_sku=s.mp_sku
                                WHERE s.mp='ozon' AND s.snap_date=? GROUP BY 1, 2""", (snap,)):
            stock[(r["a"], r["cl"])] = (r["fr"] or 0, r["pr"] or 0, r["rs"] or 0)
            names[r["a"]] = r["nm"]
    orders, local = {}, {}
    for r in con.execute("""SELECT COALESCE(article, mp_sku) a, COALESCE(cluster_to, region, 'Не определён') cl, SUM(qty) q,
                                   SUM(CASE WHEN cluster_from = cluster_to THEN qty ELSE 0 END) lq
                            FROM orders WHERE mp='ozon' AND is_cancel=0 AND cluster_to IS NOT NULL AND dt BETWEEN ? AND ?
                            GROUP BY 1, 2""", (f, to)):
        orders[(r["a"], r["cl"])] = r["q"] or 0
        local[(r["a"], r["cl"])] = r["lq"] or 0
    clusters = sorted({k[1] for k in list(stock) + list(orders) if k[1]},
                      key=lambda c: -sum(v for (a, cl), v in orders.items() if cl == c))
    arts = sorted({k[0] for k in list(stock) + list(orders) if k[0]})
    rows = []
    for a in arts:
        cells, tot_o, tot_s, tot_w, tot_need, tot_l = {}, 0, 0, 0, 0, 0
        for c in clusters:
            fr, pr, rs = stock.get((a, c), (0, 0, 0))
            o = orders.get((a, c), 0)
            cell = _plan_cell(o, days, fr, target, pr)
            cell["nonlocal"] = (1 - local.get((a, c), 0) / o) * 100 if o else None
            cells[c] = cell
            tot_o += o; tot_s += fr; tot_w += pr; tot_need += cell["need"]; tot_l += local.get((a, c), 0)
        total = _plan_cell(tot_o, days, tot_s, target, tot_w)
        total["need"] = tot_need          # везти считаем по кластерам: излишек в одном не закрывает дефицит в другом
        total["nonlocal"] = (1 - tot_l / tot_o) * 100 if tot_o else None
        rows.append({"article": a, "name": names.get(a) or "", "cells": cells, "total": total})
    pnames = {r[0]: r[1] for r in con.execute("SELECT article, MAX(name) FROM products WHERE mp='ozon' AND name IS NOT NULL GROUP BY article")}
    for r in rows:
        r["name"] = r["name"] or pnames.get(r["article"], "")
    rows.sort(key=lambda r: -r["total"]["orders"])
    ctot = {}
    for c in clusters:
        o = sum(r["cells"][c]["orders"] for r in rows)
        lq = sum(local.get((r["article"], c), 0) for r in rows)
        t = _plan_cell(o, days, sum(r["cells"][c]["stock"] for r in rows), target, sum(r["cells"][c]["in_way"] for r in rows))
        t["need"] = sum(r["cells"][c]["need"] for r in rows)
        t["nonlocal"] = (1 - lq / o) * 100 if o else None
        t["deficit_skus"] = sum(1 for r in rows if r["cells"][c]["per_day"] > 0 and (r["cells"][c]["cover"] or 0) < 14)
        ctot[c] = t
    m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    return {"clusters": clusters, "rows": rows, "cluster_totals": ctot, "from": f, "to": to, "days": days, "target": target,
            "snapshot": snap, "snapshot_at": m.get("oz_wh_snapshot")}


def wh_wb(con, q):
    days = int(q.get("days") or 14)
    target = float(q.get("target") or 30)
    to = q.get("to") or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    f = (d(to) - dt.timedelta(days=days - 1)).isoformat()
    orders = {}
    for r in con.execute("""SELECT COALESCE(article, mp_sku) a, COALESCE(region, 'Не определён') reg, SUM(qty) q
                            FROM orders WHERE mp='wb' AND is_cancel=0 AND dt BETWEEN ? AND ? GROUP BY 1, 2""", (f, to)):
        orders[(r["a"], r["reg"])] = r["q"] or 0
    ru = ["Центральный федеральный округ", "Северо-Западный федеральный округ", "Южный федеральный округ",
          "Северо-Кавказский федеральный округ", "Приволжский федеральный округ", "Уральский федеральный округ",
          "Сибирский федеральный округ", "Дальневосточный федеральный округ"]
    def dist(reg):
        return reg if reg in ru else "Другие страны"
    agg = {}
    for (a, reg), v in orders.items():
        agg[(a, dist(reg))] = agg.get((a, dist(reg)), 0) + v
    districts = [x for x in ru + ["Другие страны"] if any(k[1] == x for k in agg)]
    snap = con.execute("SELECT MAX(snap_date) FROM stocks WHERE mp='wb'").fetchone()[0]
    stock = {}
    if snap:
        for r in con.execute("""SELECT COALESCE(article, mp_sku) a, SUM(qty) q, SUM(to_client) tc, SUM(from_client) fc
                                FROM stocks WHERE mp='wb' AND snap_date=? GROUP BY 1""", (snap,)):
            stock[r["a"]] = (r["q"] or 0, r["tc"] or 0, r["fc"] or 0)
    arts = sorted({a for a, _ in agg} | set(stock))
    rows = []
    for a in arts:
        tot_o = sum(agg.get((a, x), 0) for x in districts)
        st, tc, fc = stock.get(a, (0, 0, 0))
        total = _plan_cell(tot_o, days, st, target)
        cells = {}
        for x in districts:
            o = agg.get((a, x), 0)
            per_day = o / days
            cells[x] = {"orders": o, "per_day": per_day, "share": o / tot_o * 100 if tot_o else 0,
                        "keep": per_day * target,            # сколько держать в округе на целевой запас
                        "need": total["need"] * (o / tot_o) if tot_o else 0}   # общий дефицит, разложенный по спросу
        rows.append({"article": a, "cells": cells, "total": total, "to_client": tc, "from_client": fc})
    rows.sort(key=lambda r: -r["total"]["orders"])
    dtot = {}
    all_o = sum(r["total"]["orders"] for r in rows)
    for x in districts:
        o = sum(r["cells"][x]["orders"] for r in rows)
        dtot[x] = {"orders": o, "per_day": o / days, "share": o / all_o * 100 if all_o else 0,
                   "keep": sum(r["cells"][x]["keep"] for r in rows), "need": sum(r["cells"][x]["need"] for r in rows)}
    total = _plan_cell(all_o, days, sum(r["total"]["stock"] for r in rows), target)
    total["need"] = sum(r["total"]["need"] for r in rows)
    m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    return {"districts": districts, "rows": rows, "district_totals": dtot, "total": total, "from": f, "to": to,
            "days": days, "target": target, "snapshot": snap, "snapshot_at": m.get("wb_wh_snapshot") or m.get("last_update")}


def ozon_plan_xlsx(con, q):
    """Excel-заготовка плана поставок Ozon: сводка, общий список и лист на каждый кластер."""
    import math, re as _re
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    R = wh_ozon(con, q)
    skus = {r["article"]: r["mp_sku"] for r in con.execute("SELECT article, MAX(mp_sku) mp_sku FROM products WHERE mp='ozon' GROUP BY article")}
    target = R["target"]
    wb = openpyxl.Workbook()
    head_fill = PatternFill("solid", fgColor="E5EFFB")
    red, amber = PatternFill("solid", fgColor="FBE9E7"), PatternFill("solid", fgColor="FDF3DC")
    thin = Border(bottom=Side(style="thin", color="C3C2B7"))
    bold = Font(bold=True)

    def sheet_header(ws, title, cols, widths):
        ws.append([title]); ws["A1"].font = Font(bold=True, size=13)
        ws.append([f"Спрос: заказы без отмен за {ruDate(R['from'])}–{ruDate(R['to'])} ({R['days']} дн.). "
                   f"Целевой запас: {target:g} дн. Остатки на {ruDate(R['snapshot'] or '')}. "
                   f"Везти = заказов в день × {target:g} − остаток − в пути (округлено вверх)."])
        ws["A2"].font = Font(italic=True, color="52514E")
        ws.append([])
        ws.append(cols)
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=4, column=i); cell.font = bold; cell.fill = head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center"); cell.border = thin
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A5"

    def line(r, c):
        x = r["cells"][c]
        need = math.ceil(x["need"]) if x["need"] > 0 else 0
        after = (x["stock"] + x["in_way"] + need) / x["per_day"] if x["per_day"] > 0 else None
        return need, x, after

    def fill_cover(ws, row, col, cover):
        if cover is None:
            return
        cell = ws.cell(row=row, column=col)
        if cover < 14:
            cell.fill = red
        elif cover < 30:
            cell.fill = amber

    def rnd(v, k=1):
        return None if v is None or v >= 999 else round(v, k)

    # 1) Сводка
    ws = wb.active; ws.title = "Сводка"
    sheet_header(ws, "План поставок Ozon — сводка по кластерам",
                 ["Кластер", "Артикулов к поставке", "Везти, шт", "Заказов в день", "Остаток, шт", "В пути, шт",
                  "Дней запаса сейчас", "Нелокальных заказов, %"], [34, 14, 12, 12, 12, 11, 12, 14])
    total_need = 0
    for c in R["clusters"]:
        t = R["cluster_totals"][c]
        n_art = sum(1 for r in R["rows"] if line(r, c)[0] > 0)
        need = sum(line(r, c)[0] for r in R["rows"])
        if need <= 0 and t["per_day"] <= 0:
            continue
        total_need += need
        ws.append([c, n_art, need, round(t["per_day"], 1), t["stock"], t["in_way"], rnd(t["cover"]),
                   None if t["nonlocal"] is None else round(t["nonlocal"], 1)])
        fill_cover(ws, ws.max_row, 7, t["cover"] if t["per_day"] > 0 else None)
    ws.append([]); ws.append(["Итого везти", None, total_need]); ws.cell(row=ws.max_row, column=1).font = bold
    ws.cell(row=ws.max_row, column=3).font = bold
    ws.auto_filter.ref = f"A4:H{ws.max_row - 2}"

    cols = ["Артикул", "Название", "SKU Ozon", "Везти, шт", "Заказов в день", "Остаток, шт", "В пути, шт",
            "Дней запаса сейчас", "Дней запаса после поставки"]
    widths = [18, 46, 14, 10, 11, 11, 10, 12, 13]

    # 2) Все кластеры одним списком
    ws = wb.create_sheet("Все кластеры")
    sheet_header(ws, "План поставок Ozon — все позиции", ["Кластер"] + cols, [30] + widths)
    for c in R["clusters"]:
        for r in sorted(R["rows"], key=lambda r: -line(r, c)[0]):
            need, x, after = line(r, c)
            if need <= 0:
                continue
            ws.append([c, r["article"], r["name"], skus.get(r["article"]), need, round(x["per_day"], 2), x["stock"],
                       x["in_way"], rnd(x["cover"]), rnd(after)])
            fill_cover(ws, ws.max_row, 9, x["cover"])
    ws.auto_filter.ref = f"A4:J{max(ws.max_row, 4)}"

    # 3) По листу на кластер
    used = set()
    for c in R["clusters"]:
        rows = [(r, *line(r, c)) for r in R["rows"]]
        rows = [x for x in rows if x[1] > 0]
        if not rows:
            continue
        name = _re.sub(r"[\\/*?:\[\]]", " ", c)[:28].strip() or "Кластер"
        base, k = name, 2
        while name in used:
            name = f"{base[:25]} {k}"; k += 1
        used.add(name)
        ws = wb.create_sheet(name)
        sheet_header(ws, f"План поставок Ozon — {c}", cols, widths)
        for r, need, x, after in sorted(rows, key=lambda y: -y[1]):
            ws.append([r["article"], r["name"], skus.get(r["article"]), need, round(x["per_day"], 2), x["stock"],
                       x["in_way"], rnd(x["cover"]), rnd(after)])
            fill_cover(ws, ws.max_row, 8, x["cover"])
        ws.append([]); ws.append(["Итого", None, None, sum(x[1] for x in rows)])
        ws.cell(row=ws.max_row, column=1).font = bold; ws.cell(row=ws.max_row, column=4).font = bold
    bio = io.BytesIO(); wb.save(bio)
    return bio.getvalue()


def ruDate(s):
    return ".".join(reversed(s.split("-"))) if s else ""


# ---------------- обновление данных ----------------
def update_running(con):
    m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta WHERE key IN ('update_running','update_heartbeat')")}
    try:
        fresh = time.time() - float(m.get("update_heartbeat") or 0) < 600
    except ValueError:
        fresh = False
    return m.get("update_running") == "1" and fresh


def run_update(con, full=False, mode=None):
    """Загрузчик запускается отдельным процессом: переживает закрытие окна сервера и не блокирует дашборд."""
    if update_running(con):
        return False
    args = [sys.executable, os.path.join(db.APP_DIR, "collector.py")] + (["--full"] if full else []) + \
           {"ozon_wh": ["--ozon-wh"], "wb_wh": ["--wb-wh"], "gsheet": ["--gsheet"], "prices": ["--prices"], "today": ["--today"], "supplies": ["--supplies"], "promos": ["--promos"]}.get(mode, [])
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(args, cwd=db.APP_DIR, creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_running','1')")
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_heartbeat', ?)", (str(time.time()),))
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_status','Запуск загрузки…')")
    con.commit()
    return True


# ---------------- HTTP ----------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def send_json(self, obj, code=200, cookie=None):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def raw_body(self, limit=25 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("файл слишком большой")
        return self.rfile.read(n)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def route(self, method):
        u = urlparse(self.path)
        p = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if method == "GET" and not p.startswith("/api/"):
            fn = "index.html" if p in ("/", "") else p.lstrip("/").replace("static/", "", 1)
            path = os.path.normpath(os.path.join(STATIC, fn))
            if not path.startswith(STATIC) or not os.path.isfile(path):
                self.send_response(404); self.end_headers(); return
            data = open(path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(os.path.splitext(path)[1], "application/octet-stream"))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers(); self.wfile.write(data); return
        con = db.connect()
        try:
            parts = p.strip("/").split("/")[1:]
            name = parts[0] if parts else ""
            token = self.cookie("mpc_session")
            self.user = auth.session_user(con, token)
            if name == "login" and method == "POST":
                b = self.body()
                tok = auth.login(con, b.get("phone"), b.get("password"))
                if not tok:
                    self.send_json({"error": "Неверный телефон или пароль"}, 401); return
                self.send_json({"ok": True}, cookie=f"mpc_session={tok}; Path=/; HttpOnly; SameSite=Lax; Max-Age={auth.SESSION_DAYS * 86400}")
                return
            if name == "logout":
                auth.logout(con, token)
                self.send_json({"ok": True}, cookie="mpc_session=; Path=/; Max-Age=0"); return
            if auth.has_users(con):
                if not self.user:
                    self.send_json({"error": "login", "need_login": True}, 401); return
                allowed = set(auth.user_pages(self.user))
                need = auth.API_PAGE.get(name)
                if name == "wh":
                    need = "wh_wb" if (len(parts) > 1 and parts[1].startswith("wb")) else "wh_ozon"
                if name in ("users", "config") and self.user["role"] != "admin":
                    self.send_json({"error": "Нет доступа"}, 403); return
                if name == "update" and method == "POST":
                    if q.get("full") == "1" and self.user["role"] != "admin":
                        self.send_json({"error": "Нет доступа"}, 403); return
                    need = {"ozon_wh": "wh_ozon", "wb_wh": "wh_wb", "gsheet": "operations", "prices": "prices", "today": "dashboard", "supplies": "supplies", "promos": "promos"}.get(q.get("mode"), "dashboard")
                if need and need not in allowed:
                    self.send_json({"error": "Нет доступа к этому разделу"}, 403); return
            res = self.api(con, method, parts, q)
            if isinstance(res, tuple) and res and res[0] == "file":
                _, data, fname, ctype = res
                from urllib.parse import quote
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(fname)}")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_json(res)
        except Exception as e:
            import traceback; traceback.print_exc()
            self.send_json({"error": str(e)}, 500)
        finally:
            con.close()

    def api(self, con, method, parts, q):
        name = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else None
        if name == "meta":
            m = meta(con)
            u = getattr(self, "user", None)
            m["auth"] = {"enabled": auth.has_users(con), "user": ({"name": u["name"], "phone": u["phone"], "role": u["role"]} if u else None),
                         "pages": auth.user_pages(u), "page_names": auth.PAGE_NAMES,
                         "is_admin": (not auth.has_users(con)) or bool(u and u["role"] == "admin"),
                         "lan_url": LAN_URL}
            pg = set(m["auth"]["pages"])
            m["price_alerts"] = prices.alert_count(con) if "prices" in pg else 0
            m["supply_alerts"] = supplies.pending_count(con) if "supplies" in pg else 0
            m["shop_name"] = appconfig.shop_name()
            m["promo_alerts"] = promos.new_count(con) if "promos" in pg else 0
            m["promo_active"] = promos.active_counts(con) if "promos" in pg else {"wb": 0, "ozon": 0}
            if not pg & {"operations", "settings", "dds", "pnl"}:
                m["accounts"], m["categories"] = [], []
            return m
        if name == "users":
            if method == "GET":
                return auth.list_users(con)
            b = self.body()
            try:
                return {"id": auth.save_user(con, b, int(arg) if arg else None)}
            except ValueError as e:
                return {"error": str(e)}
        if name == "dashboard":
            return dashboard(con, q)
        if name == "summary":
            return summary(con, q)
        if name == "chart":
            return chart(con, q)
        if name == "today":
            if method == "POST":
                return today.save_settings(con, self.body())
            return today.report(con, dt.datetime.fromisoformat(q["now"]) if q.get("now") else None,
                                q.get("mp") or None, q.get("scheme") if q.get("scheme") in ("FBO", "FBS") else None)
        if name == "monthly":
            R = monthly.report(con, q.get("ym"))
            if R["ym"] == monthly.default_month():
                con.execute("INSERT OR REPLACE INTO meta VALUES('monthly_seen', ?)", (R["ym"],)); con.commit()
            return R
        if name == "settings" and method == "POST":
            b = self.body()
            if b.get("tax_mode") in ("rates", "actual"):
                con.execute("INSERT OR REPLACE INTO meta VALUES('tax_mode', ?)", (b["tax_mode"],))
                con.commit()
            return {"ok": True}
        if name == "wh":
            if arg == "ozon_plan":
                return ("file", ozon_plan_xlsx(con, q), f"План поставок Ozon {dt.date.today():%d.%m.%Y}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if arg == "wb_plan":
                return ("file", wbplan.plan_xlsx(con, q), f"План поставок WB {dt.date.today():%d.%m.%Y}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if arg == "wb_presence":
                if method == "DELETE":
                    return wbplan.clear_presence(con, q.get("district"))
                try:
                    return wbplan.import_presence(con, self.body())
                except ValueError as e:
                    return {"error": str(e)}
            if arg == "wb_settings":
                return wbplan.save_settings(con, self.body())
            return wh_ozon(con, q) if arg == "ozon" else wbplan.plan(con, q)
        if name == "prices":
            if method == "GET":
                return prices.report(con, q)
            b = self.body()
            if arg == "settings":
                return prices.save_settings(con, b)
            if arg == "rrp":
                rows = b.get("rows") or []
                if b.get("text"):
                    rows = prices.parse_rrp_text(b["text"])
                if b.get("file"):
                    rows = prices.parse_rrp_xlsx(base64.b64decode(b["file"]))
                if not rows and not b.get("rows"):
                    return {"error": "Не нашёл ни одной пары «артикул — цена»"}
                return {"saved": prices.save_rrp(con, rows, bool(b.get("replace")))}
        if name == "media":
            uname = self.user["name"] if getattr(self, "user", None) else "admin"
            try:
                if arg == "load" and method == "POST":
                    out = {"wb": None, "ozon": None, "errors": []}
                    try:
                        out["wb"] = media.load_wb(con)
                    except Exception as e:
                        out["errors"].append(f"WB: {e}")
                    try:
                        media.load_ozon(con)
                        out["ozon"] = True
                    except Exception as e:
                        out["errors"].append(f"Ozon: {e}")
                    con.execute("INSERT OR REPLACE INTO meta VALUES('media_error', ?)", ("; ".join(out["errors"]),))
                    con.commit()
                    return out
                if arg == "upload" and method == "POST":
                    from urllib.parse import unquote
                    data = self.raw_body()
                    return media.replace_photo(con, uname, q["nm"], int(q["n"]), data,
                                               unquote(self.headers.get("X-Filename") or "photo.jpg"), self.headers.get("Content-Type"))
                if arg == "refresh" and method == "POST":
                    return media.refresh_card(con, q["nm"])
                if arg == "keep" and method == "POST":
                    return media.keep_first(con, uname, q["nm"], int(q["k"]))
                if arg == "restore" and method == "POST":
                    return media.restore(con, uname, q["nm"], q["ts"])
            except (ValueError, RuntimeError) as e:
                return {"error": str(e)}
            return media.report(con)
        if name == "promos":
            return promos.report(con, mark_viewed=q.get("seen") == "1")
        if name == "config":
            if arg == "check":
                return appconfig.check()
            if method == "POST":
                try:
                    return appconfig.save(self.body())
                except ValueError as e:
                    return {"error": str(e)}
            return appconfig.read()
        if name == "supplies":
            if method == "POST":
                try:
                    return supplies.save_mark(con, self.body())
                except ValueError as e:
                    return {"error": str(e)}
            return supplies.report(con, q)
        if name == "pnl":
            return pnl_report(con, q)
        if name == "dds":
            return dds_report(con, q)
        if name == "costs":
            if method == "GET":
                return costs_list(con, q)
            if arg == "import":
                b = self.body()
                rows = parse_costs_xlsx(base64.b64decode(b["file"]))
                return {"imported": import_costs_rows(con, rows, b.get("valid_from") or "2000-01-01", b.get("replace"))}
            if method in ("POST", "PUT"):
                b = self.body()
                return {"imported": import_costs_rows(con, b.get("rows", [b]))}
            if method == "DELETE":
                b = self.body()
                con.execute("DELETE FROM costs WHERE mp_sku=? AND scheme=?", (b["mp_sku"], b["scheme"])); con.commit()
                return {"ok": True}
        if name == "operations":
            if method == "GET":
                return operations_list(con, q)
            if method == "POST":
                return {"ids": save_operation(con, self.body())}
            if method == "PUT":
                return {"ids": save_operation(con, self.body(), int(arg))}
            if method == "DELETE":
                b = self.body() if int(self.headers.get("Content-Length") or 0) else {}
                if b.get("series") and b.get("series_id"):
                    con.execute("DELETE FROM operations WHERE series_id=? AND pay_date >= (SELECT pay_date FROM operations WHERE id=?)",
                                (b["series_id"], int(arg)))
                else:
                    con.execute("DELETE FROM operations WHERE id=?", (int(arg),))
                con.commit(); return {"ok": True}
        if name in ("accounts", "categories"):
            cols = ["name", "kind", "opening_balance", "opening_date", "archived"] if name == "accounts" else \
                   ["name", "kind", "dds_group", "pnl_line", "archived"]
            if method == "GET":
                return [dict(r) for r in con.execute(f"SELECT * FROM {name}")]
            b = self.body()
            if method == "POST":
                cur = con.execute(f"INSERT INTO {name}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                  [b.get(c) for c in cols]); con.commit(); return {"id": cur.lastrowid}
            if method == "PUT":
                con.execute(f"UPDATE {name} SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                            [b.get(c) for c in cols] + [int(arg)]); con.commit(); return {"ok": True}
            if method == "DELETE":
                used = con.execute(f"SELECT COUNT(*) FROM operations WHERE {'account_id' if name == 'accounts' else 'category_id'}=?",
                                   (int(arg),)).fetchone()[0]
                if used:
                    con.execute(f"UPDATE {name} SET archived=1 WHERE id=?", (int(arg),))
                else:
                    con.execute(f"DELETE FROM {name} WHERE id=?", (int(arg),))
                con.commit(); return {"ok": True, "archived": bool(used)}
        if name == "update":
            if method == "POST":
                started = run_update(con, q.get("full") == "1", q.get("mode"))
                return {"started": started, "running": True}
            m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
            return {"running": update_running(con), "status": m.get("update_status"), "last_update": m.get("last_update")}
        return {"error": "not found"}

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PUT(self): self.route("PUT")
    def do_DELETE(self): self.route("DELETE")


def seed_costs(con):
    path = os.path.join(db.APP_DIR, "costs_seed.json")
    if os.path.exists(path) and not con.execute("SELECT 1 FROM costs").fetchone():
        import_costs_rows(con, json.load(open(path, encoding="utf-8")))


def main():
    con = db.init()
    auth.init(con)
    wbplan.init(con)
    prices.init(con)
    supplies.init(con)
    media.init(con)
    promos.init(con)
    seed_costs(con)
    con.close()
    cfg = db.config()
    network = cfg.get("server", "network", fallback="0").strip() in ("1", "yes", "да", "true")
    con = db.connect()
    users = auth.has_users(con)
    con.close()
    if network and not users:
        print("ВНИМАНИЕ: доступ по сети включён в config.ini, но ещё нет ни одного пользователя.\n"
              "Пока дашборд открыт только на этом компьютере. Создайте администратора: Прочее → Пользователи.")
        network = False
    global PORT
    PORT = cfg.getint("server", "port", fallback=PORT)
    host = "0.0.0.0" if network else "127.0.0.1"
    srv = ThreadingHTTPServer((host, PORT), H)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Дашборд запущен: {url}\nНе закрывайте это окно, пока пользуетесь дашбордом.")
    if network:
        import socket
        try:
            s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s_.connect(("10.255.255.255", 1)); ip = s_.getsockname()[0]; s_.close()
        except OSError:
            ip = "IP-адрес этого компьютера"
        global LAN_URL
        LAN_URL = f"http://{ip}:{PORT}/"
        print(f"Доступ с других устройств в этой сети: {LAN_URL}  (вход по телефону и паролю)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
