# -*- coding: utf-8 -*-
"""Заказы «на сегодня» — как в кабинетах WB и Ozon: сколько штук и на какую сумму заказали с начала дня,
в сравнении со вчера на это же время. Данные — из заказов, которые программа подтягивает каждые 30 минут
(режим collector.py --today). Сумма — по цене до СПП, как колонка «Заказы» в дашборде."""
import datetime as dt


def _meta(con, k, d=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r and r[0] is not None else d


def settings(con):
    return {"jump_rub": float(_meta(con, "alert_orders_jump", 100000))}


def save_settings(con, b):
    if "jump_rub" in b:
        con.execute("INSERT OR REPLACE INTO meta VALUES('alert_orders_jump', ?)", (str(max(0.0, float(b["jump_rub"]))),))
        con.commit()
    return settings(con)


def fbs(con, now):
    """Сборочные задания WB FBS, которые ещё не ушли покупателю: новые, на сборке, собраны и ждут приёмки WB."""
    try:
        rows = con.execute("""SELECT supplier_status ss, wb_status ws, created, article, price FROM fbs_tasks
                              WHERE supplier_status IN ('new', 'confirm') OR (supplier_status = 'complete' AND wb_status = 'waiting')""").fetchall()
    except Exception:
        return None
    out = {"new": 0, "confirm": 0, "waiting": 0, "sum": 0.0, "oldest": None, "items": {},
           "checked": _meta(con, "wb_fbs_checked"), "access": _meta(con, "wb_fbs_access")}
    for r in rows:
        k = "waiting" if r["ss"] == "complete" else r["ss"]
        out[k] += 1
        out["sum"] += r["price"] or 0
        if k in ("new", "confirm") and r["created"] and (not out["oldest"] or r["created"] < out["oldest"]):
            out["oldest"] = r["created"]
        a = out["items"].setdefault(r["article"] or "—", {"article": r["article"] or "—", "new": 0, "confirm": 0, "waiting": 0})
        a[k] += 1
    out["items"] = sorted(out["items"].values(), key=lambda x: -(x["new"] + x["confirm"] + x["waiting"]))[:15]
    if out["oldest"]:
        out["oldest_h"] = (now - dt.datetime.fromisoformat(out["oldest"])).total_seconds() / 3600
    return out


def report(con, now=None, mp=None, scheme=None):
    now = now or dt.datetime.now()
    today, yday = now.date(), now.date() - dt.timedelta(days=1)
    t_now = now.strftime("%H:%M:%S")
    rows = con.execute("""SELECT mp, COALESCE(article, mp_sku) a, dt, REPLACE(COALESCE(ts, dt), ' ', 'T') ts,
                                 qty, price, COALESCE(scheme, 'FBO') scheme FROM orders WHERE dt IN (?, ?)""", (today.isoformat(), yday.isoformat())).fetchall()
    rows = [r for r in rows if (not mp or r["mp"] == mp) and (not scheme or r["scheme"] == scheme)]
    def zero():
        return {"qty": 0.0, "sum": 0.0}
    tot = {k: {"wb": zero(), "ozon": zero(), "all": zero(), "wb_fbo": zero(), "wb_fbs": zero()}
           for k in ("today", "yday_same", "yday_full")}
    hours = {"today": [0.0] * 24, "yday": [0.0] * 24}
    arts = {}
    last = {}
    for r in rows:
        q, s = r["qty"] or 1, (r["price"] or 0) * (r["qty"] or 1)
        tm = (r["ts"][11:19] if len(r["ts"]) >= 19 else "00:00:00")
        h = int(tm[:2]) if tm[:2].isdigit() else 0
        if r["dt"] == today.isoformat():
            keys = ["today"]
            hours["today"][h] += s
            a = arts.setdefault((r["mp"], r["a"]), {"mp": r["mp"], "article": r["a"], "qty": 0, "sum": 0, "y_qty": 0, "y_sum": 0, "fbs_qty": 0})
            a["qty"] += q; a["sum"] += s
            if r["scheme"] == "FBS":
                a["fbs_qty"] += q
            last[r["mp"]] = max(last.get(r["mp"], ""), r["ts"])
        else:
            keys = ["yday_full"] + (["yday_same"] if tm <= t_now else [])
            hours["yday"][h] += s
            if tm <= t_now:
                a = arts.setdefault((r["mp"], r["a"]), {"mp": r["mp"], "article": r["a"], "qty": 0, "sum": 0, "y_qty": 0, "y_sum": 0, "fbs_qty": 0})
                a["y_qty"] += q; a["y_sum"] += s
        for k in keys:
            for m in (r["mp"], "all") + ((f"wb_{r['scheme'].lower()}",) if r["mp"] == "wb" else ()):
                tot[k][m]["qty"] += q
                tot[k][m]["sum"] += s
    cum = {}
    for k, arr in hours.items():
        acc, out = 0.0, []
        for v in arr:
            acc += v
            out.append(acc)
        cum[k] = out
    items = sorted(arts.values(), key=lambda x: -(x["sum"] - x["y_sum"]))
    for x in items:
        x["delta"] = x["sum"] - x["y_sum"]
    d = tot["today"]["all"]["sum"] - tot["yday_same"]["all"]["sum"]
    return {"now": now.strftime("%Y-%m-%d %H:%M"), "today": today.isoformat(), "yday": yday.isoformat(),
            "totals": tot, "delta_sum": d,
            "delta_pct": (d / tot["yday_same"]["all"]["sum"] * 100) if tot["yday_same"]["all"]["sum"] else None,
            "cum": cum, "hour_now": now.hour, "top": sorted([x for x in items if x["sum"]], key=lambda x: -x["sum"])[:10],
            "growth": [x for x in items if x["delta"] > 0][:5], "last_order": last,
            "checked": _meta(con, "today_checked"), "settings": settings(con), "filter": {"mp": mp or "", "scheme": scheme or ""},
            "fbs": fbs(con, now) if mp in (None, "", "wb") and scheme in (None, "", "FBS") else None}
