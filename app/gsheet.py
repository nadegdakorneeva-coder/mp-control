# -*- coding: utf-8 -*-
"""Импорт операций из Google Таблицы «РАСХОДЫ» (лист «Мосийчук М.В. 2026»).
Таблица — источник правды: при каждом импорте операции из неё за период с [gsheet] start
удаляются и записываются заново; операции, внесённые вручную в дашборде, не трогаются.

Колонки листа: A дата (только у первой строки дня), B Счет WB, C Счет Ozon, D Счет СБЕР,
F пометка, G тип операции, H наименование, I Игорь, J Наташа, K Олег, L Касса (наличные мимо р/с)."""
import csv, datetime as dt, io, os, re, urllib.request
import db

ACCOUNTS = {1: ("Счет WB", "bank"), 2: ("Счет Ozon", "bank"), 3: ("Счет СБЕР", "bank"),
            8: ("Наличные Игорь", "cash"), 9: ("Наличные Наташа", "cash"), 10: ("Наличные Олег", "cash"),
            11: ("Касса", "cash")}
BANK, CASH = (1, 2, 3), (8, 9, 10, 11)
# Типы, которые по смыслу не являются расходом бизнеса в ОПиУ (выручка МП уже учтена из отчётов,
# закупка — через себестоимость, налоги считаются по ставкам). Остальные можно переключить в «Счета, статьи, налоги».
TYPE_DEFAULTS = {                     # тип: (вид, раздел ДДС, строка ОПиУ) — согласовано с владельцем 29.10.2026
    "поступление вб": ("income", "operating", "none"),
    "поступление озон": ("income", "operating", "none"),
    "закупка товара": ("expense", "operating", "none"),       # уже в себестоимости
    "лицензия": ("expense", "financial", "none"),
    "зп наша": ("expense", "financial", "dividends"),          # вывод денег собственникам
    "без типа": ("expense", "operating", "none"),
    "налог ип": ("expense", "operating", "tax"),
    "налог сотруднники": ("expense", "operating", "opex"),
    "налог сотрудники": ("expense", "operating", "opex"),
    "расходы склад": ("expense", "operating", "opex"),
    "зп сотрудники": ("expense", "operating", "opex"),
    "аренда склад": ("expense", "operating", "opex"),
    "перевозчик": ("expense", "operating", "opex"),
    "банк": ("expense", "operating", "opex"),
    "продажа продукции": ("income", "operating", "none"),       # распродажа неликвида — в ОПиУ не учитываем
}
RULES_VERSION = "gs_rules_v2"


