# -*- coding: utf-8 -*-
"""Расчёт показателей: прибыль, удержания, себестоимость, налоги, остатки.
Логика повторяет TrueStats:
  Валовая прибыль = Реализация − (себестоимость + комиссия + эквайринг + логистика
                    + хранение + приёмка + штрафы + прочие удержания + реклама) + компенсации
  Чистая прибыль  = Валовая − операционные расходы − налоги
"""
import sqlite3
import calendar, datetime as dt
from db import tax_settings

FIN_METRICS = ["realization", "sales", "returns", "spp", "commission", "acquiring", "logistics",
               "storage", "acceptance", "penalty", "other", "ads", "compensation", "for_pay", "refusal"]

KEY_SQL = {
    "day": "f.dt",
    "week": "date(f.dt, 'weekday 0', '-6 days')",
    "month": "substr(f.dt, 1, 7)",
    "article": "COALESCE(NULLIF(f.article, ''), f.mp_sku)",
    "sku": "f.mp || ':' || f.mp_sku",
    "all": "'all'",
}

class CostLookup:
    """Себестоимость единицы (себестоимость + фулфилмент) по артикулу МП, схеме и дате."""
    def __init__(self, con):
        self.by_sku, self.by_art = {}, {}
        for r in con.execute("SELECT mp_sku, article, scheme, cost, fulfillment, valid_from FROM costs ORDER BY valid_from"):
            v = (r["valid_from"], (r["cost"] or 0) + (r["fulfillment"] or 0))
            self.by_sku.setdefault((str(r["mp_sku"]), r["scheme"]), []).append(v)
            if r["article"]:
                self.by_art.setdefault((r["article"].lower(), r["scheme"]), []).append(v)

    @staticmethod
    def _pick(hist, day):
        best = None
        for vf, val in hist or []:
            if vf <= day:
                best = val
        return best

    def get(self, sku, article, scheme, day):
        scheme = scheme or "FBO"
        other = "FBS" if scheme == "FBO" else "FBO"
        art = (article or "").lower()
        for h in (self.by_sku.get((str(sku), scheme)), self.by_sku.get((str(sku), other)),
                  self.by_art.get((art, scheme)), self.by_art.get((art, other))):
            v = self._pick(h, day)
            if v:
                return v
        return None


def _where(f, t, flt, alias="f"):
    sql = [f"{alias}.dt BETWEEN ? AND ?"]
    args = [f, t]
    if flt.get("mp"):
        sql.append(f"{alias}.mp = ?"); args.append(flt["mp"])
    if flt.get("articles"):
        arts = flt["articles"]
        sql.append(f"{alias}.article IN ({','.join('?' * len(arts))})"); args += arts
    if flt.get("scheme"):
        sql.append(f"COALESCE({alias}.scheme, 'FBO') = ?"); args.append(flt["scheme"])
    return " AND ".join(sql), args


def _days(f, t):
    a, b = dt.date.fromisoformat(f), dt.date.fromisoformat(t)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _key_of_day(d, group):
    if group == "day":
        return d
    if group == "week":
        x = dt.date.fromisoformat(d)
        return (x - dt.timedelta(days=x.weekday())).isoformat()
    if group == "month":
        return d[:7]
    return "all"


def opex_daily(con, f, t, line="opex"):
    """Расходы из «Операций» по дням (opex или фактические налоги): сумма делится на месяцы распределения и дни месяца."""
    days = {}
    rows = con.execute("""SELECT o.amount, o.nds, COALESCE(o.accrual_date, o.pay_date) AS ad,
                                 COALESCE(o.distribute_months, 1) AS n, c.pnl_line
                          FROM operations o JOIN categories c ON c.id = o.category_id
                          WHERE o.kind = 'expense' AND c.pnl_line = ?""", (line,)).fetchall()
    lo, hi = dt.date.fromisoformat(f), dt.date.fromisoformat(t)
    for r in rows:
        start = dt.date.fromisoformat(r["ad"][:10]).replace(day=1)
        n = max(1, int(r["n"] or 1))
        per_month = (r["amount"] or 0) / n
        y, m = start.year, start.month
        for _ in range(n):
            dim = calendar.monthrange(y, m)[1]
            per_day = per_month / dim
            for d in range(1, dim + 1):
                day = dt.date(y, m, d)
                if lo <= day <= hi:
                    days[day.isoformat()] = days.get(day.isoformat(), 0) + per_day
            m += 1
            if m == 13:
                y, m = y + 1, 1
    return days


