# -*- coding: utf-8 -*-
"""Ежедневная копия базы (03:30): data/backups/mp-ГГГГ-ММ-ДД.sqlite, хранятся 14 последних."""
import datetime as dt, glob, os, sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "mp.sqlite")
OUT = os.path.join(ROOT, "data", "backups")
KEEP = 14

if os.path.exists(DB):
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"mp-{dt.date.today():%Y-%m-%d}.sqlite")
    src, bak = sqlite3.connect(DB), sqlite3.connect(dst)
    with bak:
        src.backup(bak)          # безопасно при работающем дашборде
    src.close(); bak.close()
    for old in sorted(glob.glob(os.path.join(OUT, "mp-*.sqlite")))[:-KEEP]:
        os.remove(old)
    print("копия:", dst)
