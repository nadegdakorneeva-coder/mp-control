# -*- coding: utf-8 -*-
"""Сборщик данных WB и Ozon в локальную базу.
Запуск: python collector.py [--full]
  без флага — догружает последние дни (быстро, для ежедневного запуска);
  --full    — перезагружает всю доступную историю."""
import datetime as dt, json, os, sys, time, urllib.request, urllib.error
import db

LOG_PATH = os.path.join(db.DATA_DIR, "collector_log.txt")
FULL = "--full" in sys.argv
TODAY = dt.date.today()
con = db.init()
cfg = db.config()
_log = None


def log(msg):
    global _log
    if _log is None:
        _log = open(LOG_PATH, "a", encoding="utf-8")
        _log.write("\n")
    line = f"{dt.datetime.now():%d.%m %H:%M:%S} {msg}"
    print(line)
    _log.write(line + "\n"); _log.flush()


def status(msg):
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_status', ?)", (msg,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_heartbeat', ?)", (str(time.time()),))
    con.commit()
    log(msg)


def running(flag):
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_running', ?)", ("1" if flag else "0",))
    con.execute("INSERT OR REPLACE INTO meta VALUES('update_heartbeat', ?)", (str(time.time()),))
    con.commit()


def meta_get(k, default=None):
    r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(k, v):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))
    con.commit()


class ApiError(Exception):
    pass


def http(method, url, headers, body=None, tries=5, timeout=120, wait429=65):
    """Запрос с повторами: таймауты, обрывы, 429 и 5xx повторяются с паузой."""
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.status == 204 or not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            txt = e.read()[:500].decode("utf-8", "replace")
            last = f"HTTP {e.code}: {txt}"
            if e.code == 204:
                return None
            if e.code == 429:
                status(f"Лимит запросов API, жду {wait429} с…")
                time.sleep(wait429)
                continue
            if e.code >= 500:
                time.sleep(10 * attempt)
                continue
            raise ApiError(last)
        except Exception as e:
            last = str(e)
            log(f"  сеть: {last}; повтор {attempt}/{tries}")
            time.sleep(10 * attempt)
    raise ApiError(last or "нет ответа")


# ============================ Wildberries ============================
WB_TOKEN = cfg.get("wb", "token", fallback="").strip()
WBH = {"Authorization": WB_TOKEN}
WB_SCHEME = {"Склад продавца": "FBS"}


def wb_product(nm, art, subject=None, brand=None, barcode=None, name=None):
    con.execute("""INSERT INTO products(mp, mp_sku, article, name, brand, category, barcode) VALUES('wb',?,?,?,?,?,?)
                   ON CONFLICT(mp, mp_sku) DO UPDATE SET article=COALESCE(excluded.article, article),
                   name=COALESCE(excluded.name, name), brand=COALESCE(excluded.brand, brand),
                   category=COALESCE(excluded.category, category), barcode=COALESCE(excluded.barcode, barcode)""",
                (str(nm), art, name, brand, subject, barcode))


def wb_orders():
    since = (TODAY - dt.timedelta(days=89 if FULL else 14)).isoformat()
    date_from = since if FULL else (meta_get("wb_orders_cursor") or since)
    total = 0
    while True:
        rows = http("GET", f"https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom={date_from}", WBH) or []
        for r in rows:
            scheme = WB_SCHEME.get(r.get("warehouseType"), "FBO")
            con.execute("""INSERT OR REPLACE INTO orders(mp, order_key, dt, ts, article, mp_sku, scheme, qty, price, paid,
                           warehouse, region, is_cancel, status) VALUES('wb',?,?,?,?,?,?,1,?,?,?,?,?,?)""",
                        (r["srid"], r["date"][:10], r["date"], r.get("supplierArticle"), str(r.get("nmId")), scheme,
                         r.get("priceWithDisc") or 0, r.get("finishedPrice") or 0, r.get("warehouseName"),
                         r.get("oblastOkrugName") or r.get("regionName"), 1 if r.get("isCancel") else 0,
                         "Отмена" if r.get("isCancel") else ""))
            wb_product(r.get("nmId"), r.get("supplierArticle"), r.get("subject"), r.get("brand"), r.get("barcode"))
        con.commit()
        total += len(rows)
        if len(rows) < 80000:
            if rows:
                meta_set("wb_orders_cursor", rows[-1]["lastChangeDate"])
            break
        date_from = rows[-1]["lastChangeDate"]
        time.sleep(61)
    log(f"WB заказы: {total} строк")


def f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def wb_articles():
    return {r[0]: r[1] for r in con.execute("SELECT mp_sku, article FROM products WHERE mp='wb' AND article IS NOT NULL")}


def put_fin(mp, key, metric, day, article, sku, scheme, amount, qty=0, source=""):
    if not amount and not qty:
        return
    con.execute("""INSERT INTO fin(mp, line_key, metric, dt, article, mp_sku, scheme, amount, qty, source)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(mp, line_key, metric) DO UPDATE SET amount=amount+excluded.amount, qty=qty+excluded.qty""",
                (mp, key, metric, day, article, sku, scheme, amount, qty, source))


SALE_OPS = {"Продажа", "Возврат", "Корректная продажа", "Корректный возврат", "Сторно продаж", "Сторно возвратов"}


def wb_fin_row(r, source, arts):
    key = str(r.get("rrdId"))
    con.execute("DELETE FROM fin WHERE mp='wb' AND line_key=?", (key,))
    day = (r.get("rrDate") or r.get("saleDt") or "")[:10]
    nm = str(r.get("nmId") or "")
    art = arts.get(nm) or r.get("vendorCode") or ""
    method = (r.get("deliveryMethod") or "") + " " + (r.get("officeName") or "")
    scheme = "FBS" if ("FBS" in method or "Склад поставщика" in method) else "FBO"
    doc = r.get("docTypeName") or ""
    op = r.get("sellerOperName") or ""
    sign = -1 if doc.startswith("Возврат") or op in ("Возврат", "Сторно продаж") else 1
    q = f(r.get("quantity"))
    P = lambda metric, amount, qty=0: put_fin("wb", key, metric, day, art, nm, scheme, amount, qty, source)
    if op in SALE_OPS and q:
        real = f(r.get("retailPriceWithDisc")) * q
        P("realization", sign * real, sign * q)
        P("sales", sign * f(r.get("retailAmount")))
        P("acquiring", sign * f(r.get("acquiringFee")))
        P("commission", sign * (real - f(r.get("forPay")) - f(r.get("acquiringFee"))))
        P("for_pay", sign * f(r.get("forPay")))
        if sign < 0:
            P("returns", real, q)
    else:
        fp = f(r.get("forPay"))
        if fp:
            P("compensation", sign * fp)
            P("for_pay", sign * fp)
    P("logistics", f(r.get("deliveryService")) + f(r.get("rebillLogisticCost")))
    P("penalty", f(r.get("penalty")))
    P("storage", f(r.get("paidStorage")))
    P("acceptance", f(r.get("paidAcceptance")))
    P("other", f(r.get("deduction")))
    P("compensation", f(r.get("additionalPayment")))
    bonus = (r.get("bonusTypeName") or "").lower()
    if r.get("returnAmount") and ("отмен" in bonus or "невыкуп" in bonus or "отказ" in bonus):
        P("refusal", 0, f(r.get("returnAmount")))