def compute(con, f, t, flt=None, group="all"):
    """Возвращает {ключ: {показатель: значение}} за период [f, t]."""
    flt = flt or {}
    key = KEY_SQL[group]
    w, args = _where(f, t, flt)
    out = {}

    def row(k):
        return out.setdefault(k, {m: 0.0 for m in FIN_METRICS} | {
            "sales_qty": 0.0, "returns_qty": 0.0, "refusal_qty": 0.0, "cost": 0.0, "no_cost_qty": 0.0,
            "orders_sum": 0.0, "orders_qty": 0.0, "orders_paid": 0.0, "cancel_qty": 0.0, "opex": 0.0,
            "tax_fact": 0.0, "tax_fact_on": 0})

    for r in con.execute(f"SELECT {key} AS k, f.metric, SUM(f.amount) a, SUM(f.qty) q FROM fin f WHERE {w} GROUP BY 1, 2", args):
        d = row(r["k"])
        d[r["metric"]] = d.get(r["metric"], 0) + (r["a"] or 0)
        if r["metric"] == "realization":
            d["sales_qty"] += r["q"] or 0
        elif r["metric"] == "returns":
            d["returns_qty"] += r["q"] or 0
        elif r["metric"] == "refusal":
            d["refusal_qty"] += r["q"] or 0

    # себестоимость проданного (цена берётся в Python — без вложенных подзапросов, они медленные и капризны в старых SQLite)
    cl = CostLookup(con)
    for r in con.execute(f"""SELECT {key} AS k, f.mp_sku, f.article, COALESCE(f.scheme,'FBO') sc, f.dt, SUM(f.qty) q
                             FROM fin f WHERE {w} AND f.metric = 'realization' GROUP BY 1, 2, 3, 4, 5""", args):
        uc = cl.get(r["mp_sku"], r["article"], r["sc"], r["dt"])
        d = row(r["k"])
        if uc is None:
            d["no_cost_qty"] += r["q"] or 0
        else:
            d["cost"] += (r["q"] or 0) * uc

    # заказы
    okey = key.replace("f.", "o.")
    ow, oargs = _where(f, t, flt, "o")
    for r in con.execute(f"""SELECT {okey} AS k, SUM(o.qty) q, SUM(o.price * o.qty) s, SUM(o.paid * o.qty) p,
                                    SUM(CASE WHEN o.is_cancel THEN o.qty ELSE 0 END) c
                             FROM orders o WHERE {ow} GROUP BY 1""", oargs):
        d = row(r["k"])
        d["orders_qty"] += r["q"] or 0
        d["orders_sum"] += r["s"] or 0
        d["orders_paid"] += r["p"] or 0
        d["cancel_qty"] += r["c"] or 0

    # история заказов WB до начала обычных данных: помесячные итоги, по дням — поровну
    try:
        hw = ["d_to >= ?", "d_from <= ?"]; ha = [f, t]
        if flt.get("mp"):
            hw.append("mp = ?"); ha.append(flt["mp"])
        if flt.get("articles"):
            hw.append(f"article IN ({','.join('?' * len(flt['articles']))})"); ha += flt["articles"]
        # в помесячной истории нет разбивки FBO/FBS — при выборе схемы её не берём
        hrows = [] if flt.get("scheme") else con.execute(f"SELECT * FROM orders_hist WHERE {' AND '.join(hw)}", ha).fetchall()
    except sqlite3.OperationalError:
        hrows = []
    for r in hrows:
        days = _days(r["d_from"], r["d_to"])
        n = len(days)
        for day in days:
            if f <= day <= t:
                k = r["article"] if group == "article" and r["article"] else _key_of_day(day, group) if group in ("day", "week", "month", "all") else None
                if k is None:
                    continue
                d = row(k)
                d["orders_qty"] += (r["qty"] or 0) / n
                d["orders_sum"] += (r["sum"] or 0) / n
                d["orders_paid"] += (r["sum"] or 0) / n

    # операционные расходы (не распределяются по товарам и не делятся по площадкам)
    if group in ("day", "week", "month", "all") and not flt.get("articles") and not flt.get("mp") and not flt.get("scheme"):
        for day, v in opex_daily(con, f, t).items():
            row(_key_of_day(day, group))["opex"] += v
        for day, v in opex_daily(con, f, t, "tax").items():
            row(_key_of_day(day, group))["tax_fact"] += v
        for k in out:
            out[k]["tax_fact_on"] = 1

    tax = tax_settings()
    for k, d in out.items():
        derive(d, tax)
    return out


