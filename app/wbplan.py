# -*- coding: utf-8 -*-
"""План поставок Wildberries.

WB не раскрывает остатки по складам (в API везде «Склад WB РФ»), поэтому:
  * спрос по округам берём точно — из заказов;
  * общий остаток раскладываем по округам пропорционально спросу, но только там, где товар есть.
    «Есть / нет на месте» узнаём из сроков доставки, которые сотрудник снимает со страницы магазина
    на WB кнопкой-закладкой (по одному заходу на округ). Срок ≥ порога → товара в округе нет, на месте 0;
  * везти в округ = заказов в день × запас − оценка остатка в округе; округ → склад отгрузки по таблице.
"""
import datetime as dt
import json
import math
import re

RU = ["Центральный федеральный округ", "Северо-Западный федеральный округ", "Южный федеральный округ",
      "Северо-Кавказский федеральный округ", "Приволжский федеральный округ", "Уральский федеральный округ",
      "Сибирский федеральный округ", "Дальневосточный федеральный округ"]
OTHER = "Другие страны"
DEFAULT_MAP = {
    "Центральный федеральный округ": "Коледино",
    "Северо-Западный федеральный округ": "Санкт-Петербург (Шушары)",
    "Южный федеральный округ": "Краснодар",
    "Северо-Кавказский федеральный округ": "Невинномысск",
    "Приволжский федеральный округ": "Казань",
    "Уральский федеральный округ": "Екатеринбург",
    "Сибирский федеральный округ": "Новосибирск",
    "Дальневосточный федеральный округ": "Хабаровск",
    OTHER: "",
}
FRESH_DAYS = 14
# где смотреть сроки: город со складом WB в округе — тогда видно, есть ли товар рядом
CHECK_CITY = {
    "Центральный федеральный округ": "Москва",
    "Северо-Западный федеральный округ": "Санкт-Петербург",
    "Южный федеральный округ": "Краснодар",
    "Северо-Кавказский федеральный округ": "Невинномысск",
    "Приволжский федеральный округ": "Казань",
    "Уральский федеральный округ": "Екатеринбург",
    "Сибирский федеральный округ": "Новосибирск",
    "Дальневосточный федеральный округ": "Хабаровск",
}          # сколько дней действует отметка о наличии
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# город в адресе доставки → округ (для подсказки при вставке)
CITY_DISTRICT = {
    "Центральный": ["москв", "тул", "твер", "калуг", "рязан", "владимир", "ярослав", "иванов", "воронеж", "белгород", "курск",
                    "липецк", "тамбов", "орёл", "орел", "брянск", "смоленск", "кострома", "подольск", "коледино", "электросталь", "химки"],
    "Северо-Западный": ["петербург", "спб", "шушар", "калининград", "мурманск", "архангельск", "вологд", "череповец", "псков",
                        "великий новгород", "петрозаводск", "сыктывкар"],
    "Южный": ["краснодар", "ростов", "волгоград", "астрахан", "севастопол", "симферопол", "сочи", "новороссийск", "майкоп", "элиста"],
    "Северо-Кавказский": ["ставропол", "невинномысск", "махачкал", "грозн", "нальчик", "владикавказ", "пятигорск", "черкесск", "магас"],
    "Приволжский": ["казан", "нижний новгород", "самар", "уф", "перм", "саратов", "ижевск", "ульяновск", "пенз", "оренбург",
                    "киров", "чебоксар", "саранск", "йошкар", "тольятти", "набережные челны"],
    "Уральский": ["екатеринбург", "челябинск", "тюмен", "курган", "сургут", "нижневартовск", "магнитогорск", "ханты", "новый уренгой"],
    "Сибирский": ["новосибирск", "омск", "красноярск", "барнаул", "томск", "кемерово", "новокузнецк", "иркутск", "абакан", "кызыл"],
    "Дальневосточный": ["хабаровск", "владивосток", "якутск", "благовещенск", "чита", "улан-удэ", "южно-сахалинск",
                        "петропавловск", "магадан", "комсомольск"],
}