WB_FIELDS = ["rrdId", "nmId", "vendorCode", "docTypeName", "sellerOperName", "bonusTypeName", "quantity",
             "retailPriceWithDisc", "retailAmount", "forPay", "acquiringFee", "deliveryService", "rebillLogisticCost",
             "penalty", "paidStorage", "paidAcceptance", "deduction", "additionalPayment", "returnAmount", "rrDate",
             "saleDt", "deliveryMethod", "officeName", "dateTo", "reportId"]


def wb_finance_period(date_from, date_to, period, source):
    """Детализация отчётов реализации за период. Возвращает (строк, макс. dateTo отчёта)."""
    rrd, total, max_to = 0, 0, None
    arts = wb_articles()
    first = True
    while True:
        if not first:
            time.sleep(61)
        first = False
        rows = http("POST", "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed", WBH,
                    {"dateFrom": date_from, "dateTo": date_to, "period": period, "limit": 50000, "rrdId": rrd,
                     "fields": WB_FIELDS},
                    timeout=300) or []
        for r in rows:
            wb_fin_row(r, source, arts)
            max_to = max(max_to or "", r.get("dateTo") or "")
        con.commit()
        total += len(rows)
        status(f"WB финотчёты: загружено {total} строк…")
        if len(rows) < 50000:
            break
        rrd = rows[-1]["rrdId"]
    return total, max_to


def wb_finance():
    start = "2026-01-01" if FULL else (meta_get("wb_weekly_to") and
                                       (dt.date.fromisoformat(meta_get("wb_weekly_to")) - dt.timedelta(days=21)).isoformat()) or "2026-01-01"
    n, wk_to = wb_finance_period(start, TODAY.isoformat(), "weekly", "wbw")
    if wk_to:
        meta_set("wb_weekly_to", wk_to)
        # дневные строки, перекрытые недельными отчётами, больше не нужны
        con.execute("DELETE FROM fin WHERE mp='wb' AND source='wbd' AND dt <= ?", (wk_to,))
        con.commit()
    log(f"WB финотчёты (недельные): {n} строк, по {wk_to}")
    wk_to = meta_get("wb_weekly_to") or start
    d_from = (dt.date.fromisoformat(wk_to) + dt.timedelta(days=1)).isoformat()
    if d_from <= TODAY.isoformat():
        time.sleep(61)
        n, _ = wb_finance_period(d_from, TODAY.isoformat(), "daily", "wbd")
        log(f"WB финотчёты (ежедневные) с {d_from}: {n} строк")


def wb_stocks():
    items, offset = [], 0
    while True:
        res = http("POST", "https://seller-analytics-api.wildberries.ru/api/analytics/v1/stocks-report/wb-warehouses", WBH,
                   {"limit": 250000, "offset": offset}, wait429=21) or {}
        chunk = (res.get("data") or {}).get("items") or []
        items += chunk
        if len(chunk) < 250000:
            break
        offset += len(chunk)
        time.sleep(21)
    arts = wb_articles()
    snap = TODAY.isoformat()
    con.execute("DELETE FROM stocks WHERE snap_date=? AND mp='wb'", (snap,))
    agg = {}
    for it in items:
        k = (str(it["nmId"]), it.get("warehouseName") or "Склад WB")
        a = agg.setdefault(k, [0, 0, 0])
        a[0] += it.get("quantity") or 0
        a[1] += it.get("inWayToClient") or 0
        a[2] += it.get("inWayFromClient") or 0
    for (nm, wh), (q, tc, fc) in agg.items():
        con.execute("INSERT OR REPLACE INTO stocks VALUES(?,?,?,?,?,?,?,?,?)",
                    (snap, "wb", nm, arts.get(nm), wh, "FBO", q, tc, fc))
    con.commit()
    log(f"WB остатки: {len(agg)} позиций")


# ============================ Ozon ============================
OZ_ID = cfg.get("ozon", "client_id", fallback="").strip()
OZ_KEY = cfg.get("ozon", "api_key", fallback="").strip()
OZH = {"Client-Id": OZ_ID, "Api-Key": OZ_KEY}
OZ = "https://api-seller.ozon.ru"


def oz(path, body, **kw):
    time.sleep(0.25)   # Ozon ограничивает число запросов в секунду
    return http("POST", OZ + path, OZH, body, wait429=3, **kw)


OZ_TYPE_METRIC = {}
def oz_type_map():
    names = {}
    try:
        res = oz("/v1/finance/accrual/types", {}) or {}
        names = {t["id"]: t["name"] for t in res.get("accrual_types", [])}
    except ApiError as e:
        log(f"Ozon: справочник типов начислений недоступен ({e})")
    def metric(name):
        n = name or ""
        if n == "Acquiring": return "acquiring"
        if n == "SaleCommission": return "commission"
        if n.startswith("DefectFine") or n == "DefectRate": return "penalty"
        if n in ("Placements", "ReturnStorageInTheWarehouse", "TemporaryPlacement", "TemporaryPlacementsAgent", "B2CTemporaryPlacement"):
            return "storage"
        if n in ("SupplyInbound", "MicroFulfillmentSupply"): return "acceptance"
        if n in ("Compensation", "ItemCompensation", "ClaimCommission", "B2CInsuranceCompensation", "VolumeObligationReward",
                 "RealizationReportCorrection", "CorrectionCommission", "AnalyticsCorrection"):
            return "compensation"
        ads = ("Brand", "ExternalPromotion", "InternetSiteAdvertising", "Marketing", "PayPerClick", "PointsForReviews",
               "PremiumCashback", "PremiumMailing", "Promotion", "PushCampaign", "SaleReview", "SocialMediaAdvertising",
               "Stencil", "StarsMembership", "VideoCover", "DisplayAdvertising", "AcceleratedReviewCollection",
               "FirstCustomerReview", "CustomerChatPoints", "ReviewsPin", "OrdersBooking")
        if n.startswith(ads) and n != "BrandDeposit": return "ads"
        logi = ("Logistic", "LastMile", "Shipment", "BackwardShipment", "ReturnFlowLogistic", "Drop-Off", "Pick-Up", "PickUp",
                "DeliveryToHandoverPlaceByOzon", "ClientReturn", "Cancellation", "PartialReturn", "Replenishment",
                "B2CLogistics", "B2CBackwardLogistics", "B2C Drop-Off", "B2CCourierClientReinvoice", "B2CDeliveryToHandoverPlaceByOzon",
                "B2CPickUpPoint", "CourierPickUp", "QuantProcessingDrop", "PackageUnitProcessing", "PreparingToReturn",
                "RfbsDomesticDelivery", "InternationalLogisticDelta", "OzonGlobalLogisticsDelivery", "OversizedExtraHandling")
        if n.startswith(logi): return "logistics"
        return "other"
    for i, n in names.items():
        OZ_TYPE_METRIC[i] = metric(n)
    if not OZ_TYPE_METRIC:      # запасной вариант по известным номерам
        OZ_TYPE_METRIC.update({1: "acquiring", 69: "commission", 32: "logistics", 29: "logistics", 30: "logistics", 28: "logistics"})


def oz_products():
    last, n = "", 0
    while True:
        res = (oz("/v3/product/list", {"filter": {"visibility": "ALL"}, "last_id": last, "limit": 1000}) or {}).get("result") or {}
        items = res.get("items") or []
        for it in items:
            if it.get("sku"):
                con.execute("""INSERT INTO products(mp, mp_sku, article) VALUES('ozon',?,?)
                               ON CONFLICT(mp, mp_sku) DO UPDATE SET article=excluded.article""", (str(it["sku"]), it.get("offer_id")))
                n += 1
        last = res.get("last_id") or ""
        if not items or not last or len(items) < 1000:
            break
    con.commit()
    log(f"Ozon товары: {n}")


