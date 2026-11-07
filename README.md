# Mocheqi — дашборд WB + Ozon

Аналитика магазинов Mocheqi (Wildberries) и Mocheqi_Ozon: сводный и месячный отчёты, ДДС, ОПиУ,
себестоимость, план поставок, поставки и их статусы, контроль цен (МРЦ), виджет поверх окон.

Python 3 (стандартная библиотека + openpyxl), SQLite, веб-интерфейс на чистом JS + Chart.js.

## Что НЕ хранится в репозитории
- `config.ini` — ключи API WB и Ozon (образец — `config.example.ini`);
- `data/` — база `mp.sqlite` (история, пользователи и пароли, отметки), логи, выгрузки API;
- `app/costs_seed.json` — себестоимость.

## Запуск на Windows
`start.bat` — сервер на http://127.0.0.1:8765, `install_schedule.bat` — задачи Windows (ночная загрузка,
цены и поставки в 10/14/18, заказы каждые 30 минут), `widget.bat` — виджет.

## Структура
- `app/server.py` — HTTP-сервер и API; `app/collector.py` — загрузка данных из API (режимы `--full`, `--prices`,
  `--today`, `--supplies`, `--ozon-wh`, `--wb-wh`, `--gsheet`);
- `app/static/` — интерфейс; `help_build/content.js` — текст «Инструкций» (собирается в `app/static/help.html` и Word).