def init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS wb_presence(
      nm TEXT NOT NULL, district TEXT NOT NULL, days REAL, label TEXT, checked_at TEXT, addr TEXT,
      PRIMARY KEY(nm, district));
    """)
    con.commit()


def _meta(con, k, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r and r[0] is not None else default


def _meta_set(con, k, v):
    con.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def settings(con):
    try:
        m = json.loads(_meta(con, "wb_wh_map", "") or "{}")
    except ValueError:
        m = {}
    wh_map = dict(DEFAULT_MAP)
    wh_map.update({k: v for k, v in m.items() if k in DEFAULT_MAP})
    return {"map": wh_map, "threshold": float(_meta(con, "wb_presence_threshold", 4)),
            "min_qty": int(float(_meta(con, "wb_min_qty", 5)))}


def save_settings(con, b):
    if "map" in b:
        m = {k: (v or "").strip() for k, v in (b.get("map") or {}).items() if k in DEFAULT_MAP}
        _meta_set(con, "wb_wh_map", json.dumps(m, ensure_ascii=False))
    if "threshold" in b:
        _meta_set(con, "wb_presence_threshold", str(max(1.0, float(b["threshold"]))))
    if "min_qty" in b:
        _meta_set(con, "wb_min_qty", str(max(0, int(float(b["min_qty"])))))
    con.commit()
    return settings(con)


def guess_district(addr):
    a = (addr or "").lower()
    for short, keys in CITY_DISTRICT.items():
        if any(k in a for k in keys):
            return next(x for x in RU if x.startswith(short))
    return None


def parse_delivery(text, today):
    """'сегодня' / 'завтра' / 'послезавтра' / '3 ноября' → через сколько дней доставка."""
    t = (text or "").lower()
    if "послезавтра" in t:
        return 2
    if "завтра" in t:
        return 1
    if "сегодня" in t:
        return 0
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")", t)
    if m:
        day, mon = int(m.group(1)), MONTHS.index(m.group(2)) + 1
        for y in (today.year, today.year + 1):
            try:
                dd = dt.date(y, mon, day)
            except ValueError:
                return None
            if dd >= today - dt.timedelta(days=1):
                return (dd - today).days
        return None
    m = re.search(r"через\s+(\d{1,2})", t)
    return int(m.group(1)) if m else None


def import_presence(con, b):
    """b = {district, data: строка из буфера обмена (JSON закладки)}"""
    district = b.get("district")
    if district not in RU + [OTHER]:
        raise ValueError("Выберите округ")
    try:
        data = json.loads(b.get("data") or "")
    except ValueError:
        raise ValueError("Это не данные с WB. Нажмите закладку «WB → дашборд» на странице магазина и вставьте сюда.")
    if not isinstance(data, dict) or data.get("src") != "wb-delivery":
        raise ValueError("Это не данные с WB. Нажмите закладку «WB → дашборд» на странице магазина и вставьте сюда.")
    try:
        at = dt.datetime.fromisoformat(str(data.get("at", "")).replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=3)))
    except ValueError:
        at = dt.datetime.now()
    today = at.date()
    ours = {r[0] for r in con.execute("SELECT mp_sku FROM products WHERE mp='wb'")}
    ours |= {r[0] for r in con.execute("SELECT DISTINCT mp_sku FROM orders WHERE mp='wb'")}
    saved = skipped = unparsed = 0
    for it in data.get("items") or []:
        nm, label = str(it[0]), str(it[1])
        if nm not in ours:
            skipped += 1
            continue
        days = parse_delivery(label, today)
        if days is None:
            unparsed += 1
            continue
        con.execute("""INSERT INTO wb_presence VALUES(?,?,?,?,?,?) ON CONFLICT(nm, district) DO UPDATE SET
                       days=excluded.days, label=excluded.label, checked_at=excluded.checked_at, addr=excluded.addr""",
                    (nm, district, days, label, today.isoformat(), (data.get("addr") or "")[:150]))
        saved += 1
    con.commit()
    return {"saved": saved, "skipped": skipped, "unparsed": unparsed, "district": district,
            "guess": guess_district(data.get("addr")), "addr": data.get("addr") or ""}


def clear_presence(con, district=None):
    if district:
        con.execute("DELETE FROM wb_presence WHERE district=?", (district,))
    else:
        con.execute("DELETE FROM wb_presence")
    con.commit()
    return {"ok": True}


def plan(con, q):
    s = settings(con)
    days = int(q.get("days") or 14)
    target = float(q.get("target") or 30)
    thr, min_qty, wh_map = s["threshold"], s["min_qty"], s["map"]
    to = q.get("to") or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    f = (dt.date.fromisoformat(to) - dt.timedelta(days=days - 1)).isoformat()
    fresh_from = (dt.date.today() - dt.timedelta(days=FRESH_DAYS)).isoformat()

    dist = lambda reg: reg if reg in RU else OTHER
    agg, nm_of, name_of = {}, {}, {}
    for r in con.execute("""SELECT COALESCE(article, mp_sku) a, MAX(mp_sku) nm, COALESCE(region, '') reg, SUM(qty) q
                            FROM orders WHERE mp='wb' AND is_cancel=0 AND dt BETWEEN ? AND ? GROUP BY 1, 3""", (f, to)):
        k = (r["a"], dist(r["reg"]))
        agg[k] = agg.get(k, 0) + (r["q"] or 0)
        nm_of.setdefault(r["a"], r["nm"])
    for r in con.execute("SELECT article, mp_sku, name FROM products WHERE mp='wb'"):
        a = r["article"] or r["mp_sku"]
        nm_of.setdefault(a, r["mp_sku"])
        if r["name"]:
            name_of[a] = r["name"]
    snap = con.execute("SELECT MAX(snap_date) FROM stocks WHERE mp='wb'").fetchone()[0]
    stock = {}
    if snap:
        for r in con.execute("""SELECT COALESCE(article, mp_sku) a, MAX(mp_sku) nm, SUM(qty) q, SUM(to_client) tc
                                FROM stocks WHERE mp='wb' AND snap_date=? GROUP BY 1""", (snap,)):
            stock[r["a"]] = (r["q"] or 0, r["tc"] or 0)
            nm_of.setdefault(r["a"], r["nm"])
    pres = {}
    for r in con.execute("SELECT * FROM wb_presence WHERE checked_at >= ?", (fresh_from,)):
        pres[(r["nm"], r["district"])] = r
    districts = [x for x in RU + [OTHER] if any(k[1] == x for k in agg) or x in RU]

    rows = []
    for a in sorted({k[0] for k in agg} | set(stock)):
        S, tc = stock.get(a, (0, 0))
        nm = str(nm_of.get(a) or "")
        P = {x: agg.get((a, x), 0) / days for x in districts}
        Ptot = sum(P.values())
        cells = {}
        for x in districts:
            p = pres.get((nm, x))
            status = "unknown" if not p else ("no" if p["days"] >= thr else "yes")
            cells[x] = {"orders": agg.get((a, x), 0), "per_day": P[x], "share": P[x] / Ptot * 100 if Ptot else 0,
                        "keep": P[x] * target, "status": status, "days": p["days"] if p else None,
                        "label": p["label"] if p else None, "checked": p["checked_at"] if p else None}
        avail = sum(P[x] for x in districts if cells[x]["status"] != "no")
        for x in districts:
            c = cells[x]
            c["est"] = 0 if c["status"] == "no" or avail <= 0 else S * P[x] / avail
            c["need"] = max(0.0, c["keep"] - c["est"])
            c["ship"] = math.ceil(c["need"] - 1e-9) if wh_map.get(x) and c["need"] > 0 else 0
        # округа → склады; мелкие партии (< min_qty) переносим на самый крупный склад артикула
        wh = {}
        for x in districts:
            if cells[x]["ship"]:
                wh[wh_map[x]] = wh.get(wh_map[x], 0) + cells[x]["ship"]
        if wh and min_qty > 1:
            big = max(wh, key=wh.get)
            for w in list(wh):
                if w != big and wh[w] < min_qty:
                    wh[big] += wh.pop(w)
        total = {"orders": sum(c["orders"] for c in cells.values()), "per_day": Ptot, "stock": S, "to_client": tc,
                 "cover": (S / Ptot if Ptot > 0 else (None if S == 0 else 999)),
                 "need": sum(wh.values()), "need_simple": max(0.0, Ptot * target - S),
                 "missing": sum(1 for x in RU if cells[x]["status"] == "no" and cells[x]["per_day"] > 0)}
        rows.append({"article": a, "nm": nm, "name": name_of.get(a, ""), "cells": cells, "total": total, "wh": wh})
    rows.sort(key=lambda r: -r["total"]["orders"])

    all_pd = sum(r["total"]["per_day"] for r in rows)
    dtot = {}
    for x in districts:
        pd = sum(r["cells"][x]["per_day"] for r in rows)
        chk = [r["cells"][x] for r in rows if r["cells"][x]["status"] != "unknown"]
        last = max((c["checked"] for c in chk), default=None)
        dtot[x] = {"per_day": pd, "share": pd / all_pd * 100 if all_pd else 0,
                   "keep": sum(r["cells"][x]["keep"] for r in rows), "est": sum(r["cells"][x]["est"] for r in rows),
                   "need": sum(r["cells"][x]["ship"] for r in rows), "warehouse": wh_map.get(x, ""),
                   "checked": len(chk), "missing": sum(1 for c in chk if c["status"] == "no"), "last_check": last}
    whs = {}
    for r in rows:
        for w, n in r["wh"].items():
            t = whs.setdefault(w, {"warehouse": w, "qty": 0, "articles": 0,
                                   "districts": sorted({short(x) for x in districts if wh_map.get(x) == w})})
            t["qty"] += n; t["articles"] += 1
    total = {"per_day": all_pd, "stock": sum(r["total"]["stock"] for r in rows),
             "need": sum(r["total"]["need"] for r in rows),
             "need_simple": sum(r["total"]["need_simple"] for r in rows)}
    total["cover"] = total["stock"] / all_pd if all_pd else None
    m = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
    return {"districts": districts, "rows": rows, "district_totals": dtot, "warehouses": sorted(whs.values(), key=lambda w: -w["qty"]),
            "total": total, "from": f, "to": to, "days": days, "target": target, "snapshot": snap,
            "snapshot_at": m.get("wb_wh_snapshot") or m.get("last_update"), "settings": s, "fresh_days": FRESH_DAYS,
            "check_city": CHECK_CITY,
            "city_district": {next(x for x in RU if x.startswith(k)): v for k, v in CITY_DISTRICT.items()}}


def short(x):
    return x.replace(" федеральный округ", "")


def plan_xlsx(con, q):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    R = plan(con, q)
    rd = lambda s: ".".join(reversed(s.split("-"))) if s else ""
    bar = {r["mp_sku"]: r["barcode"] for r in con.execute("SELECT mp_sku, barcode FROM products WHERE mp='wb'")}
    wb = openpyxl.Workbook()
    head_fill = PatternFill("solid", fgColor="E5EFFB")
    red = PatternFill("solid", fgColor="FBE9E7")
    thin = Border(bottom=Side(style="thin", color="C3C2B7"))
    bold = Font(bold=True)
    note = (f"Спрос: заказы без отмен за {rd(R['from'])}–{rd(R['to'])} ({R['days']} дн.). Запас: {R['target']:g} дн. "
            f"Остаток WB на {rd(R['snapshot'] or '')} (общий, WB не раскрывает склады). Остаток разложен по округам по доле спроса; "
            f"где по срокам доставки товара нет (≥ {R['settings']['threshold']:g} дн.), на месте считается 0. "
            f"Партии меньше {R['settings']['min_qty']} шт. перенесены на основной склад артикула.")

    def header(ws, title, cols, widths):
        ws.append([title]); ws["A1"].font = Font(bold=True, size=13)
        ws.append([note]); ws["A2"].font = Font(italic=True, color="52514E")
        ws.append([]); ws.append(cols)
        for i, _ in enumerate(cols, 1):
            c = ws.cell(row=4, column=i); c.font = bold; c.fill = head_fill; c.border = thin
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A5"

    ws = wb.active; ws.title = "Сводка"
    header(ws, "План поставок Wildberries — по складам", ["Склад", "Округа", "Артикулов", "Везти, шт"], [28, 44, 12, 12])
    for w in R["warehouses"]:
        ws.append([w["warehouse"], ", ".join(w["districts"]), w["articles"], w["qty"]])
    ws.append([]); ws.append(["Итого", None, None, R["total"]["need"]])
    ws.cell(row=ws.max_row, column=1).font = bold; ws.cell(row=ws.max_row, column=4).font = bold

    cols = ["Артикул", "Название", "Артикул WB", "Баркод", "Везти, шт", "Заказов в день (округа склада)", "Остаток WB всего", "Нет на месте"]
    widths = [18, 46, 13, 16, 10, 14, 12, 12]
    ws = wb.create_sheet("Все склады")
    header(ws, "План поставок Wildberries — все позиции", ["Склад"] + cols, [24] + widths)
    per_wh = {}
    for r in R["rows"]:
        for w, n in r["wh"].items():
            ds = [x for x in R["districts"] if R["settings"]["map"].get(x) == w]
            pd = sum(r["cells"][x]["per_day"] for x in ds)
            miss = any(r["cells"][x]["status"] == "no" for x in ds)
            line = [r["article"], r["name"], r["nm"], bar.get(r["nm"]), n, round(pd, 2), r["total"]["stock"], "да" if miss else ""]
            per_wh.setdefault(w, []).append(line)
    for w in [x["warehouse"] for x in R["warehouses"]]:
        for line in sorted(per_wh.get(w, []), key=lambda l: -l[4]):
            ws.append([w] + line)
            if line[7]:
                ws.cell(row=ws.max_row, column=9).fill = red
    for w in [x["warehouse"] for x in R["warehouses"]]:
        name = re.sub(r"[\\/*?:\[\]]", "", w)[:31] or "Склад"
        ws = wb.create_sheet(name)
        header(ws, f"Поставка на склад {w}", cols, widths)
        for line in sorted(per_wh.get(w, []), key=lambda l: -l[4]):
            ws.append(line)
            if line[7]:
                ws.cell(row=ws.max_row, column=8).fill = red
        ws.append([]); ws.append(["Итого", None, None, None, sum(l[4] for l in per_wh.get(w, []))])
        ws.cell(row=ws.max_row, column=1).font = bold; ws.cell(row=ws.max_row, column=5).font = bold
    import io
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()