def oz_articles():
    return {r[0]: r[1] for r in con.execute("SELECT mp_sku, article FROM products WHERE mp='ozon'")}


def amt(x):
    return f((x or {}).get("amount")) if isinstance(x, dict) else f(x)


def oz_accrual(a, arts):
    aid = str(a.get("accrual_id") or f"{a.get('unit_number')}:{a.get('date')}:{amt(a.get('total_amount'))}")
    con.execute("DELETE FROM fin WHERE mp='ozon' AND line_key LIKE ?", (aid + "%",))
    day = (a.get("date") or "")[:10]
    cat = a.get("accrued_category")
    P = lambda k, metric, sku, scheme, amount, qty=0: put_fin("ozon", f"{aid}:{k}", metric, day, arts.get(str(sku or "")) or "",
                                                                str(sku or ""), scheme, amount, qty, "oz")
    first_sku, scheme = None, "FBO"
    if cat == "POSTING" and a.get("posting"):
        ps = a["posting"]
        scheme = "FBS" if "fbs" in (ps.get("delivery_schema") or "").lower() else "FBO"
        for i, p in enumerate(ps.get("products") or []):
            sku, q = p.get("sku"), f(p.get("quantity")) or 1
            first_sku = first_sku or sku
            c = p.get("commission")
            if c:
                seller = amt(c.get("seller_price")) or amt(c.get("sale_amount"))
                sale = amt(c.get("sale_price")) + amt(c.get("coinvestment"))   # как в TrueStats: с соинвестом банка
                com = amt(c.get("sale_commission")) or amt(c.get("commission"))
                sign = -1 if (com > 0 or seller < 0) else 1
                P(i, "realization", sku, scheme, sign * abs(seller), sign * q)
                P(i, "sales", sku, scheme, sign * abs(sale))
                P(i, "commission", sku, scheme, -com)
                if sign < 0:
                    P(i, "returns", sku, scheme, abs(seller), q)
            for s in ((p.get("delivery") or {}).get("services") or []):
                m = OZ_TYPE_METRIC.get(s.get("type_id"), "logistics")
                v = amt(s.get("accrued"))
                P(i, m, sku, scheme, v if m == "compensation" else -v)
    elif cat == "ITEM" and a.get("item_fees"):
        for i, g in enumerate(a["item_fees"].get("fees") or []):
            sku = g.get("sku"); first_sku = first_sku or sku
            for j, fee in enumerate(g.get("fees") or []):
                m = OZ_TYPE_METRIC.get(fee.get("type_id"), "other")
                v = amt(fee.get("accrued"))
                P(f"{i}.{j}", m, sku, scheme, v if m == "compensation" else -v)
    elif a.get("non_item_fee"):
        fee = a["non_item_fee"]
        m = OZ_TYPE_METRIC.get(fee.get("type_id"), "other")
        v = amt(fee.get("accrued"))
        P("n", m, None, scheme, v if m == "compensation" else -v)
    else:
        v = amt(a.get("total_amount"))
        P("c", "other" if v < 0 else "compensation", None, scheme, -v if v < 0 else v)
    P("t", "for_pay", first_sku, scheme, amt(a.get("total_amount")))


def oz_finance():
    oz_type_map()
    last_done = meta_get("oz_accrual_to")
    start = dt.date(2026, 1, 1) if FULL or not last_done else dt.date.fromisoformat(last_done) - dt.timedelta(days=10)
    arts = oz_articles()
    day, total = start, 0
    while day <= TODAY:
        last, pages = "", 0
        while True:
            body = {"date": day.isoformat()}
            if last:
                body["last_id"] = last
            res = oz("/v1/finance/accrual/by-day", body) or {}
            res = res.get("result", res) if isinstance(res, dict) else {}
            for a in res.get("accruals") or []:
                oz_accrual(a, arts); total += 1
            last = res.get("last_id") or ""
            pages += 1
            if not last or not res.get("accruals") or pages > 500:
                break
        con.commit()
        if day < TODAY:
            meta_set("oz_accrual_to", day.isoformat())
        if day.day == 1 or day == TODAY:
            status(f"Ozon: начисления загружены по {day:%d.%m.%Y}")
        day += dt.timedelta(days=1)
    log(f"Ozon начисления: {total} записей")


def oz_stocks():
    cursor, rows = "", []
    while True:
        res = oz("/v4/product/info/stocks", {"filter": {"visibility": "ALL"}, "cursor": cursor, "limit": 1000}) or {}
        items = res.get("items") or []
        rows += items
        cursor = res.get("cursor") or ""
        if not items or not cursor or len(items) < 1000:
            break
    snap = TODAY.isoformat()
    con.execute("DELETE FROM stocks WHERE snap_date=? AND mp='ozon'", (snap,))
    n = 0
    for it in rows:
        for s in it.get("stocks") or []:
            sku = str(s.get("sku") or "")
            if not sku:
                continue
            con.execute("""INSERT INTO stocks VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(snap_date, mp, mp_sku, warehouse)
                           DO UPDATE SET qty=qty+excluded.qty""",
                        (snap, "ozon", sku, it.get("offer_id"), "Ozon " + (s.get("type") or "").upper(),
                         (s.get("type") or "fbo").upper(), f(s.get("present")), f(s.get("reserved")), 0))
            n += 1
    con.commit()
    log(f"Ozon остатки: {n} позиций")


