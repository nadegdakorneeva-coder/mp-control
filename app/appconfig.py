# -*- coding: utf-8 -*-
"""Раздел «Настройки»: ключи API, налоги, магазин, сеть — правка config.ini из интерфейса (только администратор).
Ключи хранятся в config.ini рядом с программой (на сервере файл закрыт для всех, кроме программы).
В интерфейс ключи целиком не отдаются — только последние 4 символа."""
import configparser
import datetime as dt
import json
import os
import urllib.error
import urllib.request

import db

# (раздел, ключ, подпись, тип, подсказка). Типы: secret, text, num, select:<v1=подпись|v2=подпись>, bool
FIELDS = [
    ("shop", "name", "Название магазина", "text", "показывается в меню и в заголовке; по умолчанию MP Control"),
    ("wb", "token", "WB: основной ключ (только чтение)", "secret",
     "Кабинет WB → Профиль → Настройки → Доступ к API → Создать токен, тип «Базовый», «Только на чтение». "
     "Категории: Контент, Статистика, Аналитика, Цены и скидки, Маркетплейс, Поставки, Продвижение, Финансы, Документы."),
    ("wb", "content_token", "WB: ключ для изменения фото (Контент, запись)", "secret",
     "Отдельный токен с категорией «Контент» БЕЗ галочки «Только на чтение». Нужен только для раздела «Маркетинг → Фотоконтент»."),
    ("ozon", "client_id", "Ozon: Client ID", "text", "Кабинет Ozon → Настройки → API ключи"),
    ("ozon", "api_key", "Ozon: API-ключ", "secret", "Роль «Admin read only» — для загрузки данных; для замены фото позже понадобится ключ с правом записи"),
    ("tax", "usn_percent", "УСН, %", "num", "ставка налога по УСН (6 для «Доходы», 15 для «Доходы − расходы»)"),
    ("tax", "nds_percent", "НДС, %", "num", "0 — если НДС не платите; иначе 5, 7, 10, 20"),
    ("tax", "base", "Налоговая база", "select:sales=фактические продажи|realization=реализация (до СПП)|for_pay=сумма к перечислению",
     "с какой суммы считается налог в режиме «по ставкам»"),
    ("gsheet", "url", "Google Таблица с операциями", "text", "ссылка на экспорт CSV листа с операциями; пусто — импорт выключен"),
    ("gsheet", "start", "Операции из таблицы с даты", "text", "ГГГГ-ММ-ДД"),
    ("server", "network", "Доступ из сети", "bool", "открывать дашборд другим устройствам (нужен хотя бы один пользователь). Действует после перезапуска"),
    ("server", "port", "Порт", "num", "по умолчанию 8766; действует после перезапуска"),
]
DEFAULTS = {("shop", "name"): "MP Control", ("tax", "usn_percent"): "6", ("tax", "nds_percent"): "0", ("tax", "base"): "sales",
            ("gsheet", "start"): "2026-06-01", ("server", "network"): "0", ("server", "port"): "8766"}
COMMENTS = {"shop": "Магазин", "wb": "Wildberries", "ozon": "Ozon", "tax": "Налоги (режим «по ставкам»)",
            "gsheet": "Google Таблица с операциями", "server": "Сервер дашборда"}


def _mask(v):
    v = (v or "").strip()
    return ("•••• " + v[-4:]) if len(v) > 8 else ("задан" if v else "")


def read():
    cfg = db.config()
    out = []
    for sec, key, label, typ, hint in FIELDS:
        v = cfg.get(sec, key, fallback=DEFAULTS.get((sec, key), "")).strip()
        item = {"section": sec, "key": key, "label": label, "type": typ, "hint": hint}
        if typ == "secret":
            item.update(is_set=bool(v), masked=_mask(v), value="")
        else:
            item["value"] = v
        out.append(item)
    return {"fields": out, "path": db.CONFIG_PATH, "checks": _last_checks()}


def shop_name():
    return db.config().get("shop", "name", fallback="MP Control").strip() or "MP Control"


