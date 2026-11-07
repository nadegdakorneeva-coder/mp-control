# -*- coding: utf-8 -*-
"""База данных дашборда (SQLite): схема и начальные справочники."""
import os, sqlite3, configparser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "mp.sqlite")
CONFIG_PATH = os.path.join(ROOT, "config.ini")

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops(
  id INTEGER PRIMARY KEY, mp TEXT NOT NULL, name TEXT NOT NULL);

-- Карточки товаров маркетплейсов
CREATE TABLE IF NOT EXISTS products(
  mp TEXT NOT NULL, mp_sku TEXT NOT NULL, article TEXT, name TEXT, brand TEXT,
  category TEXT, barcode TEXT, photo TEXT,
  PRIMARY KEY(mp, mp_sku));

-- Заказы (1 строка = 1 заказ/отправление по артикулу)
CREATE TABLE IF NOT EXISTS orders(
  mp TEXT NOT NULL, order_key TEXT NOT NULL, dt TEXT NOT NULL, ts TEXT,
  article TEXT, mp_sku TEXT, scheme TEXT, qty REAL DEFAULT 1,
  price REAL DEFAULT 0,      -- цена до СПП (со скидкой продавца)
  paid REAL DEFAULT 0,       -- цена для покупателя (после СПП)
  warehouse TEXT, region TEXT, is_cancel INTEGER DEFAULT 0, status TEXT,
  PRIMARY KEY(mp, order_key));
CREATE INDEX IF NOT EXISTS ix_orders_dt ON orders(dt);

-- Финансовые строки: всё из отчётов реализации WB и транзакций Ozon,
-- разложенное по статьям (metric). Суммы со знаком: продажа +, возврат −.
CREATE TABLE IF NOT EXISTS fin(
  mp TEXT NOT NULL, line_key TEXT NOT NULL, metric TEXT NOT NULL,
  dt TEXT NOT NULL, article TEXT, mp_sku TEXT, scheme TEXT,
  amount REAL DEFAULT 0, qty REAL DEFAULT 0, source TEXT,
  PRIMARY KEY(mp, line_key, metric));
CREATE INDEX IF NOT EXISTS ix_fin_dt ON fin(dt, metric);
CREATE INDEX IF NOT EXISTS ix_fin_sku ON fin(mp_sku);

-- Снимки остатков
CREATE TABLE IF NOT EXISTS stocks(
  snap_date TEXT NOT NULL, mp TEXT NOT NULL, mp_sku TEXT NOT NULL, article TEXT,
  warehouse TEXT NOT NULL, scheme TEXT, qty REAL DEFAULT 0,
  to_client REAL DEFAULT 0, from_client REAL DEFAULT 0,
  PRIMARY KEY(snap_date, mp, mp_sku, warehouse));

-- Себестоимость (с историей по дате начала действия)
CREATE TABLE IF NOT EXISTS costs(
  mp TEXT, mp_sku TEXT NOT NULL, article TEXT, barcode TEXT,
  scheme TEXT NOT NULL,              -- FBO / FBS
  cost REAL DEFAULT 0, fulfillment REAL DEFAULT 0, nds REAL DEFAULT 0,
  valid_from TEXT NOT NULL DEFAULT '2000-01-01',
  PRIMARY KEY(mp_sku, scheme, valid_from));
CREATE INDEX IF NOT EXISTS ix_costs_art ON costs(article, scheme);

-- ===== Финансы (ДДС / Операции) =====
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT DEFAULT 'bank',
  opening_balance REAL DEFAULT 0, opening_date TEXT DEFAULT '2026-01-01',
  archived INTEGER DEFAULT 0);

