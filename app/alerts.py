# -*- coding: utf-8 -*-
"""Критические сигналы для виджета поверх окон и для дашборда:
цены ниже МРЦ, заканчивается товар на складах Ozon (по кластерам) и WB (общий запас + «нет на месте»),
давно не обновлялись данные."""
import datetime as dt

import monthly
import prices
import supplies as supplies_mod
import today as today_mod
import wbplan

LEVEL = {"ok": 0, "info": 1, "amber": 2, "red": 3}


def _meta(con, k, d=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r and r[0] is not None else d


def settings(con):
    return {"cover_days": float(_meta(con, "alert_cover_days", 30)),     # «заканчивается», если запаса меньше N дней
            "red_days": float(_meta(con, "alert_red_days", 14)),         # красный, если меньше N дней
            "min_per_day": float(_meta(con, "alert_min_per_day", 0.5))}  # не шуметь по редким товарам (≥ 7 заказов за 14 дней)


def save_settings(con, b):
    for k in ("cover_days", "red_days", "min_per_day"):
        if k in b:
            con.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", ("alert_" + k, str(max(0.0, float(b[k])))))
    con.commit()
    return settings(con)


def _n(v):
    return f"{v:,.0f}".replace(",", " ")


def _f1(v):
    return f"{v:.1f}".replace(".", ",")


def _days(c):
    return "∞" if c is None or c >= 999 else f"{c:.0f}"


def compute(con, wh_ozon=None):
    s = settings(con)
    groups = []

    # 1. Цены
    try:
        R = prices.report(con)
        low = [r for r in R["rows"] if r["status"] == "low"]
        near = [r for r in R["rows"] if r["status"] == "near"]
        mpn = {"wb": "WB", "ozon": "Ozon"}
        if not R["rrp_count"]:
            g = {"level": "info", "line": "МРЦ не загружены", "details": []}
        elif low:
            g = {"level": "red", "line": f"Ниже МРЦ: {len(low)}" + (f", близко: {len(near)}" if near else ""),
                 "details": [f"{mpn[r['mp']]} {r['article']}: {_n(r['buyer_price'])} ₽ при МРЦ {_n(r['rrp'])} ({r['dev']:+.0f}%)"
                             for r in sorted(low, key=lambda r: r["dev"])[:3]]}
        elif near:
            g = {"level": "amber", "line": f"Близко к МРЦ: {len(near)}",
                 "details": [f"{mpn[r['mp']]} {r['article']}: {_n(r['buyer_price'])} ₽ (+{_f1(r['dev'])}%)"
                             for r in sorted(near, key=lambda r: r["dev"])[:3]]}
        else:
            g = {"level": "ok", "line": "Все цены выше МРЦ", "details": []}
        g.update(key="prices", title="Цены", link="#/prices", checked=R.get("checked"))
        groups.append(g)
    except Exception as e:  # не роняем виджет из-за одного блока
        groups.append({"key": "prices", "title": "Цены", "level": "info", "line": f"ошибка: {e}", "details": [], "link": "#/prices"})

    # 2. Ozon: запас по кластерам
    if wh_ozon:
        try:
            R = wh_ozon(con, {"days": "14", "target": str(s["cover_days"])})
            items = []
            for r in R["rows"]:
                for c, x in r["cells"].items():
                    if x["per_day"] >= s["min_per_day"]:
                        cov = (x["stock"] + x["in_way"]) / x["per_day"]
                        if cov < s["cover_days"]:
                            items.append((cov, r["article"], c, x["per_day"]))
            # сначала красные, внутри — самые продаваемые
            items.sort(key=lambda i: (i[0] >= s["red_days"], -i[3]))
            red = [i for i in items if i[0] < s["red_days"]]
            if items:
                g = {"level": "red" if red else "amber",
                     "line": f"Запас < {s['cover_days']:.0f} дн.: {len(items)}" + (f" (< {s['red_days']:.0f} дн.: {len(red)})" if red else ""),
                     "details": [f"{a} · {c} · {_days(cov)} дн. ({_f1(pd)} шт/день)" for cov, a, c, pd in items[:3]]}
            else:
                g = {"level": "ok", "line": f"Везде запас ≥ {s['cover_days']:.0f} дн.", "details": []}
            g.update(key="ozon", title="Склады Ozon", link="#/wh_ozon", checked=R.get("snapshot"))
            groups.append(g)
        except Exception as e:
            groups.append({"key": "ozon", "title": "Склады Ozon", "level": "info", "line": f"ошибка: {e}", "details": [], "link": "#/wh_ozon"})

    # 3. WB: общий запас + округа без товара + свежесть проверки
    try:
        R = wbplan.plan(con, {"days": "14", "target": str(s["cover_days"])})
        low = sorted([(r["total"]["cover"], r["article"], r["total"]["per_day"]) for r in R["rows"]
                      if r["total"]["per_day"] >= s["min_per_day"] and r["total"]["cover"] is not None
                      and r["total"]["cover"] < s["cover_days"]], key=lambda x: (x[0] >= s["red_days"], -x[2]))
        red = [x for x in low if x[0] < s["red_days"]]
        missing = [(r["article"], wbplan.short(d)) for r in R["rows"] for d, c in r["cells"].items()
                   if c["status"] == "no" and c["per_day"] >= s["min_per_day"]]
        stale = [d for d in wbplan.CHECK_CITY if not R["district_totals"].get(d, {}).get("last_check")
                 or (dt.date.today() - dt.date.fromisoformat(R["district_totals"][d]["last_check"])).days > 7]
        parts, details = [], []
        if low:
            parts.append(f"запас < {s['cover_days']:.0f} дн.: {len(low)}")
            details += [f"{a} · вся Россия · {_days(c)} дн." for c, a, _ in low[:2]]
        if missing:
            parts.append(f"нет в округах: {len(missing)}")
            details += [f"{a} · нет: {d}" for a, d in missing[:2]]
        level = "red" if (red or missing) else ("amber" if low else "ok")
        if stale:
            details.append(f"проверка наличия: {len(stale)} из {len(wbplan.CHECK_CITY)} округов не проверены за неделю")
            if level == "ok":
                level = "info"
        g = {"key": "wb", "title": "Склады WB", "link": "#/wh_wb", "level": level,
             "line": ("; ".join(parts) if parts else f"Общий запас ≥ {s['cover_days']:.0f} дн.").capitalize(),
             "details": details[:3], "checked": R.get("snapshot")}
        groups.append(g)
    except Exception as e:
        groups.append({"key": "wb", "title": "Склады WB", "level": "info", "line": f"ошибка: {e}", "details": [], "link": "#/wh_wb"})

    # 3б. Заказы сегодня против вчера на это же время: резкий рост (акция?) или падение
    try:
        T = today_mod.report(con)
        jump = T["settings"]["jump_rub"]
        cur, prev, dlt = T["totals"]["today"]["all"]["sum"], T["totals"]["yday_same"]["all"]["sum"], T["delta_sum"]
        pc = f" ({T['delta_pct']:+.0f}%)".replace("-", "−") if T["delta_pct"] is not None else ""
        line = f"Сегодня {_n(cur)} ₽ / {_n(T['totals']['today']['all']['qty'])} шт; вчера к этому времени {_n(prev)} ₽"
        if jump and dlt >= jump:
            g = {"level": "amber", "line": f"Резкий рост заказов: +{_n(dlt)} ₽{pc} к вчера на это время",
                 "details": [line] + [f"{'WB' if x['mp'] == 'wb' else 'Ozon'} {x['article']}: +{_n(x['delta'])} ₽ ({_n(x['qty'])} шт)"
                                      for x in T["growth"][:2]] + ["Проверьте, не попал ли товар в акцию, и цены (МРЦ)."]}
        elif jump and dlt <= -jump:
            g = {"level": "amber", "line": f"Резкое падение заказов: −{_n(-dlt)} ₽{pc} к вчера на это время", "details": [line]}
        else:
            g = {"level": "ok", "line": line, "details": []}
        g.update(key="orders", title="Заказы", link="#/dashboard", checked=T.get("checked"))
        groups.insert(0, g)
    except Exception as e:
        groups.insert(0, {"key": "orders", "title": "Заказы", "level": "info", "line": f"ошибка: {e}", "details": [], "link": "#/dashboard"})

    # 3в. Поставки: приняты, а документы (акт, УПД) ещё не отмечены
    try:
        R = supplies_mod.report(con)
        if R["rows"]:
            pend = [r for r in R["rows"] if r["docs_pending"]]
            way = R["counts"]["way"]
            mpn = {"wb": "WB", "ozon": "Ozon"}
            if pend:
                g = {"level": "amber", "line": f"Приняты, нужны документы: {len(pend)}" + (f"; в пути / на приёмке: {way}" if way else ""),
                     "details": [f"{mpn[r['mp']]} №{r['number']} · {r['warehouse'] or '—'} · принято {_n(r['accepted'] or 0)} шт"
                                 for r in pend[:3]]}
            else:
                g = {"level": "ok", "line": (f"В пути / на приёмке: {way}" if way else "Документы по принятым поставкам оформлены"),
                     "details": []}
            g.update(key="supplies", title="Поставки", link="#/supplies", checked=R.get("checked"))
            groups.append(g)
    except Exception as e:
        groups.append({"key": "supplies", "title": "Поставки", "level": "info", "line": f"ошибка: {e}", "details": [], "link": "#/supplies"})

    # 4. Свежесть данных
    last, st = _meta(con, "last_update"), _meta(con, "update_status") or ""
    try:
        age = (dt.datetime.now() - dt.datetime.strptime(last, "%d.%m.%Y %H:%M")).total_seconds() / 3600 if last else None
    except ValueError:
        age = None
    if age is None:
        g = {"level": "amber", "line": "Данные ещё не загружались"}
    elif age > 30:
        g = {"level": "red", "line": f"Данные не обновлялись с {last}"}
    elif "ошибк" in st.lower():
        g = {"level": "amber", "line": f"Последнее обновление с ошибками ({last})"}
    else:
        g = {"level": "ok", "line": f"Обновлено {last}"}
    g.update(key="data", title="Данные", details=[], link="#/dashboard")
    groups.append(g)

    # 5. Готов месячный отчёт (через 3 дня после последней недели месяца — когда придут отчёты WB), пока его не открыли
    try:
        ym = monthly.default_month()
        if _meta(con, "monthly_seen") != ym:
            groups.append({"key": "monthly", "title": "Отчёт", "level": "info", "details": [],
                           "line": f"Готов месячный отчёт: {monthly.title(ym)}", "link": "#/monthly"})
    except Exception:
        pass

    worst = max(groups, key=lambda g: LEVEL[g["level"]])["level"] if groups else "ok"
    return {"level": worst, "groups": groups, "settings": s, "generated": dt.datetime.now().strftime("%d.%m %H:%M")}
