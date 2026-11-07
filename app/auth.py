# -*- coding: utf-8 -*-
"""Пользователи, роли и сессии. Пока нет ни одного пользователя, дашборд открыт без входа
(как раньше); после создания первого администратора вход обязателен."""
import hashlib, json, os, re, secrets, sqlite3, time

PAGES = ["dashboard", "summary", "monthly", "wh_ozon", "wh_wb", "supplies", "dds", "pnl", "operations", "costs", "prices", "photos", "promos", "settings"]
PAGE_NAMES = {"dashboard": "Дашборд", "summary": "Сводный отчёт", "monthly": "Месячный отчёт", "wh_ozon": "Склады — Ozon", "wh_wb": "Склады — Wildberries", "supplies": "Склады — Поставки",
              "dds": "ДДС", "pnl": "ОПиУ", "operations": "Операции", "costs": "Себестоимость", "prices": "Контроль цен", "photos": "Маркетинг — Фотоконтент", "promos": "Маркетинг — Акции",
              "settings": "Счета, статьи, налоги"}
SESSION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, phone TEXT UNIQUE NOT NULL, name TEXT, role TEXT DEFAULT 'user',
  pages TEXT DEFAULT '[]', salt TEXT, pass_hash TEXT, active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expires REAL);
"""

# какие API-разделы требуют какой страницы
API_PAGE = {"dashboard": "dashboard", "chart": "dashboard", "today": "dashboard", "summary": "summary", "monthly": "monthly", "pnl": "pnl", "dds": "dds", "operations": "operations",
            "costs": "costs", "prices": "prices", "supplies": "supplies", "media": "photos", "promos": "promos", "accounts": "settings", "categories": "settings", "settings": "settings"}


def init(con):
    con.executescript(SCHEMA)
    con.commit()


def norm_phone(p):
    d = re.sub(r"\D", "", p or "")
    if len(d) == 11 and d[0] == "8":
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), 200_000).hex()


def has_users(con):
    return bool(con.execute("SELECT 1 FROM users WHERE active=1").fetchone())


def user_pages(u):
    if not u:
        return PAGES
    if u["role"] == "admin":
        return PAGES
    try:
        return [p for p in json.loads(u["pages"] or "[]") if p in PAGES]
    except ValueError:
        return []


def login(con, phone, password):
    u = con.execute("SELECT * FROM users WHERE phone=? AND active=1", (norm_phone(phone),)).fetchone()
    if not u or not u["pass_hash"] or _hash(password or "", u["salt"]) != u["pass_hash"]:
        time.sleep(0.7)
        return None
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions VALUES(?,?,?)", (token, u["id"], time.time() + SESSION_DAYS * 86400))
    con.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (u["id"],))
    con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    con.commit()
    return token


def logout(con, token):
    con.execute("DELETE FROM sessions WHERE token=?", (token,))
    con.commit()


def session_user(con, token):
    if not token:
        return None
    r = con.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                       WHERE s.token=? AND s.expires>? AND u.active=1""", (token, time.time())).fetchone()
    return r


def save_user(con, b, uid=None):
    phone = norm_phone(b.get("phone"))
    other = con.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone()
    if other and other["id"] != uid:
        raise ValueError("Пользователь с таким телефоном уже есть")
    if len(phone) != 11:
        raise ValueError("Телефон должен содержать 11 цифр, например +7 910 123-45-67")
    role = "admin" if b.get("role") == "admin" else "user"
    pages = json.dumps([p for p in (b.get("pages") or []) if p in PAGES])
    pwd = b.get("password") or ""
    if not uid and len(pwd) < 6:
        raise ValueError("Пароль — не короче 6 символов")
    if pwd and len(pwd) < 6:
        raise ValueError("Пароль — не короче 6 символов")
    if uid:
        con.execute("UPDATE users SET phone=?, name=?, role=?, pages=?, active=? WHERE id=?",
                    (phone, b.get("name"), role, pages, 1 if b.get("active", True) else 0, uid))
        if pwd:
            salt = secrets.token_hex(8)
            con.execute("UPDATE users SET salt=?, pass_hash=? WHERE id=?", (salt, _hash(pwd, salt), uid))
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        if not b.get("active", True):
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    else:
        salt = secrets.token_hex(8)
        uid = con.execute("INSERT INTO users(phone, name, role, pages, salt, pass_hash) VALUES(?,?,?,?,?,?)",
                          (phone, b.get("name"), role, pages, salt, _hash(pwd, salt))).lastrowid
    # нельзя остаться без активного администратора
    if not con.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():
        con.rollback()
        raise ValueError("Должен остаться хотя бы один активный администратор")
    con.commit()
    return uid


def list_users(con):
    return [{"id": r["id"], "phone": r["phone"], "name": r["name"], "role": r["role"], "active": r["active"],
             "pages": json.loads(r["pages"] or "[]"), "last_login": r["last_login"]}
            for r in con.execute("SELECT * FROM users ORDER BY role, name")]
