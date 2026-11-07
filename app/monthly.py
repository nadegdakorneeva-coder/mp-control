# -*- coding: utf-8 -*-
"""Месячный отчёт для руководителя.

Месяц = полные недели пн–вс, у которых четверг попадает в этот месяц (как считают недели WB/Ozon и ISO):
октябрь 2026 = 28.09–01.11 (5 недель). Сравнение — с предыдущим месяцем, посчитанным так же.
Так как в месяцах разное число недель (4 или 5), сравниваем и итоги, и средние за неделю.
"""
import datetime as dt

import metrics
import prices

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
KPI = ["orders_sum", "orders_qty", "sales", "realization", "sales_qty", "for_pay", "commission", "logistics", "storage", "ads",
       "cost", "tax", "opex", "profit_wo_opex", "profit", "margin", "roi", "buyout", "returns"]
RATIO = {"margin", "roi", "buyout"}          # проценты — не делим на недели


def month_weeks(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    first = dt.date(y, m, 1)
    # понедельник недели, в которой четверг ≥ 1-го числа месяца
    thu = first + dt.timedelta(days=(3 - first.weekday()) % 7)
    start = thu - dt.timedelta(days=3)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    thu2 = nxt + dt.timedelta(days=(3 - nxt.weekday()) % 7)
    end = thu2 - dt.timedelta(days=4)
    weeks = []
    w = start
    while w <= end:
        weeks.append(w.isoformat())
        w += dt.timedelta(days=7)
    return start.isoformat(), end.isoformat(), weeks


def prev_ym(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - (m == 1)}-{(m - 2) % 12 + 1:02d}"


def default_month(today=None):
    """Последний месяц, чья последняя неделя закончилась минимум 3 дня назад (WB присылает недельный отчёт в пн–вт)."""
    today = today or dt.date.today()
    ym = today.strftime("%Y-%m")
    while month_weeks(ym)[1] > (today - dt.timedelta(days=3)).isoformat():
        ym = prev_ym(ym)
    return ym


def month_list(con):
    first = con.execute("SELECT MIN(dt) FROM fin").fetchone()[0] or dt.date.today().isoformat()
    today = dt.date.today()
    ym, last, out = first[:7], today.strftime("%Y-%m"), []
    while ym <= last:
        out.append(ym)
        y, m = int(ym[:4]), int(ym[5:7])
        ym = f"{y + (m == 12)}-{m % 12 + 1:02d}"
    return list(reversed(out))


def title(ym):
    return f"{MONTHS[int(ym[5:7]) - 1].capitalize()} {ym[:4]}"


def _pick(d):
    return {k: (d or {}).get(k, 0) or 0 for k in KPI}


def _delta(c, p):
    return {"abs": c - p, "pct": ((c - p) / abs(p) * 100) if p else None}


def report(con, ym=None):
    ym = ym or default_month()
    f, t, weeks = month_weeks(ym)
    pym = prev_ym(ym)
    pf, pt, pweeks = month_weeks(pym)
    nw, pnw = len(weeks), len(pweeks)
    today = dt.date.today().isoformat()

    def totals(a, b, flt=None):
        return _pick(metrics.compute(con, a, b, flt or {}).get("all"))

    cur, prv = totals(f, t), totals(pf, pt)
    kpis = []
    for k in KPI:
        c, p = cur[k], prv[k]
        if k in RATIO:
            kpis.append({"key": k, "cur": c, "prev": p, "delta": _delta(c, p), "ratio": True})
        else:
            cw, pw = c / nw, p / pnw
            kpis.append({"key": k, "cur": c, "prev": p, "cur_w": cw, "prev_w": pw, "delta": _delta(cw, pw)})

    # площадки
    mps = []
    for mp, name in (("wb", "Wildberries"), ("ozon", "Ozon")):
        c, p = totals(f, t, {"mp": mp}), totals(pf, pt, {"mp": mp})
        mps.append({"mp": mp, "name": name, "cur": c, "prev": p,
                    "share": c["realization"] / cur["realization"] * 100 if cur["realization"] else 0})

    # по неделям: этот и прошлый месяц
    def wk(a, b, ws):
        data = metrics.compute(con, a, b, {}, "week")
        return [{"week": w, **_pick(data.get(w))} for w in ws]
    weekly, pweekly = wk(f, t, weeks), wk(pf, pt, pweeks)

    # товары: рост и падение по заказам в среднем за неделю
    ca, pa = metrics.compute(con, f, t, {}, "article"), metrics.compute(con, pf, pt, {}, "article")
    names = {r["article"]: r["name"] for r in con.execute(
        "SELECT article, MAX(name) name FROM products WHERE article IS NOT NULL GROUP BY article")}
    arts = []
    for a in set(ca) | set(pa):
        c, p = _pick(ca.get(a)), _pick(pa.get(a))
        cw, pw = c["orders_sum"] / nw, p["orders_sum"] / pnw
        if not c["orders_sum"] and not p["orders_sum"] and not c["realization"] and not p["realization"]:
            continue
        arts.append({"article": a, "name": names.get(a) or "", "orders_w": cw, "orders_w_prev": pw,
                     "orders_qty": c["orders_qty"], "orders_qty_prev": p["orders_qty"],
                     "realization": c["realization"], "profit": c["profit"], "profit_prev": p["profit"],
                     "margin": c["margin"], "delta": cw - pw, "delta_pct": ((cw - pw) / pw * 100) if pw else None})
    grow = sorted([x for x in arts if x["delta"] > 0], key=lambda x: -x["delta"])[:10]
    fall = sorted([x for x in arts if x["delta"] < 0], key=lambda x: x["delta"])[:10]
    new = sorted([x for x in arts if x["orders_w"] > 0 and x["orders_w_prev"] == 0], key=lambda x: -x["orders_w"])[:10]
    gone = sorted([x for x in arts if x["orders_w"] == 0 and x["orders_w_prev"] > 0], key=lambda x: -x["orders_w_prev"])[:10]
    top_profit = sorted([x for x in arts if x["profit"]], key=lambda x: -x["profit"])[:10]

    # нет в наличии: по снимкам остатков (если есть за месяц), иначе — косвенно по дням без заказов
    days = metrics._days(f, min(t, today))
    snaps = [r[0] for r in con.execute("SELECT DISTINCT snap_date FROM stocks WHERE snap_date BETWEEN ? AND ? ORDER BY 1", (f, t))]
    oos, oos_method = [], None
    if len(snaps) >= max(7, len(days) // 2):
        oos_method = "stocks"
        zero = {}
        for r in con.execute("""SELECT snap_date, mp, COALESCE(article, mp_sku) a, SUM(qty) q FROM stocks
                                WHERE snap_date BETWEEN ? AND ? GROUP BY 1, 2, 3""", (f, t)):
            if (r["q"] or 0) <= 0:
                zero.setdefault((r["mp"], r["a"]), []).append(r["snap_date"])
        sold = {(r[0], r[1]) for r in con.execute(
            "SELECT DISTINCT mp, COALESCE(article, mp_sku) FROM orders WHERE dt BETWEEN ? AND ? AND is_cancel=0", (pf, t))}
        for (mp, a), ds in zero.items():
            if (mp, a) in sold:
                oos.append({"mp": mp, "article": a, "days": len(ds), "from": min(ds), "to": max(ds)})
    else:
        oos_method = "orders"
        per = {}
        for r in con.execute("""SELECT mp, COALESCE(article, mp_sku) a, dt, SUM(qty) q FROM orders
                                WHERE is_cancel=0 AND dt BETWEEN ? AND ? GROUP BY 1, 2, 3""", (pf, t)):
            per.setdefault((r["mp"], r["a"]), {})[r["dt"]] = r["q"] or 0
        pdays = len(metrics._days(pf, pt))
        for (mp, a), byday in per.items():
            prev_rate = sum(v for d_, v in byday.items() if d_ <= pt) / pdays
            if prev_rate < 1:          # только товары, которые продавались хотя бы раз в день
                continue
            run, best, best_end = 0, 0, None
            for d_ in days:
                if byday.get(d_, 0) == 0:
                    run += 1
                    if run > best:
                        best, best_end = run, d_
                else:
                    run = 0
            if best >= 3:
                oos.append({"mp": mp, "article": a, "days": best, "to": best_end,
                            "from": (dt.date.fromisoformat(best_end) - dt.timedelta(days=best - 1)).isoformat(),
                            "prev_rate": prev_rate})
    oos.sort(key=lambda x: -x["days"])

    # цены ниже МРЦ — по каждому заказу месяца (цена, которую заплатил покупатель)
    s = prices.settings(con)
    rrp = {}
    for r in con.execute("SELECT * FROM rrp"):
        rrp[(r["mp"], r["article"].lower())] = r["price"]
    viol = {}
    for r in con.execute("""SELECT mp, article, dt, paid, qty FROM orders WHERE dt BETWEEN ? AND ? AND paid > 0
                            AND article IS NOT NULL""", (f, t)):
        target = rrp.get((r["mp"], r["article"].lower())) or rrp.get(("all", r["article"].lower()))
        if not target:
            continue
        v = viol.setdefault((r["mp"], r["article"]), {"mp": r["mp"], "article": r["article"], "rrp": target, "orders": 0,
                                                       "below": 0, "min": None, "days": set()})
        v["orders"] += r["qty"] or 1
        if r["paid"] < target * (1 - s["tolerance"] / 100):
            v["below"] += r["qty"] or 1
            v["days"].add(r["dt"])
            v["min"] = r["paid"] if v["min"] is None else min(v["min"], r["paid"])
    price_viol = []
    for v in viol.values():
        if v["below"]:
            price_viol.append({**v, "days": len(v["days"]), "share": v["below"] / v["orders"] * 100,
                               "min_dev": (v["min"] - v["rrp"]) / v["rrp"] * 100})
    price_viol.sort(key=lambda x: (-x["below"]))

    # качество данных
    have = {r[0] for r in con.execute("SELECT DISTINCT dt FROM fin WHERE dt BETWEEN ? AND ?", (f, t))}
    missing = [x for x in days if x not in have]
    no_cost = (metrics.compute(con, f, t, {}).get("all") or {}).get("no_cost_qty", 0)
    notes = []
    if t >= today:
        notes.append("Месяц ещё не закончился — цифры неполные.")
    if missing:
        notes.append(f"Нет финансовых данных за {len(missing)} дн. ({', '.join(x[8:10] + '.' + x[5:7] for x in missing[:7])}"
                     f"{'…' if len(missing) > 7 else ''}) — маркетплейсы ещё не прислали отчёты.")
    if no_cost:
        notes.append(f"{no_cost:,.0f} шт. продано без заполненной себестоимости — прибыль завышена.".replace(",", " "))
    if not cur["opex"]:
        notes.append("Операционных расходов за месяц нет (Google Таблица не загружена или пуста) — чистая прибыль без них.")

    # главное — короткие выводы
    def num(x, dec=0):
        txt = f"{abs(x):,.{dec}f}".replace(",", " ").replace(".", ",")
        return ("−" if x < 0 else "") + txt

    def pct(x):
        return "—" if x is None else ("+" if x > 0 else "") + num(x) + "%"
    kd = {k["key"]: k for k in kpis}
    hl = [f"Реализация {num(cur['realization'] / 1e6, 1)} млн ₽ — в среднем за неделю {pct(kd['realization']['delta']['pct'])} к прошлому месяцу.",
          f"Чистая прибыль {num(cur['profit'] / 1e6, 2)} млн ₽ ({pct(kd['profit']['delta']['pct'])} за неделю), маржинальность "
          f"{num(cur['margin'], 1)}% (было {num(prv['margin'], 1)}%).",
          f"Заказы {num(cur['orders_sum'] / 1e6, 1)} млн ₽, {num(cur['orders_qty'])} шт. — {pct(kd['orders_sum']['delta']['pct'])} за неделю."]
    if grow:
        g = grow[0]
        hl.append(f"Больше всего выросли заказы {g['article']}: +{num(g['delta'])} ₽ в неделю ({pct(g['delta_pct'])}).")
    if fall:
        g = fall[0]
        hl.append(f"Сильнее всего упали заказы {g['article']}: {num(g['delta'])} ₽ в неделю ({pct(g['delta_pct'])}).")
    if oos:
        hl.append(f"Возможный аут-оф-сток: {len(oos)} позиций; дольше всех — {oos[0]['article']} ({oos[0]['days']} дн. подряд).")
    hl.append(f"Продажи ниже МРЦ: {len(price_viol)} артикулов, {num(sum(v['below'] for v in price_viol))} заказов."
              if price_viol else "Продаж ниже МРЦ не было.")

    return {"ym": ym, "title": title(ym), "from": f, "to": t, "weeks": weeks, "prev": {"ym": pym, "title": title(pym), "from": pf,
            "to": pt, "weeks": pweeks}, "kpis": kpis, "cur": cur, "prv": prv, "mps": mps, "weekly": weekly, "pweekly": pweekly,
            "grow": grow, "fall": fall, "new": new, "gone": gone, "top_profit": top_profit, "oos": oos[:20], "oos_method": oos_method,
            "price_viol": price_viol[:20], "notes": notes, "highlights": hl, "months": month_list(con),
            "price_tolerance": s["tolerance"], "default": default_month(), "generated": dt.datetime.now().strftime("%d.%m.%Y %H:%M")}