def msk(ts):
    """Время Ozon приходит в UTC — переводим в московское."""
    try:
        t = dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        return (t + dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ts


def oz_postings_kind(path, scheme, since, to):
    """Заказы Ozon. Методы списков отправлений недавно сменились, поэтому разбор терпимый к разным форматам."""
    cursor, n, first = "", 0, True
    while True:
        body = {"filter": {"since": since + "T00:00:00Z", "to": to + "T23:59:59Z"}, "limit": 100, "cursor": cursor,
                "with": {"analytics_data": True, "financial_data": True}}
        res = oz(path, body) or {}
        if first:
            os.makedirs(os.path.join(db.DATA_DIR, "raw"), exist_ok=True)
            json.dump(res, open(os.path.join(db.DATA_DIR, "raw", f"oz_{scheme}_postings_sample.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            first = False
        r = res.get("result", res) if isinstance(res, dict) else {}
        posts = r.get("postings") if isinstance(r, dict) else r
        posts = posts or []
        for p in posts:
            ts = msk(p.get("in_process_at") or p.get("created_at") or "")
            fin_by_sku = {}
            for fp in ((p.get("financial_data") or {}).get("products") or []):
                fin_by_sku[str(fp.get("product_id") or fp.get("sku") or "")] = fp
            cancel = 1 if (p.get("status") or "").lower() in ("cancelled", "canceled") else 0
            for i, pr in enumerate(p.get("products") or []):
                sku = str(pr.get("sku") or "")
                q = f(pr.get("quantity")) or 1
                price = amt(pr.get("price"))
                fp = fin_by_sku.get(sku) or {}
                paid = amt(fp.get("customer_price")) or amt(pr.get("customer_price")) or price
                region = (p.get("analytics_data") or {}).get("region")
                wh = (p.get("analytics_data") or {}).get("warehouse_name") or (p.get("analytics_data") or {}).get("warehouse")
                fd = p.get("financial_data") or {}
                con.execute("""INSERT OR REPLACE INTO orders(mp, order_key, dt, ts, article, mp_sku, scheme, qty, price, paid,
                               warehouse, region, is_cancel, status, cluster_from, cluster_to, city)
                               VALUES('ozon',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (f"{p.get('posting_number')}:{sku}:{i}", ts[:10], ts, pr.get("offer_id"), sku, scheme, q,
                             price, paid, wh, region or fd.get("cluster_to"), cancel, p.get("status"),
                             fd.get("cluster_from"), fd.get("cluster_to"), (p.get("analytics_data") or {}).get("city")))
                n += 1
        con.commit()
        cursor = (r.get("cursor") if isinstance(r, dict) else "") or ""
        has_next = r.get("has_next") if isinstance(r, dict) else False
        if not posts or not (has_next or cursor) or (has_next is False):
            break
    return n


def oz_orders(days=None):
    since = (TODAY - dt.timedelta(days=days or (89 if FULL else 14))).isoformat()
    for path, scheme in (("/v3/posting/fbo/list", "FBO"), ("/v4/posting/fbs/list", "FBS")):
        try:
            # длинные периоды режем по месяцу
            a, n = dt.date.fromisoformat(since), 0
            while a <= TODAY:
                b = min(a + dt.timedelta(days=29), TODAY)
                n += oz_postings_kind(path, scheme, a.isoformat(), b.isoformat())
                a = b + dt.timedelta(days=1)
            log(f"Ozon заказы {scheme}: {n} строк")
        except ApiError as e:
            log(f"Ozon заказы {scheme}: ошибка {e}")


def _walk(o, fn):
    if isinstance(o, dict):
        fn(o)
        for v in o.values():
            _walk(v, fn)
    elif isinstance(o, list):
        for v in o:
            _walk(v, fn)


def oz_clusters():
    """Склад → кластер. Сначала официальный справочник кластеров, затем — по заказам (склад отгрузки → cluster_from)."""
    found = {}
    # 1) по заказам: склад отгрузки → кластер отгрузки (те же названия, что у кластера доставки)
    for r in con.execute("""SELECT warehouse, cluster_from, COUNT(*) n FROM orders WHERE mp='ozon' AND warehouse IS NOT NULL
                            AND cluster_from IS NOT NULL GROUP BY 1, 2 ORDER BY n"""):
        found[r["warehouse"]] = r["cluster_from"]
    # 2) официальный справочник — для складов без заказов
    try:
        res = oz("/v1/cluster/list", {"cluster_type": "CLUSTER_TYPE_OZON"}) or {}
        os.makedirs(os.path.join(db.DATA_DIR, "raw"), exist_ok=True)
        json.dump(res, open(os.path.join(db.DATA_DIR, "raw", "oz_clusters_sample.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        def on_cluster(d):
            if "name" in d and any(k in d for k in ("logistic_clusters", "warehouses")):
                cname = d["name"]
                def on_wh(w):
                    if w is not d and w.get("name") and ("warehouse_id" in w or "id" in w) and "logistic_clusters" not in w:
                        found.setdefault(w["name"], cname)
                _walk(d.get("logistic_clusters") or d.get("warehouses"), on_wh)
        _walk(res, on_cluster)
    except ApiError as e:
        log(f"Ozon кластеры: справочник недоступен ({e}), беру из заказов")
    # 3) остальные склады — по названию (город в начале названия склада)
    known = set(found.values()) | {r[0] for r in con.execute("SELECT DISTINCT cluster_to FROM orders WHERE mp='ozon' AND cluster_to IS NOT NULL")}
    moscow = next((c for c in known if c.startswith("Москва")), "Москва, МО и Дальние регионы")
    spb = next((c for c in known if c.startswith("Санкт-Петербург")), "Санкт-Петербург и СЗО")
    MO = ("ВАТУТИНКИ", "ДОМОДЕДОВО", "ГРИВНО", "ЖУКОВСКИЙ", "ПЕТРОВСКОЕ", "ПУШКИНО", "ХОРУГВИНО", "НОГИНСК", "СОФЬИНО",
          "ЭЛЕКТРОСТАЛЬ", "ПОДОЛЬСК", "КОЛЕДИНО", "ЧЕХОВ", "БЕЛЫЕ_СТОЛБЫ", "ВНУКОВО", "МОСКВА", "ЛОБНЯ", "ХИМКИ")
    def guess(wh):
        w = wh.upper().replace("-", "_")
        if w.startswith(MO):
            return moscow
        if w.startswith(("СПБ", "САНКТ_ПЕТЕРБУРГ", "ШУШАРЫ")):
            return spb
        wn = w.replace("_", " ")
        for c in sorted(known, key=len, reverse=True):
            first = c.split(",")[0].split(" и ")[0].upper().replace("-", " ").strip()
            if first and wn.startswith(first):
                return c
        return None
    for r in con.execute("SELECT DISTINCT warehouse FROM wh_stocks WHERE mp='ozon'"):
        wh = r[0]
        if wh and wh not in found:
            g = guess(wh)
            if g:
                found[wh] = g
    for wh, cl in found.items():
        con.execute("INSERT OR REPLACE INTO wh_cluster VALUES('ozon',?,?)", (wh, cl))
    con.commit()
    log(f"Ozon кластеры: {len(found)} складов сопоставлено")
    return found


def oz_wh_stocks():
    rows, offset = [], 0
    while True:
        res = (oz("/v2/analytics/stock_on_warehouses", {"limit": 1000, "offset": offset, "warehouse_type": "ALL"}) or {}).get("result") or {}
        chunk = res.get("rows") or []
        rows += chunk
        if len(chunk) < 1000:
            break
        offset += 1000
    snap = TODAY.isoformat()
    con.execute("DELETE FROM wh_stocks WHERE snap_date=? AND mp='ozon'", (snap,))
    clusters = {}
    for r in rows:
        wh = r.get("warehouse_name") or "?"
        con.execute("""INSERT INTO wh_stocks VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(snap_date, mp, mp_sku, warehouse)
                       DO UPDATE SET free=free+excluded.free, promised=promised+excluded.promised, reserved=reserved+excluded.reserved""",
                    (snap, "ozon", str(r.get("sku")), r.get("item_code"), r.get("item_name"), wh, clusters.get(wh),
                     f(r.get("free_to_sell_amount")), f(r.get("promised_amount")), f(r.get("reserved_amount"))))
        if r.get("item_name"):
            con.execute("UPDATE products SET name=COALESCE(name, ?) WHERE mp='ozon' AND mp_sku=?", (r["item_name"], str(r.get("sku"))))
    con.commit()
    for wh, cl in oz_clusters().items():
        con.execute("UPDATE wh_stocks SET cluster=? WHERE mp='ozon' AND snap_date=? AND warehouse=?", (cl, snap, wh))
    con.commit()
    meta_set("oz_wh_snapshot", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    log(f"Ozon остатки по складам: {len(rows)} строк")


# ============================ запуск ============================
def step(name, fn):
    try:
        status(f"Загрузка: {name}…")
        fn()
        return True
    except Exception as e:
        import traceback
        log(f"ОШИБКА на шаге «{name}»: {e}\n{traceback.format_exc()}")
        return False


# ============================ История заказов ============================
# WB отдаёт заказы через API статистики только за последние ~90 дней, Ozon — за любой период.
# Чтобы график и отчёты показывали заказы с начала года:
#   Ozon — догружаем сами отправления (настоящие заказы) от начала финансовых данных;
#   WB  — берём помесячные итоги заказов по карточкам из аналитики («Воронка продаж», nm-report)
#         за период до первого дня, по которому есть обычные заказы, и кладём в orders_hist.
HIST_VERSION = "2"


def _hist_start():
    r = con.execute("SELECT MIN(dt) FROM fin").fetchone()[0]
    return max(r or "2026-01-01", (TODAY - dt.timedelta(days=364)).isoformat())


def oz_orders_history():
    start = _hist_start()
    first = con.execute("SELECT MIN(dt) FROM orders WHERE mp='ozon'").fetchone()[0] or TODAY.isoformat()
    if start >= first:
        log("Ozon история заказов: догружать нечего")
        return
    end = (dt.date.fromisoformat(first) - dt.timedelta(days=1)).isoformat()
    for path, scheme in (("/v3/posting/fbo/list", "FBO"), ("/v4/posting/fbs/list", "FBS")):
        a, n = dt.date.fromisoformat(start), 0
        while a.isoformat() <= end:
            b = min(a + dt.timedelta(days=29), dt.date.fromisoformat(end))
            status(f"Загрузка: история заказов Ozon {scheme} {a:%d.%m}–{b:%d.%m}…")
            n += oz_postings_kind(path, scheme, a.isoformat(), b.isoformat())
            a = b + dt.timedelta(days=1)
        log(f"Ozon история заказов {scheme} {start}…{end}: {n} строк")


def wb_orders_history():
    con.execute("""CREATE TABLE IF NOT EXISTS orders_hist(mp TEXT NOT NULL, d_from TEXT NOT NULL, d_to TEXT NOT NULL,
                   article TEXT, mp_sku TEXT NOT NULL, qty REAL, sum REAL, src TEXT, PRIMARY KEY(mp, d_from, mp_sku))""")
    start = _hist_start()
    first = con.execute("SELECT MIN(dt) FROM orders WHERE mp='wb'").fetchone()[0] or TODAY.isoformat()
    if start >= first:
        log("WB история заказов: догружать нечего")
        return
    arts = {r[0]: r[1] for r in con.execute("SELECT mp_sku, article FROM products WHERE mp='wb'")}
    end = dt.date.fromisoformat(first) - dt.timedelta(days=1)
    a, total = dt.date.fromisoformat(start), 0
    while a <= end:
        nxt = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        b = min(nxt - dt.timedelta(days=1), end)
        status(f"Загрузка: история заказов WB {a:%m.%Y}…")
        off, rows = 0, 0
        while True:
            # «Воронка продаж» v3 (v2 nm-report WB отключил): итоги по карточкам за период до 365 дней, 3 запроса/мин
            body = {"selectedPeriod": {"start": a.isoformat(), "end": b.isoformat()}, "nmIds": [], "brandNames": [],
                    "subjectIds": [], "tagIds": [], "skipDeletedNm": False,
                    "orderBy": {"field": "orderSum", "mode": "desc"}, "limit": 100, "offset": off}
            res = http("POST", "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products", WBH, body, wait429=25) or {}
            if off == 0 and a.isoformat() == start:
                os.makedirs(os.path.join(db.DATA_DIR, "raw"), exist_ok=True)
                json.dump(res, open(os.path.join(db.DATA_DIR, "raw", "wb_sales_funnel_sample.json"), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
            data = res.get("data", res) if isinstance(res, dict) else {}
            prods = (data.get("products") if isinstance(data, dict) else None) or []
            for it in prods:
                pr = it.get("product") or {}
                stt = it.get("statistic") or it.get("statistics") or {}
                sel = stt.get("selected") or stt.get("selectedPeriod") or it.get("currentPeriod") or {}
                q, sm = f(sel.get("orderCount") or sel.get("ordersCount")), f(sel.get("orderSum") or sel.get("ordersSumRub"))
                if not q and not sm:
                    continue
                nm = str(pr.get("nmId") or pr.get("nmID") or it.get("nmId") or "")
                if not nm:
                    continue
                con.execute("INSERT OR REPLACE INTO orders_hist VALUES('wb',?,?,?,?,?,?,'sales-funnel-v3')",
                            (a.isoformat(), b.isoformat(), arts.get(nm) or pr.get("vendorCode"), nm, q, sm))
                rows += 1
            con.commit()
            time.sleep(21)          # лимит аналитики — 3 запроса в минуту
            if len(prods) < 100:
                break
            off += 100
        log(f"WB история заказов {a}…{b}: {rows} карточек")
        total += rows
        a = b + dt.timedelta(days=1)
    log(f"WB история заказов: всего {total} строк")
    if not total:   # ответ пришёл, но не разобрался — не ставим отметку «готово», образец ответа в data\raw
        raise ApiError("WB история заказов: 0 строк — см. data/raw/wb_sales_funnel_sample.json")


def orders_history():
    if meta_get("orders_hist_version") == HIST_VERSION:
        return
    ok = True
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon история заказов", oz_orders_history)
    if WB_TOKEN:
        ok &= step("WB история заказов", wb_orders_history)
    if ok:
        meta_set("orders_hist_version", HIST_VERSION)


# ============================ Поставки ============================
SUP_DAYS = 180          # завершённые поставки — за полгода; незавершённые — все


def _raw(name, obj):
    try:
        os.makedirs(os.path.join(db.DATA_DIR, "raw"), exist_ok=True)
        json.dump(obj, open(os.path.join(db.DATA_DIR, "raw", name), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    except Exception:
        pass


def _no_access(e):
    s = str(e)
    return any(f"HTTP {c}" in s for c in (401, 403, 404))


def _d(x):
    """'2026-10-20T08:00:00Z' / '2026-10-20T11:00:00+03:00' → '2026-10-20 11:00' (Москва)."""
    if not x:
        return None
    s = str(x)
    if s.startswith("0001"):
        return None
    if s.endswith("Z") or "+00:00" in s:
        s = msk(s)
    return s[:16].replace("T", " ")


def wb_supplies():
    """Поставки FBW: список за полгода + детали (склад, сколько отправлено и принято). Нужна категория «Поставки» в токене."""
    import supplies as SP
    base = "https://supplies-api.wildberries.ru/api/v1"
    body = {"dates": [{"from": (TODAY - dt.timedelta(days=SUP_DAYS)).isoformat(), "till": TODAY.isoformat(), "type": "createDate"}]}
    lst, off = [], 0
    while True:
        try:
            res = http("POST", f"{base}/supplies?limit=1000&offset={off}", WBH, body, wait429=20)
        except ApiError as e:
            if _no_access(e):
                meta_set("wb_supplies_access", f"нет доступа: {str(e)[:160]}")
                log(f"WB поставки: нет доступа ({e}). Нужна категория «Поставки» в токене WB.")
                return
            raise
        rows = res if isinstance(res, list) else ((res or {}).get("data") or [])
        if off == 0:
            _raw("wb_supplies_list_sample.json", (rows or [])[:20])
        lst += rows
        if len(rows) < 1000:
            break
        off += 1000
        time.sleep(2.1)
    meta_set("wb_supplies_access", "ok")
    old = SP.known(con, "wb")
    n_det = 0
    for r in lst:
        sid, pre = r.get("supplyID"), r.get("preorderID")
        key = str(sid) if sid else f"pre{pre}"
        if not sid and not pre:
            continue
        st = r.get("statusID")
        stage = SP.STAGE_WB.get(st, "plan")
        o = old.get(key) or {}
        info = dict(number=str(sid) if sid else f"заказ {pre}", status_code=str(st), status=SP.WB_STATUS.get(st, f"статус {st}"),
                    stage=stage, created=_d(r.get("createDate")), planned=_d(r.get("supplyDate")), fact=_d(r.get("factDate")),
                    updated=_d(r.get("updatedDate")))
        # детали — для новых, изменившихся и ещё не принятых поставок (лимит WB — 30 запросов в минуту)
        if (not o or o.get("status_code") != str(st) or o.get("updated") != info["updated"] or o.get("qty") is None
                or stage == "way" or (stage == "done" and o.get("accepted") is None)):
            try:
                time.sleep(2.1)
                det = http("GET", f"{base}/supplies/{sid or pre}" + ("" if sid else "?isPreorderID=true"), WBH, wait429=20) or {}
                if n_det == 0:
                    _raw("wb_supply_details_sample.json", det)
                n_det += 1
                info.update(warehouse=det.get("actualWarehouseName") or det.get("warehouseName"),
                            qty=det.get("quantity"), accepted=det.get("acceptedQuantity"), ready=det.get("readyForSaleQuantity"),
                            acceptance_cost=det.get("acceptanceCost"), note=det.get("rejectReason") or None)
                if det.get("statusID") and det.get("statusID") != st:
                    st = det["statusID"]
                    info.update(status_code=str(st), status=SP.WB_STATUS.get(st, f"статус {st}"), stage=SP.STAGE_WB.get(st, "plan"))
            except ApiError as e:
                log(f"  WB поставка {key}: детали не получены ({e})")
        SP.upsert(con, "wb", key, **info)
    con.commit()
    log(f"WB поставки: {len(lst)} шт., детали обновлены у {n_det}")


def _wh_name(x):
    """'КАЗАНЬ_РФЦ_НОВЫЙ' → 'Казань РФЦ Новый'."""
    keep = {"РФЦ", "МРФЦ", "ХАБ", "СЦ", "КГТ", "ППЗ", "XD", "МСК", "СПБ", "ПВЗ", "ФФ"}
    return " ".join(w if w.upper() in keep else w.capitalize() for w in str(x or "").replace("_", " ").split()) or None


OZ_SUP_ACTIVE = ["DATA_FILLING", "READY_TO_SUPPLY", "ACCEPTED_AT_SUPPLY_WAREHOUSE", "IN_TRANSIT",
                 "ACCEPTANCE_AT_STORAGE_WAREHOUSE", "REPORTS_CONFIRMATION_AWAITING", "REPORT_REJECTED"]
OZ_SUP_FINAL = ["COMPLETED", "REJECTED_AT_SUPPLY_WAREHOUSE", "CANCELLED", "OVERDUE"]
OZ_ACT_STATE = {"AWAITING_APPROVAL_BY_SELLER": "акт ждёт вашего согласования", "APPROVED": "акт согласован",
                "APPROVED_BY_SELLER": "акт согласован", "REJECTED": "акт отклонён", "AUTO_APPROVED": "акт согласован автоматически"}


def oz_supplies():
    """Заявки на поставку FBO: /v3/supply-order/list → get → состав (bundle) → акт приёмки (сколько принято)."""
    import supplies as SP
    cutoff = (TODAY - dt.timedelta(days=SUP_DAYS)).isoformat()
    orders = {}

    def pull(states, use_cut):
        last = ""
        for _ in range(100):
            l = oz("/v3/supply-order/list", {"filter": {"states": states}, "limit": 100, "last_id": last,
                                              "sort_by": "ORDER_CREATION", "sort_dir": "DESC"}) or {}
            ids = l.get("order_ids") or []
            oldest = "9999"
            for i in range(0, len(ids), 50):
                g = oz("/v3/supply-order/get", {"order_ids": ids[i:i + 50]}) or {}
                if not orders and g.get("orders"):
                    _raw("oz_supply_order_sample.json", g["orders"][:3])
                for o in g.get("orders") or []:
                    orders[str(o.get("order_id"))] = o
                    oldest = min(oldest, (o.get("created_date") or "9999")[:10])
            last = l.get("last_id") or ""
            if not ids or not last or (use_cut and oldest < cutoff):
                break
    try:
        pull(OZ_SUP_ACTIVE, False)
        pull(OZ_SUP_FINAL, True)
    except ApiError as e:
        if _no_access(e):
            meta_set("oz_supplies_access", f"нет доступа: {str(e)[:160]}")
            log(f"Ozon поставки: нет доступа ({e})")
            return
        raise
    meta_set("oz_supplies_access", "ok")
    old = SP.known(con, "ozon")
    n = 0
    for o in orders.values():
        ostate = o.get("state") or ""
        created = (o.get("created_date") or "")[:10]
        if ostate in OZ_SUP_FINAL and created and created < cutoff:
            continue
        slot = ((o.get("timeslot") or {}).get("timeslot") or {}) if isinstance(o.get("timeslot"), dict) else {}
        drop = (o.get("drop_off_warehouse") or {}).get("name")
        sups = o.get("supplies") or [{"supply_id": f"o{o.get('order_id')}"}]
        act_by = None
        for s in sups:
            key = str(s.get("supply_id"))
            st = s.get("state") or ostate
            stage = SP.STAGE_OZ.get(st, "plan")
            prev = old.get(key) or {}
            wh = (s.get("storage_warehouse") or {}).get("name") or drop
            info = dict(number=str(o.get("order_number") or o.get("order_id")), status_code=st, status=SP.OZ_STATUS.get(st, st),
                        stage=stage, created=_d(o.get("created_date")), planned=_d(slot.get("from")),
                        updated=_d(o.get("state_updated_date")), warehouse=_wh_name(wh))
            # сколько отправлено — из состава поставки (один раз)
            if s.get("bundle_id") and prev.get("qty") is None:
                try:
                    q, last = 0, ""
                    for _ in range(50):
                        b = oz("/v1/supply-order/bundle", {"bundle_ids": [s["bundle_id"]], "limit": 100, "is_asc": True, "last_id": last}) or {}
                        q += sum(f(i.get("quantity")) for i in b.get("items") or [])
                        if not b.get("has_next") or not b.get("last_id"):
                            break
                        last = b["last_id"]
                    info["qty"] = q
                except ApiError as e:
                    log(f"  Ozon поставка {key}: состав не получен ({e})")
            # сколько принято — из акта приёмки, когда приёмка закончена; пока статус меняется — перечитываем
            if stage == "done" and (prev.get("accepted") is None or prev.get("status_code") != st):
                if act_by is None:
                    act_by = {}
                    try:
                        a = oz("/v1/supply-order/act/summary/get", {"order_id": int(o.get("order_id"))}) or {}
                        for sa in a.get("supplies_acts") or []:
                            acts = sa.get("supply_acts") or []
                            main = next((x for x in acts if x.get("type") == "ACCEPTANCE"), acts[0] if acts else None)
                            if main:
                                act_by[str(sa.get("supply_id"))] = main
                    except ApiError as e:
                        log(f"  Ozon заявка {o.get('order_id')}: акт не получен ({e})")
                m = act_by.get(key)
                if m:
                    sm = m.get("summary") or {}
                    info["accepted"] = sm.get("fact_quantity")
                    info["fact"] = _d(m.get("created_date"))
                    info["note"] = OZ_ACT_STATE.get(m.get("act_state"), m.get("act_state"))
            SP.upsert(con, "ozon", key, **info)
            n += 1
    con.commit()
    log(f"Ozon поставки: {n} шт. ({len(orders)} заявок)")


def main_supplies():
    t0 = time.time()
    ok = True
    if WB_TOKEN:
        ok &= step("WB поставки", wb_supplies)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon поставки", oz_supplies)
    meta_set("supplies_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    status(("Поставки обновлены" if ok else "Поставки: есть ошибки — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


# ============================ Цены ============================
def _ensure_prices_table():
    con.execute("""CREATE TABLE IF NOT EXISTS cur_prices(mp TEXT NOT NULL, article TEXT NOT NULL, mp_sku TEXT,
                   seller_price REAL, buyer_price REAL, base_price REAL, discount REAL, ts TEXT, PRIMARY KEY(mp, article))""")
    try:
        con.execute("ALTER TABLE cur_prices ADD COLUMN buyer_src TEXT")   # откуда цена покупателя: api / index / seller
    except Exception:
        pass


def wb_prices():
    """Ваша цена и скидка на WB (до СПП). Нужна категория «Цены и скидки» в токене; без неё шаг пропускается."""
    _ensure_prices_table()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    off, n = 0, 0
    while True:
        try:
            res = http("GET", f"https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter?limit=1000&offset={off}", WBH, tries=3)
        except ApiError as e:
            if "401" in str(e) or "403" in str(e):
                meta_set("wb_prices_access", "0")
                log("WB цены: у токена нет доступа к «Цены и скидки» — цена продавца берётся из заказов")
                return
            raise
        goods = ((res or {}).get("data") or {}).get("listGoods") or []
        for g in goods:
            sizes = g.get("sizes") or [{}]
            base = f(sizes[0].get("price"))
            disc_price = f(sizes[0].get("discountedPrice")) or base * (1 - f(g.get("discount")) / 100)
            con.execute("""INSERT INTO cur_prices(mp, article, mp_sku, seller_price, base_price, discount, ts) VALUES('wb',?,?,?,?,?,?)
                           ON CONFLICT(mp, article) DO UPDATE SET mp_sku=excluded.mp_sku, seller_price=excluded.seller_price,
                           base_price=excluded.base_price, discount=excluded.discount, ts=excluded.ts""",
                        (g.get("vendorCode") or str(g.get("nmID")), str(g.get("nmID")), disc_price, base, f(g.get("discount")), now))
            n += 1
        con.commit()
        if len(goods) < 1000:
            break
        off += 1000
    meta_set("wb_prices_access", "1")
    log(f"WB цены: {n} карточек")


def _oz_site_price(pr_idx):
    """Цена на сайте Ozon по индексу цен: в API её нет, а скидку за счёт Ozon (Ozon Карта, соинвест) видно только
    через индекс. Ozon считает индекс I по цене на сайте P и минимальной цене конкурентов C:
    P ≤ C → I = P / C;  P > C → I = 2 − C / P.  Обратно: I ≤ 1 → P = I × C, I > 1 → P = C / (2 − I)."""
    for k in ("ozon_index_data", "external_index_data", "self_marketplaces_index_data"):
        d = (pr_idx or {}).get(k) or {}
        c, i = amt(d.get("min_price") or d.get("minimal_price")), f(d.get("price_index_value"))
        if c and i and 0 < i < 2:
            return round(i * c if i <= 1 else c / (2 - i)), k
    return None, None


def oz_prices():
    """Цены Ozon: предельная цена (ваша, с акциями) и оценка цены на сайте — со скидками за счёт Ozon.
    Цена на сайте восстанавливается по индексу цен. У товаров без индекса (WITHOUT_INDEX) скидку Ozon берём
    как у товаров с близкой ценой (±3%), а если таких нет — медиану по всем товарам с индексом."""
    _ensure_prices_table()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor, items_all = "", []
    while True:
        res = oz("/v5/product/info/prices", {"filter": {"visibility": "ALL"}, "cursor": cursor, "limit": 1000}) or {}
        items = res.get("items") or (res.get("result") or {}).get("items") or []
        if not cursor and items:
            _raw("oz_prices_sample.json", items[:10])
        items_all += items
        cursor = res.get("cursor") or ""
        if not items or not cursor or len(items) < 1000:
            break
    recs = []
    for it in items_all:
        pr = it.get("price") or {}
        seller = amt(pr.get("marketing_seller_price")) or amt(pr.get("price"))
        site, _ = _oz_site_price(it.get("price_indexes"))
        if site and seller and site > seller * 1.02:      # цена на сайте не может быть выше предельной
            site = None
        recs.append({"it": it, "pr": pr, "seller": seller, "site": site, "src": "index" if site else None})
    ratios = [(r["seller"], r["site"] / r["seller"]) for r in recs if r["site"] and r["seller"]]
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
    for r in recs:
        if r["site"] or not r["seller"] or not ratios:
            continue
        near = [k for s_, k in ratios if abs(s_ - r["seller"]) <= r["seller"] * 0.03]
        k = med(near) if near else med([k for _, k in ratios])
        r["site"], r["src"] = round(r["seller"] * k), "similar" if near else "median"
    try:   # акции товаров Ozon приходят в том же ответе — сохраняем для раздела «Маркетинг → Акции»
        import promos
        promos.store_ozon(con, items_all)
    except Exception as e:
        log(f"  Ozon акции: {e}")
    for r in recs:
        it, pr, seller = r["it"], r["pr"], r["seller"]
        buyer = r["site"] or amt(pr.get("marketing_price")) or seller
        src = r["src"] or "seller"
        con.execute("""INSERT INTO cur_prices(mp, article, mp_sku, seller_price, buyer_price, base_price, discount, ts, buyer_src)
                       VALUES('ozon',?,?,?,?,?,NULL,?,?) ON CONFLICT(mp, article) DO UPDATE SET mp_sku=excluded.mp_sku,
                       seller_price=excluded.seller_price, buyer_price=excluded.buyer_price, base_price=excluded.base_price,
                       ts=excluded.ts, buyer_src=excluded.buyer_src""",
                    (it.get("offer_id"), str(it.get("product_id") or ""), seller, buyer, amt(pr.get("old_price")) or None, now, src))
    con.commit()
    log(f"Ozon цены: {len(recs)} товаров, с индексом цен {len(ratios)}")


def wb_promos():
    import promos
    try:
        promos.load_wb(con, http, WBH, log, _raw)
        meta_set("promos_wb_error", "")
    except ApiError as e:
        meta_set("promos_wb_error", ("нет доступа: у ключа WB нужна категория «Цены и скидки»" if _no_access(e) else str(e))[:300])
        if not _no_access(e):
            raise


def media_load():
    import media
    if WB_TOKEN:
        media.load_wb(con, log)
    if OZ_ID and OZ_KEY:
        media.load_ozon(con, log)


def main_promos():
    t0 = time.time()
    ok = True
    if WB_TOKEN:
        ok &= step("WB акции", wb_promos)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon цены и акции", oz_prices)
    status(("Акции обновлены" if ok else "Акции: есть ошибки — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


def main_prices():
    """Проверка цен несколько раз в день: свежие заказы (реальная цена покупателя) + цены из API."""
    t0 = time.time()
    log("Проверка цен")
    ok = True
    if WB_TOKEN:
        ok &= step("WB заказы", wb_orders)
        ok &= step("WB цены", wb_prices)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon заказы", lambda: oz_orders(3))
        ok &= step("Ozon цены", oz_prices)
    meta_set("prices_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    if WB_TOKEN:
        ok &= step("WB акции", wb_promos)
    # заодно статусы поставок — чтобы днём видеть, что поставка принята
    if WB_TOKEN:
        ok &= step("WB поставки", wb_supplies)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon поставки", oz_supplies)
    meta_set("supplies_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    status(("Цены проверены" if ok else "Цены: есть ошибки — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


# ============================ Сборочные задания FBS (WB) ============================
FBS_STATUS = {"new": "Новое", "confirm": "На сборке", "complete": "В доставке", "cancel": "Отменено продавцом",
              "receive": "Получено покупателем", "reject": "Отказ при получении"}


def wb_fbs_tasks():
    """Сборочные задания FBS за 7 дней и их статусы: сколько новых, на сборке и отгруженных, но ещё не принятых WB.
    Нужна категория «Маркетплейс» в токене WB."""
    con.executescript("""CREATE TABLE IF NOT EXISTS fbs_tasks(id TEXT PRIMARY KEY, created TEXT, article TEXT, nm_id TEXT,
                           price REAL, supplier_status TEXT, wb_status TEXT, updated TEXT)""")
    base = "https://marketplace-api.wildberries.ru/api/v3"
    since = int((dt.datetime.now() - dt.timedelta(days=7)).timestamp())
    rows, nxt = [], 0
    try:
        for _ in range(50):
            r = http("GET", f"{base}/orders?limit=1000&next={nxt}&dateFrom={since}", WBH, wait429=20) or {}
            part = r.get("orders") or []
            if not rows and part:
                _raw("wb_fbs_orders_sample.json", part[:5])
            rows += part
            nxt = r.get("next") or 0
            if len(part) < 1000 or not nxt:
                break
    except ApiError as e:
        if _no_access(e):
            meta_set("wb_fbs_access", f"нет доступа: {str(e)[:160]}")
            log(f"WB FBS задания: нет доступа ({e}). Нужна категория «Маркетплейс» в токене WB.")
            return
        raise
    meta_set("wb_fbs_access", "ok")
    st = {}
    ids = [o["id"] for o in rows if o.get("id")]
    for i in range(0, len(ids), 1000):
        r = http("POST", f"{base}/orders/status", WBH, {"orders": ids[i:i + 1000]}, wait429=20) or {}
        for x in r.get("orders") or []:
            st[x.get("id")] = (x.get("supplierStatus"), x.get("wbStatus"))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    con.execute("DELETE FROM fbs_tasks WHERE created < ?", ((dt.date.today() - dt.timedelta(days=30)).isoformat(),))
    for o in rows:
        ss, ws = st.get(o.get("id"), (None, None))
        con.execute("INSERT OR REPLACE INTO fbs_tasks VALUES(?,?,?,?,?,?,?,?)",
                    (str(o.get("id")), _d(o.get("createdAt")), o.get("article"), str(o.get("nmId") or ""),
                     f(o.get("convertedPrice") or o.get("price")) / 100, ss, ws, now))
    con.commit()
    meta_set("wb_fbs_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    log(f"WB FBS задания: {len(rows)} за 7 дней")


def main_today():
    """Каждые 30 минут днём: свежие заказы WB и Ozon — для блока «Сегодня» и сигнала о резком росте заказов."""
    t0 = time.time()
    ok = True
    if WB_TOKEN:
        ok &= step("WB заказы", wb_orders)
        ok &= step("WB FBS задания", wb_fbs_tasks)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon заказы", lambda: oz_orders(2))
    meta_set("today_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    status(("Заказы за сегодня обновлены" if ok else "Заказы за сегодня: есть ошибки — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


def main_ozon_wh():
    """Быстрое обновление для раздела «Склады → Ozon»: заказы за 35 дней + остатки по складам."""
    t0 = time.time()
    log("Обновление складов Ozon")
    ok = step("Ozon заказы", lambda: oz_orders(35)) & step("Ozon остатки по складам", oz_wh_stocks)
    status(("Склады Ozon обновлены" if ok else "Склады Ozon: есть ошибки — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


def gsheet_import():
    import gsheet
    gsheet.import_sheet(log)


def main_gsheet():
    t0 = time.time()
    ok = step("Google Таблица: операции", gsheet_import)
    status(("Операции из Google Таблицы загружены" if ok else "Google Таблица: ошибка — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


def main_wb_wh():
    """Быстрое обновление для раздела «Склады → Wildberries»: свежие заказы + остатки."""
    t0 = time.time()
    log("Обновление складов WB")
    ok = step("WB заказы", wb_orders) & step("WB остатки", wb_stocks)
    meta_set("wb_wh_snapshot", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    status(("Склады WB обновлены" if ok else "Склады WB: есть ошибки — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


def main():
    t0 = time.time()
    log("=" * 60)
    log(f"Старт {'полной' if FULL else 'ежедневной'} загрузки")
    ok = True
    if WB_TOKEN:
        ok &= step("WB заказы", wb_orders)
        ok &= step("WB остатки", wb_stocks)
        time.sleep(5)
        ok &= step("WB финансовые отчёты", wb_finance)
    else:
        log("WB: токен не задан")
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon товары", oz_products)
        ok &= step("Ozon начисления", oz_finance)
        ok &= step("Ozon остатки", oz_stocks)
        ok &= step("Ozon остатки по складам", oz_wh_stocks)
        ok &= step("Ozon заказы", oz_orders)
    else:
        log("Ozon: ключи не заданы")
    ok &= step("Google Таблица: операции", gsheet_import)
    if WB_TOKEN:
        ok &= step("WB поставки", wb_supplies)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon поставки", oz_supplies)
    meta_set("supplies_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    orders_history()           # один раз: заказы с начала года (Ozon — отправления, WB — помесячно из аналитики)
    if WB_TOKEN:
        ok &= step("WB цены", wb_prices)
    if OZ_ID and OZ_KEY:
        ok &= step("Ozon цены", oz_prices)
    meta_set("prices_checked", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    if WB_TOKEN:
        ok &= step("WB акции", wb_promos)
    ok &= step("Фото карточек", media_load)
    # артикулы WB в финстроках — в регистре продавца
    con.execute("""UPDATE fin SET article=(SELECT p.article FROM products p WHERE p.mp=fin.mp AND p.mp_sku=fin.mp_sku)
                   WHERE EXISTS(SELECT 1 FROM products p WHERE p.mp=fin.mp AND p.mp_sku=fin.mp_sku AND p.article IS NOT NULL)""")
    con.commit()
    now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    meta_set("last_update", now)
    status(("Готово" if ok else "Готово с ошибками — см. data\\collector_log.txt") + f" ({int(time.time() - t0)} с)")


if __name__ == "__main__":
    running(True)
    try:
        if "--ozon-wh" in sys.argv:
            main_ozon_wh()
        elif "--wb-wh" in sys.argv:
            main_wb_wh()
        elif "--gsheet" in sys.argv:
            main_gsheet()
        elif "--prices" in sys.argv:
            main_prices()
        elif "--today" in sys.argv:
            main_today()
        elif "--supplies" in sys.argv:
            main_supplies()
        elif "--promos" in sys.argv:
            main_promos()
        else:
            main()
    finally:
        running(False)
