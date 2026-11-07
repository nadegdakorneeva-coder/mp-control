# -*- coding: utf-8 -*-
"""Поставки на склады WB (FBW) и Ozon (FBO): номер, склад, даты, статус, сколько отправлено и принято,
плюс ручные отметки «акт выгружен» и «УПД/ОПД оформлены» — чтобы видеть принятые поставки без документов."""
import datetime as dt

WB_STATUS = {1: "Не запланировано", 2: "Запланировано", 3: "Отгрузка разрешена", 4: "Идёт приёмка",
             5: "Принято", 6: "Отгружено на воротах"}
OZ_STATUS = {
    "DATA_FILLING": "Заполнение данных", "READY_TO_SUPPLY": "Готова к отгрузке",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE": "Принята на точке отгрузки", "IN_TRANSIT": "В пути",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE": "Идёт приёмка на складе", "REPORTS_CONFIRMATION_AWAITING": "Принята — согласование актов",
    "REPORT_REJECTED": "Спор по акту", "COMPLETED": "Завершена (принята)", "REJECTED_AT_SUPPLY_WAREHOUSE": "Отказано в приёмке",
    "CANCELLED": "Отменена", "OVERDUE": "Просрочена",
}
OZ_STATES = ["ORDER_STATE_" + k for k in OZ_STATUS]

# стадии для цвета и фильтров: plan — готовится, way — в пути/приёмка, done — принята, bad — отмена/отказ
STAGE_WB = {1: "plan", 2: "plan", 3: "plan", 4: "way", 5: "done", 6: "way"}
STAGE_OZ = {"DATA_FILLING": "plan", "READY_TO_SUPPLY": "plan", "ACCEPTED_AT_SUPPLY_WAREHOUSE": "way", "IN_TRANSIT": "way",
            "ACCEPTANCE_AT_STORAGE_WAREHOUSE": "way", "REPORTS_CONFIRMATION_AWAITING": "done", "REPORT_REJECTED": "done",
            "COMPLETED": "done", "REJECTED_AT_SUPPLY_WAREHOUSE": "bad", "CANCELLED": "bad", "OVERDUE": "bad"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplies(
  mp TEXT NOT NULL, supply_id TEXT NOT NULL, number TEXT, status_code TEXT, status TEXT, stage TEXT,
  created TEXT, planned TEXT, fact TEXT, updated TEXT, warehouse TEXT, qty REAL, accepted REAL, ready REAL,
  acceptance_cost REAL, note TEXT, loaded_at TEXT, PRIMARY KEY(mp, supply_id));
CREATE TABLE IF NOT EXISTS supply_marks(
  mp TEXT NOT NULL, supply_id TEXT NOT NULL, act INTEGER DEFAULT 0, upd INTEGER DEFAULT 0, comment TEXT,
  updated_at TEXT, PRIMARY KEY(mp, supply_id));
"""


def init(con):
    con.executescript(SCHEMA)
    con.commit()


COLS = ["number", "status_code", "status", "stage", "created", "planned", "fact", "updated", "warehouse",
        "qty", "accepted", "ready", "acceptance_cost", "note"]


def upsert(con, mp, supply_id, **kw):
    """Пишет поставку; поля, которых нет в kw (или None), остаются прежними — детали не затираются кратким списком."""
    vals = [kw.get(c) for c in COLS]
    con.execute(f"""INSERT INTO supplies(mp, supply_id, {', '.join(COLS)}, loaded_at) VALUES(?, ?, {', '.join('?' * len(COLS))}, ?)
                    ON CONFLICT(mp, supply_id) DO UPDATE SET {', '.join(f'{c}=COALESCE(excluded.{c}, {c})' for c in COLS)},
                    loaded_at=excluded.loaded_at""",
                [mp, str(supply_id)] + vals + [dt.datetime.now().strftime("%Y-%m-%d %H:%M")])


def known(con, mp):
    init(con)
    return {r["supply_id"]: dict(r) for r in con.execute("SELECT * FROM supplies WHERE mp=?", (mp,))}


def _meta(con, k, d=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r and r[0] is not None else d


def report(con, q=None):
    init(con)
    rows, since = [], _since(con)
    for r in con.execute("""SELECT s.*, COALESCE(m.act, 0) act, COALESCE(m.upd, 0) upd, m.comment FROM supplies s
                            LEFT JOIN supply_marks m ON m.mp = s.mp AND m.supply_id = s.supply_id
                            ORDER BY COALESCE(s.fact, s.planned, s.created) DESC"""):
        x = dict(r)
        x["docs_pending"] = (x["stage"] == "done" and not (x["act"] and x["upd"])
                             and (x["fact"] or x["updated"] or x["created"] or "") >= since)
        rows.append(x)
    cnt = {k: sum(1 for x in rows if x["stage"] == k) for k in ("plan", "way", "done", "bad")}
    cnt["docs_pending"] = sum(1 for x in rows if x["docs_pending"])
    return {"rows": rows, "counts": cnt, "checked": _meta(con, "supplies_checked"), "marks_from": since,
            "wb_access": _meta(con, "wb_supplies_access"), "oz_access": _meta(con, "oz_supplies_access")}


def save_mark(con, b):
    init(con)
    mp, sid = b.get("mp"), str(b.get("supply_id") or "")
    if mp not in ("wb", "ozon") or not sid:
        raise ValueError("Не указана поставка")
    cur = con.execute("SELECT act, upd, comment FROM supply_marks WHERE mp=? AND supply_id=?", (mp, sid)).fetchone()
    act = int(b["act"]) if "act" in b else (cur["act"] if cur else 0)
    upd = int(b["upd"]) if "upd" in b else (cur["upd"] if cur else 0)
    comment = b["comment"] if "comment" in b else (cur["comment"] if cur else None)
    con.execute("INSERT OR REPLACE INTO supply_marks VALUES(?,?,?,?,?,?)",
                (mp, sid, act, upd, comment, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    con.commit()
    return {"ok": True}


def pending_count(con):
    """Сколько поставок принято, а документы (акт + УПД) ещё не отмечены."""
    try:
        init(con)
        return con.execute("""SELECT COUNT(*) FROM supplies s LEFT JOIN supply_marks m ON m.mp = s.mp AND m.supply_id = s.supply_id
                              WHERE s.stage = 'done' AND NOT (COALESCE(m.act, 0) = 1 AND COALESCE(m.upd, 0) = 1)
                              AND COALESCE(s.fact, s.updated, s.created, '') >= ?""", (_since(con),)).fetchone()[0]
    except Exception:
        return 0


def _since(con):
    """Отметки ведутся с даты первой загрузки поставок: старые принятые поставки не считаются «без документов»."""
    v = _meta(con, "supplies_marks_from")
    if not v:
        v = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        con.execute("INSERT OR REPLACE INTO meta VALUES('supplies_marks_from', ?)", (v,))
        con.commit()
    return v