def save(b):
    """b = {"section.key": value}. Пустое значение у ключа (secret) — оставить прежний; "-" — удалить."""
    cfg = db.config()
    known = {(s, k): t for s, k, _, t, _ in FIELDS}
    changed = []
    for full, val in (b.get("values") or {}).items():
        sec, _, key = full.partition(".")
        typ = known.get((sec, key))
        if not typ:
            continue
        val = ("" if val is None else str(val)).strip()
        if typ == "secret":
            if val == "":
                continue
            if val == "-":
                val = ""
        elif typ == "num" and val:
            try:
                float(val.replace(",", "."))
            except ValueError:
                raise ValueError(f"«{dict((f'{s}.{k}', l) for s, k, l, _, _ in FIELDS)[full]}»: нужно число")
            val = val.replace(",", ".")
        elif typ == "bool":
            val = "1" if val in ("1", "true", "True", "on", "да") else "0"
        elif typ.startswith("select:"):
            opts = [o.split("=")[0] for o in typ[7:].split("|")]
            if val not in opts:
                continue
        if not cfg.has_section(sec):
            cfg.add_section(sec)
        before = cfg.get(sec, key, fallback=DEFAULTS.get((sec, key), ""))
        cfg.set(sec, key, val)
        if before.strip() != val:
            changed.append(full)
    if changed:
        _write(cfg)
    return {"ok": True, "changed": changed, "restart": any(c.startswith("server.") for c in changed)}


def _write(cfg):
    lines = ["; Настройки дашборда. Меняются в программе: Прочее → Настройки.",
             "; Файл содержит ключи API — никому не пересылайте и не выкладывайте.", ""]
    order = list(COMMENTS) + [s for s in cfg.sections() if s not in COMMENTS]
    for sec in order:
        if not cfg.has_section(sec):
            continue
        lines += [f"; {COMMENTS[sec]}" if sec in COMMENTS else "", f"[{sec}]"]
        for k, v in cfg.items(sec):
            lines.append(f"{k} = {v}")
        lines.append("")
    tmp = db.CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(l for l in lines if l is not None))
    if os.path.exists(db.CONFIG_PATH):
        try:
            import shutil
            shutil.copy2(db.CONFIG_PATH, os.path.join(db.DATA_DIR, "config.ini.bak"))   # прошлая версия на всякий случай
        except Exception:
            pass
    os.replace(tmp, db.CONFIG_PATH)
    try:
        os.chmod(db.CONFIG_PATH, 0o600)
    except Exception:
        pass


# ---------------- проверка ключей ----------------
WB_CATS = [("Контент", "content-api"), ("Статистика", "statistics-api"), ("Аналитика", "seller-analytics-api"),
           ("Цены и скидки", "discounts-prices-api"), ("Маркетплейс (FBS)", "marketplace-api"), ("Поставки", "supplies-api"),
           ("Продвижение", "advert-api"), ("Финансы", "finance-api"), ("Календарь акций", "dp-calendar-api")]


def _get(url, headers, data=None, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 method="POST" if data is not None else "GET", headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()[:2000]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500]
    except Exception as e:
        return 0, str(e).encode()


def _jwt_info(tok):
    """В токене WB (JWT) открыто записаны срок действия и признак «только чтение» — без секретов."""
    try:
        import base64
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        info = {}
        if d.get("exp"):
            info["expires"] = dt.datetime.fromtimestamp(d["exp"]).strftime("%d.%m.%Y")
        return info
    except Exception:
        return {}


def check():
    cfg = db.config()
    res = {"time": dt.datetime.now().strftime("%d.%m.%Y %H:%M"), "wb": [], "wb_content": None, "ozon": None}
    tok = cfg.get("wb", "token", fallback="").strip()
    if tok:
        for name, host in WB_CATS:
            code, _ = _get(f"https://{host}.wildberries.ru/ping", {"Authorization": tok})
            res["wb"].append({"name": name, "ok": code == 200, "code": code})
        res["wb_info"] = _jwt_info(tok)
    ct = cfg.get("wb", "content_token", fallback="").strip()
    if ct:
        code, _ = _get("https://content-api.wildberries.ru/ping", {"Authorization": ct})
        res["wb_content"] = {"ok": code == 200, "code": code, **_jwt_info(ct)}
    oid, okey = cfg.get("ozon", "client_id", fallback="").strip(), cfg.get("ozon", "api_key", fallback="").strip()
    if oid and okey:
        code, body = _get("https://api-seller.ozon.ru/v3/product/list", {"Client-Id": oid, "Api-Key": okey},
                          {"filter": {"visibility": "ALL"}, "last_id": "", "limit": 1})
        res["ozon"] = {"ok": code == 200, "code": code,
                       "error": "" if code == 200 else body.decode("utf-8", "replace")[:200]}
    con = db.connect()
    con.execute("INSERT OR REPLACE INTO meta VALUES('config_check', ?)", (json.dumps(res, ensure_ascii=False),))
    con.commit(); con.close()
    return res


def _last_checks():
    try:
        con = db.connect()
        r = con.execute("SELECT value FROM meta WHERE key='config_check'").fetchone()
        con.close()
        return json.loads(r[0]) if r and r[0] else None
    except Exception:
        return None