def num(s):
    s = re.sub(r"[\s  ]", "", s or "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(s, year=2026):
    m = re.match(r"^(\d{1,2})[.,](\d{1,2})(?:[.,](\d{2,4}))?$", (s or "").strip())
    if not m:
        return None
    y = int(m.group(3)) if m.group(3) else year
    if y < 100:
        y += 2000
    try:
        return dt.date(y, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
    if raw.lstrip().startswith("<"):
        raise RuntimeError("таблица не открылась по ссылке — включите доступ «Все, у кого есть ссылка: читатель»")
    os.makedirs(os.path.join(db.DATA_DIR, "raw"), exist_ok=True)
    open(os.path.join(db.DATA_DIR, "raw", "gsheet.csv"), "w", encoding="utf-8").write(raw)
    return raw


def parse(raw):
    """Возвращает (строки с датами, остатки на начало листа, итоговую строку листа, исправленные даты)."""
    rows = list(csv.reader(io.StringIO(raw)))
    start_bal = {c: num(rows[1][c]) if len(rows[1]) > c else 0 for c in BANK + CASH}
    # даты: проставляем дату первой строки дня всем строкам дня; явные опечатки (дата из будущего месяца
    # посреди предыдущего) исправляем на месяц соседних строк
    explicit = [(i, parse_date(r[0])) for i, r in enumerate(rows) if i >= 3 and r and parse_date(r[0])]
    fixed, fixes = {}, []
    for k, (i, d) in enumerate(explicit):
        prev = explicit[k - 1][1] if k else None
        nxt = explicit[k + 1][1] if k + 1 < len(explicit) else None
        if prev and nxt and d > nxt + dt.timedelta(days=5) and prev <= nxt:
            try:
                nd = d.replace(month=prev.month, year=prev.year)
            except ValueError:
                nd = prev
            if not (prev <= nd <= nxt):
                nd = prev
            fixes.append((i + 1, rows[i][0], nd.isoformat()))
            d = nd
        fixed[i] = d
    out, cur, empty, totals = [], None, 0, None
    for i in range(3, len(rows)):
        r = rows[i] + [""] * (14 - len(rows[i]))
        if not any(x.strip() for x in r[:12]):
            empty += 1
            if empty >= 3:
                for j in range(i + 1, len(rows)):
                    if any(x.strip() for x in rows[j][:12]):
                        totals = rows[j] + [""] * 14
                        break
                break
            continue
        empty = 0
        if i in fixed:
            cur = fixed[i]
        out.append({"row": i + 1, "date": cur, "amounts": {c: num(r[c]) for c in BANK + CASH if num(r[c])},
                    "note": r[5].strip(), "type": r[6].strip(), "name": r[7].strip()})
    return out, start_bal, totals, fixes


def ensure_accounts(con, opening, start):
    ids = {}
    for col, (name, kind) in ACCOUNTS.items():
        row = con.execute("SELECT id FROM accounts WHERE name=?", (name,)).fetchone()
        if row:
            ids[col] = row[0]
            con.execute("UPDATE accounts SET opening_balance=?, opening_date=? WHERE id=?",
                        (round(opening.get(col, 0), 2), start, row[0]))
        else:
            ids[col] = con.execute("INSERT INTO accounts(name, kind, opening_balance, opening_date) VALUES(?,?,?,?)",
                                   (name, kind, round(opening.get(col, 0), 2), start)).lastrowid
    return ids


def category(con, cache, typ, kind):
    label = typ or "Без типа"
    key = (label, kind)
    if key in cache:
        return cache[key]
    d = TYPE_DEFAULTS.get(label.lower())
    name = label if (not d or d[0] == kind) else f"{label} ({'доход' if kind == 'income' else 'расход'})"
    row = con.execute("SELECT id FROM categories WHERE name=? AND kind=?", (name, kind)).fetchone()
    if row:
        cache[key] = row[0]
        return row[0]
    if d and d[0] == kind:
        group, pnl = d[1], d[2]
    elif label.lower() == "без типа":
        group, pnl = "operating", "none"
    else:
        group, pnl = "operating", ("opex" if kind == "expense" else "fin_income")
    cid = con.execute("INSERT INTO categories(name, kind, dds_group, pnl_line) VALUES(?,?,?,?)",
                      (name, kind, group, pnl)).lastrowid
    cache[key] = cid
    return cid


DEFAULT_URL = ""   # ссылка на таблицу операций — в config.ini, раздел [gsheet], параметр url


def import_sheet(log=print):
    cfg = db.config()
    url = cfg.get("gsheet", "url", fallback="").strip() or DEFAULT_URL
    if not url:
        log("Google Таблица: ссылка не задана в config.ini [gsheet]")
        return None
    start = dt.date.fromisoformat(cfg.get("gsheet", "start", fallback="2026-06-01").strip())
    raw = fetch(url)
    rows, start_bal, totals, fixes = parse(raw)
    # сверка: остатки на начало листа + все строки = итоговая строка листа
    calc = {c: start_bal[c] + sum(r["amounts"].get(c, 0) for r in rows) for c in BANK + CASH}
    check = []
    if totals:
        for c in BANK + CASH:
            if abs(calc[c] - num(totals[c])) > 0.5:
                check.append(f"{ACCOUNTS[c][0]}: посчитано {calc[c]:,.2f}, в таблице {num(totals[c]):,.2f}")
    opening = {c: start_bal[c] + sum(r["amounts"].get(c, 0) for r in rows if r["date"] and r["date"] < start)
               for c in BANK + CASH}
    con = db.init()
    acc = ensure_accounts(con, opening, start.isoformat())
    con.execute("DELETE FROM operations WHERE src='gsheet'")
    if not con.execute("SELECT 1 FROM meta WHERE key=?", (RULES_VERSION,)).fetchone():
        # один раз применяем согласованные правила к уже созданным статьям; дальше их можно менять в настройках
        for cid, nm, k in con.execute("SELECT id, name, kind FROM categories").fetchall():
            rule = TYPE_DEFAULTS.get((nm or "").lower())
            if rule and rule[0] == k:
                con.execute("UPDATE categories SET dds_group=?, pnl_line=? WHERE id=?", (rule[1], rule[2], cid))
            elif (nm or "").startswith("Без типа"):
                con.execute("UPDATE categories SET pnl_line='none' WHERE id=?", (cid,))
        con.execute("INSERT OR REPLACE INTO meta VALUES(?, '1')", (RULES_VERSION,))
    cache, n, warn = {}, 0, []
    def add(kind, amount, d, account, to_account, cat, purpose, official):
        nonlocal n
        con.execute("""INSERT INTO operations(kind, amount, pay_date, accrual_date, account_id, to_account_id, category_id,
                       purpose, official, src, src_key) VALUES(?,?,?,?,?,?,?,?,?, 'gsheet', ?)""",
                    (kind, round(abs(amount), 2), d, d, account, to_account, cat, purpose, official, f"r{r['row']}"))
        n += 1
    for r in rows:
        if not r["date"] or r["date"] < start or not r["amounts"]:
            continue
        d = r["date"].isoformat()
        purpose = r["name"] + (f" [{r['note']}]" if r["note"] else "")
        am = r["amounts"]
        bank_out = [(c, -v) for c, v in am.items() if c in BANK and v < 0]
        cash_in = [(c, v) for c, v in am.items() if c in CASH and v > 0]
        if bank_out and cash_in:
            # деньги сняли со счёта и выдали на руки — это перевод, а не расход
            src_c, total_out = bank_out[0]
            given = 0.0
            for c, v in cash_in:
                add("transfer", v, d, acc[src_c], acc[c], None, purpose, 0)
                given += v
            rest = total_out - given
            if rest > 0.5:
                add("expense", rest, d, acc[src_c], None, category(con, cache, r["type"], "expense"), purpose, 1)
            if abs(rest) > 100:
                warn.append(f"строка {r['row']} ({d}, {r['name']}): со счёта {total_out:,.0f}, на руки {given:,.0f}")
            for c, v in bank_out[1:]:
                add("expense", v, d, acc[c], None, category(con, cache, r["type"], "expense"), purpose, 1)
            continue
        for c, v in am.items():
            kind = "income" if v > 0 else "expense"
            add(kind, v, d, acc[c], None, category(con, cache, r["type"], kind), purpose, 1 if c in BANK else 0)
    con.execute("INSERT OR REPLACE INTO meta VALUES('gsheet_import', ?)",
                (f"{dt.datetime.now():%d.%m.%Y %H:%M}: {n} операций с {start:%d.%m.%Y}",))
    con.commit()
    for row, was, now in fixes:
        log(f"Google Таблица: строка {row} — дата «{was}» выглядит опечаткой, взял {now}")
    for w in warn:
        log(f"Google Таблица: {w}")
    log("Google Таблица: сверка остатков с итоговой строкой " + ("— совпадает" if not check else "— РАСХОЖДЕНИЕ: " + "; ".join(check)))
    log(f"Google Таблица: загружено {n} операций с {start:%d.%m.%Y}")
    return {"operations": n, "fixes": fixes, "check": check, "warnings": warn}


if __name__ == "__main__":
    import_sheet()