-- dds_group: operating / financial / investing
-- pnl_line: opex | fin_income | inv_income | fin_expense | inv_expense | tax | dividends | none
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
  dds_group TEXT DEFAULT 'operating', pnl_line TEXT DEFAULT 'none',
  archived INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS operations(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                -- income / expense / transfer
  amount REAL NOT NULL,              -- с НДС, всегда положительная
  nds REAL DEFAULT 0,
  pay_date TEXT NOT NULL,            -- дата списания/поступления (ДДС)
  accrual_date TEXT,                 -- дата распределения (ОПиУ)
  distribute_months INTEGER DEFAULT 1,
  account_id INTEGER, to_account_id INTEGER, category_id INTEGER,
  counterparty TEXT, project TEXT, purpose TEXT,
  is_planned INTEGER DEFAULT 0, official INTEGER DEFAULT 0,
  series_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_ops_pay ON operations(pay_date);

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

-- Остатки по складам (Ozon — официальный отчёт по складам)
CREATE TABLE IF NOT EXISTS wh_stocks(
  snap_date TEXT NOT NULL, mp TEXT NOT NULL, mp_sku TEXT NOT NULL, article TEXT, name TEXT,
  warehouse TEXT NOT NULL, cluster TEXT,
  free REAL DEFAULT 0, promised REAL DEFAULT 0, reserved REAL DEFAULT 0,
  PRIMARY KEY(snap_date, mp, mp_sku, warehouse));
-- Склад → кластер
CREATE TABLE IF NOT EXISTS wh_cluster(mp TEXT NOT NULL, warehouse TEXT NOT NULL, cluster TEXT, PRIMARY KEY(mp, warehouse));
"""

DEFAULT_CATEGORIES = [
    # name, kind, dds_group, pnl_line
    ("Поступления от Wildberries", "income", "operating", "none"),
    ("Поступления от Ozon", "income", "operating", "none"),
    ("Прочие доходы", "income", "operating", "fin_income"),
    ("Займы и кредиты полученные", "income", "financial", "none"),
    ("Вложения собственника", "income", "financial", "none"),
    ("Закупка товара", "expense", "operating", "none"),
    ("Фулфилмент и упаковка", "expense", "operating", "opex"),
    ("Доставка до складов МП", "expense", "operating", "opex"),
    ("Зарплата и подрядчики", "expense", "operating", "opex"),
    ("Аренда", "expense", "operating", "opex"),
    ("Дизайн, фото, контент", "expense", "operating", "opex"),
    ("Внешняя реклама и блогеры", "expense", "operating", "opex"),
    ("Сервисы и программы", "expense", "operating", "opex"),
    ("Банковские комиссии", "expense", "operating", "opex"),
    ("Прочие расходы", "expense", "operating", "opex"),
    ("Налоги (УСН, НДС)", "expense", "operating", "none"),
    ("Проценты по кредитам", "expense", "financial", "fin_expense"),
    ("Возврат займов и кредитов", "expense", "financial", "none"),
    ("Покупка оборудования", "expense", "investing", "none"),
    ("Дивиденды", "expense", "financial", "dividends"),
]


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init():
    con = connect()
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM shops").fetchone():
        con.executemany("INSERT INTO shops(id, mp, name) VALUES(?,?,?)",
                        [(1, "wb", "Mocheqi"), (2, "ozon", "Mocheqi_Ozon")])
    if not con.execute("SELECT 1 FROM categories").fetchone():
        con.executemany("INSERT INTO categories(name, kind, dds_group, pnl_line) VALUES(?,?,?,?)",
                        DEFAULT_CATEGORIES)
    if not con.execute("SELECT 1 FROM accounts").fetchone():
        con.execute("INSERT INTO accounts(name, kind) VALUES('Расчётный счёт', 'bank')")
    cols = {r[1] for r in con.execute("PRAGMA table_info(orders)")}
    for c in ("cluster_from", "cluster_to", "city"):
        if c not in cols:
            con.execute(f"ALTER TABLE orders ADD COLUMN {c} TEXT")
    ocols = {r[1] for r in con.execute("PRAGMA table_info(operations)")}
    for c in ("src", "src_key"):
        if c not in ocols:
            con.execute(f"ALTER TABLE operations ADD COLUMN {c} TEXT")
    # разовая правка: даты заказов Ozon были в UTC — переводим в московское время
    if not con.execute("SELECT 1 FROM meta WHERE key='mig_oz_msk'").fetchone():
        con.execute("UPDATE orders SET dt = date(datetime(substr(ts,1,19), '+3 hours')), ts = datetime(substr(ts,1,19), '+3 hours') WHERE mp='ozon' AND ts != ''")
        con.execute("INSERT INTO meta VALUES('mig_oz_msk','1')")
    seed = os.path.join(APP_DIR, "costs_seed.json")
    if os.path.exists(seed) and not con.execute("SELECT 1 FROM costs").fetchone():
        import json
        for r in json.load(open(seed, encoding="utf-8")):
            con.execute("""INSERT OR REPLACE INTO costs(mp, mp_sku, article, barcode, scheme, cost, fulfillment, nds, valid_from)
                           VALUES(?,?,?,?,?,?,?,?,'2000-01-01')""",
                        (r["mp"], r["mp_sku"], r["article"], r["barcode"], r["scheme"], r["cost"], r["fulfillment"], r["nds"]))
    con.commit()
    return con


def config():
    cfg = configparser.ConfigParser(interpolation=None)   # без подстановок: в ссылках и ключах бывает «%»
    cfg.read(CONFIG_PATH, encoding="utf-8-sig")
    return cfg


def tax_settings():
    cfg = config()
    def num(key, default):
        try:
            return float(cfg.get("tax", key, fallback=str(default)).strip().replace(",", ".") or default)
        except ValueError:
            return default
    mode = "rates"
    try:
        c = connect()
        r = c.execute("SELECT value FROM meta WHERE key='tax_mode'").fetchone()
        mode = (r[0] if r else "actual") or "actual"
        c.close()
    except Exception:
        pass
    return {"usn": num("usn_percent", 6.0), "nds": num("nds_percent", 0.0),
            "base": cfg.get("tax", "base", fallback="sales").strip() or "sales", "mode": mode}
