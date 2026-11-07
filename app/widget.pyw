# -*- coding: utf-8 -*-
"""MP Control — маленькое окно поверх всех окон с критическими сигналами:
цены ниже МРЦ, заканчивается товар на складах Ozon / WB, давно не обновлялись данные.
Читает ту же базу, что и дашборд (сервер для работы не нужен). Обновляется каждые 5 минут.
Запуск: widget.bat в папке дашборда. Перетаскивается за заголовок; правая кнопка — меню."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import db  # noqa: E402

REFRESH_MS = 5 * 60 * 1000
try:  # тот же порт, что у сервера ([server] port в config.ini)
    PORT = db.config().getint("server", "port", fallback=8766)
except Exception:
    PORT = 8766
URL = f"http://127.0.0.1:{PORT}/"
STATE = os.path.join(db.DATA_DIR, "widget.json")
COL = {"red": "#c62828", "amber": "#d08700", "ok": "#2e7d32", "info": "#8a8a85"}
HEAD_BG = {"red": "#c62828", "amber": "#b77900", "ok": "#2f6f3a", "info": "#55554f"}
BG, INK, MUTED, LINE = "#fbfbfa", "#1d1d1b", "#6b6b66", "#e3e2dc"
FONT = "Segoe UI"

try:  # чёткий текст на экранах с масштабированием
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


def single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 8766))
        s.listen(1)
        return s
    except OSError:
        return None


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(st, open(STATE, "w", encoding="utf-8"))
    except Exception:
        pass


def compute():
    con = db.connect()
    try:
        import alerts
        import server
        return alerts.compute(con, server.wh_ozon)
    finally:
        con.close()


def server_alive():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def open_dashboard(link=""):
    if not server_alive():
        bat = os.path.join(os.path.dirname(APP), "start.bat")
        if os.path.exists(bat):
            subprocess.Popen(["cmd", "/c", bat], cwd=os.path.dirname(APP),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            for _ in range(30):
                time.sleep(0.3)
                if server_alive():
                    break
    webbrowser.open(URL + link)


class Widget:
    def __init__(self):
        self.st = load_state()
        self.root = tk.Tk()
        self.root.title("MP Control")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self.root.configure(bg=LINE)
        self.collapsed = bool(self.st.get("collapsed"))
        self.prev_red = set()
        self.data = None
        x, y = self.st.get("x"), self.st.get("y")
        if x is None:
            x, y = self.root.winfo_screenwidth() - 360, 60
        self.root.geometry(f"+{x}+{y}")

        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.pack(padx=1, pady=1, fill="both", expand=True)
        self.head = tk.Frame(self.frame, bg=HEAD_BG["info"])
        self.head.pack(fill="x")
        self.title = tk.Label(self.head, text="MP Control · загрузка…", fg="white", bg=HEAD_BG["info"],
                              font=(FONT, 10, "bold"), anchor="w", padx=10, pady=6)
        self.title.pack(side="left", fill="x", expand=True)
        self.btns = []
        for txt, cmd, tip in (("✕", self.quit, "Закрыть"), ("▾", self.toggle, "Свернуть / развернуть"),
                              ("↻", self.refresh, "Обновить")):
            b = tk.Label(self.head, text=txt, fg="white", bg=HEAD_BG["info"], font=(FONT, 10), padx=7, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda e, c=cmd: c())
            self.btns.append(b)
        self.body = tk.Frame(self.frame, bg=BG)
        for w in (self.head, self.title):
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_move)
            w.bind("<ButtonRelease-1>", self.drag_end)
            w.bind("<Double-Button-1>", lambda e: self.toggle())
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Открыть дашборд", command=lambda: open_dashboard())
        self.menu.add_command(label="Обновить сейчас", command=self.refresh)
        self.menu.add_command(label="Свернуть / развернуть", command=self.toggle)
        self.menu.add_separator()
        self.menu.add_command(label="Закрыть виджет", command=self.quit)
        for w in (self.frame, self.head, self.title, self.body):
            w.bind("<Button-3>", self.popup)
        if not self.collapsed:
            self.body.pack(fill="both", expand=True)
        self.refresh()

    # --- перетаскивание ---
    def drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def drag_end(self, e):
        self.st.update(x=self.root.winfo_x(), y=self.root.winfo_y())
        save_state(self.st)

    def popup(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def toggle(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body.pack_forget()
        else:
            self.body.pack(fill="both", expand=True)
        self.st["collapsed"] = self.collapsed
        save_state(self.st)

    def quit(self):
        self.root.destroy()

    # --- данные ---
    def refresh(self):
        self.title.config(text="MP Control · обновляю…")
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            data, err = compute(), None
        except Exception as e:
            data, err = None, str(e)
        self.root.after(0, lambda: self.render(data, err))

    def schedule(self):
        if getattr(self, "_job", None):
            self.root.after_cancel(self._job)
        self._job = self.root.after(REFRESH_MS, self.refresh)

    def set_head(self, level):
        c = HEAD_BG[level]
        for w in [self.head, self.title] + self.btns:
            w.config(bg=c)

    def flash(self, n=8):
        if n <= 0:
            self.set_head(self.data["level"] if self.data else "info")
            return
        self.set_head("red" if n % 2 else "info")
        self.root.after(350, lambda: self.flash(n - 1))

    def render(self, data, err):
        self.schedule()
        for w in self.body.winfo_children():
            w.destroy()
        if err or not data:
            self.set_head("info")
            self.title.config(text="MP Control · нет данных")
            tk.Label(self.body, text=f"Не удалось прочитать базу:\n{err}", fg=MUTED, bg=BG, font=(FONT, 9),
                     justify="left", wraplength=320, padx=10, pady=8).pack(anchor="w")
            return
        self.data = data
        reds = [g for g in data["groups"] if g["level"] == "red"]
        ambers = [g for g in data["groups"] if g["level"] == "amber"]
        summary = "всё в порядке" if not reds and not ambers else \
            ", ".join(x for x in (f"{len(reds)} крит." if reds else "", f"{len(ambers)} вним." if ambers else "") if x)
        self.title.config(text=f"MP Control · {summary} · {data['generated'][-5:]}")
        self.set_head(data["level"])
        for g in data["groups"]:
            row = tk.Frame(self.body, bg=BG, cursor="hand2")
            row.pack(fill="x", padx=10, pady=(7, 0))
            top = tk.Frame(row, bg=BG)
            top.pack(fill="x")
            dot = tk.Canvas(top, width=10, height=10, bg=BG, highlightthickness=0)
            dot.create_oval(1, 1, 9, 9, fill=COL[g["level"]], outline="")
            dot.pack(side="left", pady=(4, 0))
            t = tk.Label(top, text=g["title"], fg=INK, bg=BG, font=(FONT, 9, "bold"), padx=6)
            t.pack(side="left")
            ln = tk.Label(top, text=g["line"], fg=COL[g["level"]] if g["level"] in ("red", "amber") else MUTED,
                          bg=BG, font=(FONT, 9), anchor="w", justify="left", wraplength=230)
            ln.pack(side="left", fill="x")
            ws = [row, top, dot, t, ln]
            for d in g.get("details") or []:
                l = tk.Label(row, text=d, fg=MUTED, bg=BG, font=(FONT, 8), anchor="w", justify="left",
                             wraplength=320, padx=16)
                l.pack(fill="x")
                ws.append(l)
            for w in ws:
                w.bind("<Button-1>", lambda e, link=g.get("link", ""): threading.Thread(
                    target=open_dashboard, args=(link,), daemon=True).start())
                w.bind("<Button-3>", self.popup)
        tk.Label(self.body, text="Нажмите на строку — откроется раздел дашборда", fg="#a3a29b", bg=BG,
                 font=(FONT, 7), padx=10, pady=6).pack(anchor="w")
        # новый красный сигнал — мигнуть и развернуться
        now_red = {g["key"] for g in reds}
        if now_red - self.prev_red:
            if self.collapsed:
                self.toggle()
            self.root.lift()
            self.flash()
        self.prev_red = now_red


if __name__ == "__main__":
    lock = single_instance()
    if lock is None:
        sys.exit(0)   # виджет уже запущен
    Widget().root.mainloop()