def derive(d, tax):
    real = d["realization"]
    d["spp"] = d["spp"] or (real - d["sales"] if d["sales"] else 0)
    direct = (d["cost"] + d["commission"] + d["acquiring"] + d["logistics"] + d["storage"] +
              d["acceptance"] + d["penalty"] + d["other"] + d["ads"])
    d["direct"] = direct
    d["gross"] = real - direct + d["compensation"]
    sales = d["sales"]
    if tax["base"] == "realization":
        base = real
    elif tax["base"] == "for_pay":
        base = d["for_pay"]
    else:
        base = sales
    nds = base * tax["nds"] / (100 + tax["nds"]) if tax["nds"] else 0.0
    d["tax_base"] = base - nds
    d["tax_usn"] = d["tax_base"] * tax["usn"] / 100
    d["tax_nds"] = nds
    d["tax_calc"] = d["tax_usn"] + nds
    # режим «по факту»: налоги ИП из «Операций» (статьи со строкой ОПиУ «Налоги»); для отборов по артикулу/площадке —
    # по ставкам, т.к. фактический налог на товар не делится
    d["tax_mode"] = "actual" if (tax.get("mode") == "actual" and d.get("tax_fact_on")) else "rates"
    d["tax"] = d.get("tax_fact", 0) if d["tax_mode"] == "actual" else d["tax_calc"]
    d["profit_wo_opex"] = d["gross"] - d["tax"]
    d["profit"] = d["profit_wo_opex"] - d["opex"]
    q = d["sales_qty"]
    d["margin"] = pct(d["profit"], real)
    d["margin_wo_opex"] = pct(d["profit_wo_opex"], real)
    d["roi"] = pct(d["profit"], d["cost"])
    d["price_before_spp"] = real / q if q else 0
    d["avg_sale_price"] = sales / q if q else 0
    d["logistics_per_unit"] = d["logistics"] / q if q else 0
    d["profit_per_unit"] = d["profit"] / q if q else 0
    denom = q + d["returns_qty"] + d["refusal_qty"]
    d["buyout"] = pct(q, denom) if denom > 0 else 0
    for m in ("commission", "acquiring", "logistics", "storage", "acceptance", "penalty", "other",
              "ads", "cost", "tax", "opex", "spp", "compensation"):
        d[m + "_pct"] = pct(d[m], real)
    d["drr"] = pct(d["ads"], real)
    d["drr_orders"] = pct(d["ads"], d["orders_sum"])
    return d


def pct(a, b):
    return a / b * 100 if b else 0.0


def stocks_summary(con, t, flt=None, by_article=False):
    """Остатки на последнюю дату ≤ t (или ближайшую после) и капитализация."""
    flt = flt or {}
    snap = con.execute("SELECT MAX(snap_date) FROM stocks WHERE snap_date <= ?", (t,)).fetchone()[0] or \
        con.execute("SELECT MIN(snap_date) FROM stocks").fetchone()[0]
    empty = {"stock_qty": 0, "to_client": 0, "from_client": 0, "cap_cost": 0, "cap_retail": 0, "snap": snap}
    if not snap:
        return {} if by_article else empty
    sql = ["snap_date = ?"]; args = [snap]
    if flt.get("mp"):
        sql.append("mp = ?"); args.append(flt["mp"])
    if flt.get("articles"):
        sql.append(f"article IN ({','.join('?' * len(flt['articles']))})"); args += flt["articles"]
    if flt.get("scheme"):
        sql.append("COALESCE(scheme, 'FBO') = ?"); args.append(flt["scheme"])
    prices = {r[0]: r[1] or 0 for r in con.execute(
        "SELECT mp_sku, AVG(price) FROM orders WHERE dt > date(?, '-30 day') AND dt <= ? GROUP BY mp_sku", (t, t))}
    cl = CostLookup(con)
    res = {}
    for r in con.execute(f"SELECT mp_sku, article, scheme, SUM(qty) q, SUM(to_client) tc, SUM(from_client) fc "
                         f"FROM stocks WHERE {' AND '.join(sql)} GROUP BY 1, 2, 3", args):
        k = (r["article"] or r["mp_sku"]) if by_article else "all"
        d = res.setdefault(k, dict(empty))
        q = r["q"] or 0
        d["stock_qty"] += q
        d["to_client"] += r["tc"] or 0
        d["from_client"] += r["fc"] or 0
        d["cap_cost"] += q * (cl.get(r["mp_sku"], r["article"], r["scheme"], snap) or 0)
        d["cap_retail"] += q * prices.get(r["mp_sku"], 0)
    if by_article:
        return res
    return res.get("all", empty)


def add_stock_metrics(d, st, days):
    d.update({k: v for k, v in st.items() if k != "snap"})
    per_day = d["sales_qty"] / days if days else 0
    d["turnover"] = d.get("stock_qty", 0) / per_day if per_day > 0 else 0
    d["gmroi"] = pct(d["gross"], d.get("cap_cost", 0))
    d["gmroi_year"] = d["gmroi"] * 365 / days if days else 0
    return d
