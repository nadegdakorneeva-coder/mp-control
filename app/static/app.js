"use strict";
// ================= утилиты =================
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = async (path, opt = {}) => {
  const r = await fetch("/api/" + path, { method: opt.method || "GET", headers: { "Content-Type": "application/json" },
    body: opt.body ? JSON.stringify(opt.body) : undefined });
  const j = await r.json();
  if (r.status === 401 && j && j.need_login) { showLogin(); throw new Error("Нужно войти"); }
  if (j && j.error) throw new Error(j.error);
  return j;
};
function showLogin(msg = "") {
  if ($("#login")) return;
  document.body.insertAdjacentHTML("beforeend", `<div id="login" class="login"><form class="box" autocomplete="on">
    <div class="brand"><span class="logo">MP</span><div><b>MP Control</b><small>Вход в дашборд</small></div></div>
    <label>Телефон<input id="lgP" type="tel" name="username" autocomplete="username" placeholder="+7 900 000-00-00" required></label>
    <label>Пароль<input id="lgW" type="password" name="password" autocomplete="current-password" required></label>
    <div id="lgE" class="lg-err">${esc(msg)}</div>
    <button class="btn primary w100" id="lgB">Войти</button></form></div>`);
  $("#lgP").focus();
  $("#login form").onsubmit = async e => {
    e.preventDefault(); $("#lgB").disabled = true; $("#lgE").textContent = "";
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: $("#lgP").value, password: $("#lgW").value }) });
    if (r.ok) { location.hash = ""; location.reload(); return; }
    const j = await r.json().catch(() => ({}));
    $("#lgE").textContent = j.error || "Не удалось войти"; $("#lgB").disabled = false;
  };
}
const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const rub = v => nf0.format(Math.round(v || 0)) + " ₽";
const qty = v => nf0.format(Math.round(v || 0)) + " шт";
const pct = v => nf2.format(v || 0) + " %";
const days = v => nf1.format(v || 0) + " дн.";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const iso = d => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const d = new Date(s + "T12:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const ruDate = s => s ? s.split("-").reverse().join(".") : "";
const MONTHS = ["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"];
const monthName = m => m === "total" ? "Итого" : MONTHS[+m.slice(5, 7) - 1] + " " + m.slice(0, 4);
const store = {
  get(k, d) { try { const v = localStorage.getItem("mp." + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("mp." + k, JSON.stringify(v)); } catch {} },
};
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];

// ================= состояние фильтров =================
const today = iso(new Date());
const yesterday = addDays(today, -1);
const state = store.get("filters", null) || { from: addDays(yesterday, -6), to: yesterday, mp: "", articles: [], preset: "7" };
if (state.scheme === undefined) state.scheme = "";
let META = { articles: [], accounts: [], categories: [] };
const saveState = () => store.set("filters", state);

function presetRange(p) {
  const y = new Date(yesterday + "T12:00:00");
  if (p === "7") return [addDays(yesterday, -6), yesterday];
  if (p === "14") return [addDays(yesterday, -13), yesterday];
  if (p === "30") return [addDays(yesterday, -29), yesterday];
  if (p === "month") return [today.slice(0, 8) + "01", yesterday < today.slice(0, 8) + "01" ? today : yesterday];
  if (p === "prevmonth") { const a = new Date(y.getFullYear(), new Date().getMonth() - 1, 1, 12); const b = new Date(a.getFullYear(), a.getMonth() + 1, 0, 12); return [iso(a), iso(b)]; }
  if (p === "quarter") return [addDays(yesterday, -89), yesterday];
  if (p === "year") return [today.slice(0, 4) + "-01-01", yesterday];
  return [state.from, state.to];
}
const qs = (extra = {}) => new URLSearchParams({ from: state.from, to: state.to, mp: state.mp,
  articles: state.articles.join("|"), scheme: state.scheme || "", ...extra }).toString();

function filterBar({ period = true, mp = true, articles = true, extra = "" } = {}) {
  const el = $("#filters");
  el.innerHTML = "";
  if (period) {
    el.insertAdjacentHTML("beforeend", `
      <select id="fPreset">
        <option value="7">Последние 7 дней</option><option value="14">14 дней</option><option value="30">30 дней</option>
        <option value="month">Этот месяц</option><option value="prevmonth">Прошлый месяц</option>
        <option value="quarter">90 дней</option><option value="year">С начала года</option><option value="custom">Свой период</option>
      </select>
      <input type="date" id="fFrom" value="${state.from}"> – <input type="date" id="fTo" value="${state.to}">`);
    $("#fPreset").value = state.preset || "custom";
    $("#fPreset").onchange = e => { state.preset = e.target.value; if (state.preset !== "custom") [state.from, state.to] = presetRange(state.preset); saveState(); render(); };
    $("#fFrom").onchange = e => { state.from = e.target.value; state.preset = "custom"; saveState(); render(); };
    $("#fTo").onchange = e => { state.to = e.target.value; state.preset = "custom"; saveState(); render(); };
  }
  if (mp) {
    el.insertAdjacentHTML("beforeend", `<div class="seg" id="fMp">
      <button data-v="">Все</button><button data-v="wb">Wildberries</button><button data-v="ozon">Ozon</button></div>`);
    $$("#fMp button").forEach(b => { b.classList.toggle("on", b.dataset.v === state.mp);
      b.onclick = () => { state.mp = b.dataset.v; saveState(); render(); }; });
    el.insertAdjacentHTML("beforeend", `<div class="seg" id="fSch" title="FBO — со складов маркетплейса, FBS — со своего склада">
      <button data-v="">FBO + FBS</button><button data-v="FBO">FBO</button><button data-v="FBS">FBS</button></div>`);
    $$("#fSch button").forEach(b => { b.classList.toggle("on", b.dataset.v === (state.scheme || ""));
      b.onclick = () => { state.scheme = b.dataset.v; saveState(); render(); }; });
  }
  if (articles) {
    el.insertAdjacentHTML("beforeend", `<div class="dd" id="fArt"><button class="btn">Артикулы${state.articles.length ? ": " + state.articles.length : ""} ▾</button></div>`);
    $("#fArt button").onclick = e => { e.stopPropagation(); articleMenu(); };
    if (state.articles.length) el.insertAdjacentHTML("beforeend", `<button class="btn ghost" id="fReset">Сбросить</button>`);
    $("#fReset") && ($("#fReset").onclick = () => { state.articles = []; saveState(); render(); });
  }
  el.insertAdjacentHTML("beforeend", extra);
}

function articleMenu() {
  const dd = $("#fArt");
  if ($(".menu", dd)) { $(".menu", dd).remove(); return; }
  const sel = new Set(state.articles);
  dd.insertAdjacentHTML("beforeend", `<div class="menu"><input type="search" placeholder="Поиск артикула"><div class="list"></div>
     <div style="display:flex;gap:6px;margin-top:6px"><button class="btn sm primary" id="artOk">Применить</button><button class="btn sm" id="artNone">Снять все</button></div></div>`);
  const menu = $(".menu", dd);
  menu.onclick = e => e.stopPropagation();
  const draw = (q = "") => { $(".list", menu).innerHTML = META.articles.filter(a => a.toLowerCase().includes(q.toLowerCase()))
      .map(a => `<label><input type="checkbox" value="${esc(a)}" ${sel.has(a) ? "checked" : ""}>${esc(a)}</label>`).join("") || `<div class="muted small">Нет артикулов</div>`; };
  draw();
  $("input[type=search]", menu).oninput = e => draw(e.target.value);
  $(".list", menu).onchange = e => { e.target.checked ? sel.add(e.target.value) : sel.delete(e.target.value); };
  $("#artNone").onclick = () => { sel.clear(); draw($("input[type=search]", menu).value); };
  $("#artOk").onclick = () => { state.articles = [...sel]; saveState(); render(); };
  setTimeout(() => document.addEventListener("click", function h() { menu.remove(); document.removeEventListener("click", h); }), 0);
}

// ================= описание показателей =================
// good: up — рост хорошо, down — рост плохо, null — нейтрально
const M = {
  profit: { t: "Чистая прибыль", f: rub, good: "up", sub: "margin", subf: pct },
  profit_wo_opex: { t: "Прибыль без опер. расходов", f: rub, good: "up", sub: "margin_wo_opex", subf: pct },
  sales: { t: "Продажи", f: rub, good: "up", sub: "sales_qty", subf: qty },
  realization: { t: "Реализация (до СПП)", f: rub, good: "up" },
  orders_sum: { t: "Заказы", f: rub, good: "up", sub: "orders_qty", subf: qty },
  buyout: { t: "Процент выкупа", f: pct, good: "up" },
  for_pay: { t: "К перечислению", f: rub, good: "up" },
  commission: { t: "Номинальная комиссия", f: rub, good: "down", sub: "commission_pct", subf: pct },
  acquiring: { t: "Эквайринг", f: rub, good: "down", sub: "acquiring_pct", subf: pct },
  logistics: { t: "Логистика", f: rub, good: "down", sub: "logistics_pct", subf: pct },
  storage: { t: "Хранение", f: rub, good: "down", sub: "storage_pct", subf: pct },
  acceptance: { t: "Платная приёмка", f: rub, good: "down", sub: "acceptance_pct", subf: pct },
  penalty: { t: "Штрафы", f: rub, good: "down", sub: "penalty_pct", subf: pct },
  other: { t: "Прочие удержания", f: rub, good: "down", sub: "other_pct", subf: pct },
  ads: { t: "Реклама / ДРР", f: rub, good: "down", sub: "drr", subf: pct },
  spp: { t: "Скидка МП (СПП)", f: rub, good: null, sub: "spp_pct", subf: pct },
  compensation: { t: "Компенсации", f: rub, good: "up" },
  cost: { t: "Себестоимость продаж", f: rub, good: "down", sub: "cost_pct", subf: pct },
  tax: { t: "Налоги", f: rub, good: null, sub: "tax_pct", subf: pct },
  tax_base: { t: "Налоговая база", f: rub, good: null },
  opex: { t: "Операционные расходы", f: rub, good: "down", sub: "opex_pct", subf: pct },
  roi: { t: "ROI", f: pct, good: "up" },
  price_before_spp: { t: "Цена до СПП", f: rub, good: null },
  avg_sale_price: { t: "Сред. цена продажи", f: rub, good: null },
  logistics_per_unit: { t: "Логистика на 1 шт.", f: rub, good: "down" },
  profit_per_unit: { t: "Прибыль на 1 шт.", f: rub, good: "up" },
  returns: { t: "Возвраты", f: rub, good: "down", sub: "returns_qty", subf: qty },
  stock_qty: { t: "Остатки", f: qty, good: null },
  cap_cost: { t: "Капитализация по себес.", f: rub, good: null },
  cap_retail: { t: "Капитализация по розн.", f: rub, good: null },
  turnover: { t: "Оборачиваемость", f: days, good: "down" },
  gmroi: { t: "GMROI", f: pct, good: "up" },
  gmroi_year: { t: "Годовой GMROI", f: pct, good: "up" },
  orders_qty: { t: "Заказы, шт", f: qty, good: "up" },
  sales_qty: { t: "Продажи, шт", f: qty, good: "up" },
  margin: { t: "Маржинальность", f: pct, good: "up" },
  gross: { t: "Валовая прибыль", f: rub, good: "up" },
  drr_orders: { t: "ДРР по заказам", f: pct, good: "down" },
  no_cost_qty: { t: "Продано без себестоимости, шт", f: qty, good: "down" },
};
// группы карточек «Общих показателей» — порядок групп и карточек внутри них
const KPI_GROUPS = [
  ["Прибыль", ["profit", "profit_wo_opex", "gross", "margin", "roi", "profit_per_unit", "gmroi", "gmroi_year"]],
  ["Заказы, продажи, выплаты", ["orders_sum", "orders_qty", "sales", "sales_qty", "realization", "buyout", "returns", "price_before_spp", "avg_sale_price", "spp", "for_pay", "compensation"]],
  ["Расходы маркетплейса", ["commission", "acquiring", "logistics", "logistics_per_unit", "storage", "acceptance", "penalty", "other", "ads", "drr_orders"]],
  ["Себестоимость, налоги, расходы бизнеса", ["cost", "no_cost_qty", "tax", "tax_base", "opex"]],
  ["Остатки", ["stock_qty", "cap_cost", "cap_retail", "turnover"]],
];
const CARDS_DEFAULT = ["profit", "profit_wo_opex", "sales", "realization", "for_pay", "orders_sum", "buyout",
  "logistics", "ads", "storage", "acceptance", "other", "penalty", "commission", "acquiring", "spp", "compensation",
  "cost", "tax", "tax_base", "opex", "roi", "price_before_spp", "avg_sale_price", "logistics_per_unit",
  "profit_per_unit", "returns", "stock_qty", "cap_cost", "cap_retail", "turnover", "gmroi", "gmroi_year"];

function deltaHtml(cur, prev, good, f) {
  const diff = (cur || 0) - (prev || 0);
  const rel = prev ? diff / Math.abs(prev) * 100 : 0;
  let cls = "flat";
  if (Math.abs(diff) > 1e-9 && good && prev) cls = (diff > 0) === (good === "up") ? "up" : "down";
  const sign = diff > 0 ? "+" : diff < 0 ? "−" : "";
  const val = f === pct ? nf2.format(Math.abs(diff)) : f === days ? nf1.format(Math.abs(diff)) : nf0.format(Math.abs(Math.round(diff)));
  return { cls, html: `<span class="delta ${cls}">${sign}${val}${prev ? ` (${sign}${nf1.format(Math.abs(rel))}%)` : ""}</span>` };
}

// ================= страницы =================
const PAGES = {
  dashboard: { t: "Дашборд", r: pageDashboard },
  summary: { t: "Сводный отчёт", r: pageSummary },
  monthly: { t: "Месячный отчёт", r: pageMonthly },
  dds: { t: "ДДС — движение денег", r: pageDDS },
  pnl: { t: "ОПиУ — прибыли и убытки", r: pagePnl },
  operations: { t: "Операции", r: pageOperations },
  costs: { t: "Себестоимость", r: pageCosts },
  wh_ozon: { t: "Склады — Ozon", r: pageWhOzon },
  wh_wb: { t: "Склады — Wildberries", r: pageWhWb },
  supplies: { t: "Склады — Поставки", r: pageSupplies },
  settings: { t: "Счета, статьи, налоги", r: pageSettings },
  users: { t: "Пользователи и доступ", r: pageUsers },
  config: { t: "Настройки", r: pageConfig },
  photos: { t: "Маркетинг — Фотоконтент", r: pagePhotos },
  promos: { t: "Маркетинг — Акции", r: pagePromos },
  help: { t: "Инструкции", r: pageHelp },
  prices: { t: "Контроль цен", r: pagePrices },
};
const AUTH = () => META.auth || { enabled: false, pages: Object.keys(PAGES), is_admin: true };
const allowedPage = pg => pg === "help" ? true : (pg === "users" || pg === "config") ? AUTH().is_admin : AUTH().pages.includes(pg);
function applyAccess() {
  const a = AUTH();
  $$("#nav a").forEach(el => el.classList.toggle("hidden", !allowedPage(el.dataset.page)));
  // скрыть заголовки групп без видимых пунктов
  $$("#nav .grp").forEach(g => { let n = g.nextElementSibling, vis = false;
    while (n && !n.classList.contains("grp")) { if (n.tagName === "A" && !n.classList.contains("hidden")) vis = true; n = n.nextElementSibling; }
    g.classList.toggle("hidden", !vis); });
  $("#btnUpdate").classList.toggle("hidden", !a.pages.includes("dashboard"));
  const pb = $("#priceBadge"); pb.textContent = META.price_alerts || ""; pb.classList.toggle("hidden", !META.price_alerts);
  const pmb = $("#promoBadges"); if (pmb) { const A = META.promo_active || {}, nw = META.promo_alerts || 0;
    pmb.innerHTML = (A.wb ? `<span class="nbadge pb-wb" title="WB: товаров сейчас в акциях — ${A.wb}">${A.wb}</span>` : "")
      + (A.ozon ? `<span class="nbadge pb-oz" title="Ozon: товаров сейчас в акциях — ${A.ozon}">${A.ozon}</span>` : "")
      + (nw ? `<span class="pb-new" title="Новые попадания в акции с прошлого просмотра: ${nw}"></span>` : ""); }
  const sb = $("#supBadge"); if (sb) { sb.textContent = META.supply_alerts || ""; sb.classList.toggle("hidden", !META.supply_alerts); }
  const w = $("#whoami");
  if (a.user) { w.classList.remove("hidden");
    w.innerHTML = `<div><b>${esc(a.user.name || a.user.phone)}</b><small>${a.user.role === "admin" ? "администратор" : "сотрудник"}</small></div><button class="btn sm ghost" id="btnOut">Выйти</button>`;
    $("#btnOut").onclick = async () => { await fetch("/api/logout", { method: "POST" }); location.hash = ""; location.reload(); };
  } else w.classList.add("hidden");
}
let charts = [];
async function render() {
  let page = (location.hash.replace("#/", "") || "dashboard").split("?")[0];
  if (!PAGES[page] || !allowedPage(page)) {
    const first = AUTH().pages[0];
    if (!first) { $("#page").innerHTML = `<div class="notice warn">Для вашей учётной записи не открыт ни один раздел. Обратитесь к администратору.</div>`; return; }
    if (page !== first) { location.replace("#/" + first); return; }
  }
  const p = PAGES[page];
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.page === page));
  $("#pageTitle").textContent = p.t;
  document.title = p.t + " — " + ((META && META.shop_name) || "MP Control");
  charts.forEach(c => c.destroy()); charts = [];
  $("#alert").innerHTML = "";
  $("#page").innerHTML = `<div class="empty">Загрузка…</div>`;
  try { await p.r($("#page"));
    if (page === "dashboard" && META.price_alerts) $("#alert").insertAdjacentHTML("beforeend",
      `<div class="notice warn">Ниже минимальной цены (МРЦ) продаётся артикулов: <b>${META.price_alerts}</b>. <a href="#/prices">Открыть «Контроль цен»</a></div>`); }
  catch (e) { $("#page").innerHTML = `<div class="notice warn">Ошибка: ${esc(e.message)}</div>`; console.error(e); }
}

function noDataNotice() {
  if (!META.data_to) $("#alert").innerHTML = `<div class="notice">Данных с маркетплейсов пока нет. Нажмите «Обновить данные» слева — первая загрузка займёт несколько минут.</div>`;
}

// ---------- Дашборд ----------
async function pageDashboard(root) {
  filterBar();
  const D = await api("dashboard?" + qs());
  noDataNotice();
  const cards = store.get("cards", CARDS_DEFAULT).filter(k => M[k]);
  let notes = "";
  if (D.missing_days) notes += `<div class="notice warn">В выбранном периоде нет финансовых данных за ${D.missing_days} дн. (отчёты маркетплейсов приходят с задержкой).</div>`;
  if (state.scheme) notes += `<div class="notice">Показано только ${state.scheme} (${state.scheme === "FBS" ? "заказы со своего склада" : "заказы со складов маркетплейса"}). Операционные расходы и история заказов до июля в этом режиме не учитываются — они не делятся по схемам.</div>`;
  if (D.cur.no_cost_qty > 0) notes += `<div class="notice warn">${nf0.format(D.cur.no_cost_qty)} шт. продано по артикулам без себестоимости — прибыль завышена. <a href="#/costs">Заполнить</a></div>`;
  root.innerHTML = `${notes}
    <div class="panel card" id="todayBox"><div class="empty">Загрузка заказов за сегодня…</div></div>
    <div class="panel"><h2>Общие показатели <span class="muted small">сравнение с ${ruDate(D.prev_from)} – ${ruDate(D.prev_to)}</span><span class="sp"></span>
      <button class="btn sm" id="cardsCfg">Настроить карточки</button></h2>
      <div id="kpis"></div></div>
    ${D.wb_schemes ? `<div class="panel card" id="schBox"></div>` : ""}
    <div class="panel card"><h2 id="chTitle">Динамика<span class="sp"></span>
        <div class="seg" id="chGroup"><button data-v="day">По дням</button><button data-v="week">По неделям</button><button data-v="month">По месяцам</button></div>
        <select id="chPeriod" style="margin-left:8px"></select></h2>
      <div class="chips" id="chartChips" style="margin:-2px 0 10px"></div>
      <div class="chart"><canvas id="cDaily"></canvas></div><div class="muted small" id="chNote"></div></div>
    <div class="two panel">
      <div class="card"><h2>Топ-5 товаров по прибыли</h2><div id="top5"></div></div>
      <div class="card"><h2>Куда уходит реализация</h2><div id="struct"></div></div>
    </div>
    <div class="panel"><h2>Товары<span class="sp"></span><button class="btn sm" id="colsCfg">Колонки</button><button class="btn sm" id="csv">Экспорт CSV</button></h2><div id="prodTable"></div></div>`;
  todayPanel();
  if (D.wb_schemes) {
    const S = D.wb_schemes, sh = (a, b) => b ? nf0.format(a / b * 100) + "%" : "—";
    const rowsS = [["Заказы, шт", "orders_qty", v => nf0.format(v)], ["Заказы, ₽", "orders_sum", rub], ["Продажи, шт", "sales_qty", v => nf0.format(v)],
      ["Реализация, ₽", "realization", rub], ["Возвраты, шт", "returns_qty", v => nf0.format(v)], ["Логистика, ₽", "logistics", rub],
      ["Себестоимость, ₽", "cost", rub], ["Прибыль до опер. расходов, ₽", "profit", rub]];
    $("#schBox").innerHTML = `<h2>Wildberries: FBO и FBS <span class="muted small">${ruDate(D.from)} – ${ruDate(D.to)}</span></h2>
      <div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Показатель</th><th>FBO — склады WB</th><th>FBS — свой склад</th><th>Всего WB</th><th>Доля FBS</th></tr></thead><tbody>
      ${rowsS.map(([t, k, fm]) => `<tr><td class="l">${t}</td><td>${fm(S.FBO[k])}</td><td>${fm(S.FBS[k])}</td><td><b>${fm(S.all[k])}</b></td><td>${sh(S.FBS[k], S.all[k])}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="muted small" style="margin-top:6px">Прибыль здесь — без операционных расходов (они не делятся по схемам). Реклама и хранение у WB относятся к FBO. Чтобы весь дашборд показывал только одну схему — переключатель «FBO + FBS / FBO / FBS» вверху.</div>`;
  }
  // карточки
  const kpi = k => {
    const m = M[k]; const c = D.cur[k] || 0, p = D.prev[k] || 0;
    const dlt = deltaHtml(c, p, m.good, m.f);
    const sub = m.sub ? ` <small>/ ${m.subf(D.cur[m.sub])}</small>` : "";
    return `<div class="kpi ${dlt.cls === "up" ? "good" : dlt.cls === "down" ? "bad" : ""}"><div class="t" title="${m.t}">${m.t}</div>
      <div class="v">${m.f(c)}${sub}</div><div class="p">${m.f(p)} ${dlt.html}</div></div>`;
  };
  // карточки по смысловым группам; внутри группы — в постоянном порядке
  const used = new Set();
  const groups = KPI_GROUPS.map(([title, keys]) => { const ks = keys.filter(k => cards.includes(k)); ks.forEach(k => used.add(k)); return [title, ks]; });
  const rest = cards.filter(k => !used.has(k));
  if (rest.length) groups.push(["Другое", rest]);
  $("#kpis").innerHTML = groups.filter(([, ks]) => ks.length).map(([title, ks]) =>
    `<div class="kgroup"><div class="kg-t">${title}</div><div class="grid">${ks.map(kpi).join("")}</div></div>`).join("");
  $("#cardsCfg").onclick = () => pickList("Карточки на дашборде", Object.keys(M).map(k => [k, M[k].t]), cards, v => { store.set("cards", v); render(); });
  // график: свой период и шаг (дни / недели / месяцы), линии включаются плашками
  const LINES = [["orders_sum", "Заказы, ₽"], ["sales", "Продажи, ₽"], ["realization", "Реализация, ₽"], ["profit", "Чистая прибыль, ₽"],
    ["profit_wo_opex", "Прибыль без опер. расходов, ₽"], ["logistics", "Логистика, ₽"], ["storage", "Хранение, ₽"], ["ads", "Реклама, ₽"], ["cost", "Себестоимость, ₽"]];
  const PERIODS = { filter: "как в фильтре сверху", d30: "последние 30 дней", d90: "последние 90 дней", m6: "последние 6 месяцев",
    m12: "последние 12 месяцев", ytd: "с начала года" };
  const chCfg = store.get("chartCfg", { group: "day", period: "filter" });
  let on = store.get("chartLines", ["orders_sum", "profit"]).filter(k => LINES.some(l => l[0] === k));
  let chartObj = null, series = [];
  const range = () => {
    const end = chCfg.period === "filter" ? state.to : yesterday;
    let from = { filter: state.from, d30: addDays(end, -29), d90: addDays(end, -89), ytd: end.slice(0, 4) + "-01-01" }[chCfg.period];
    if (!from) { const m = chCfg.period === "m6" ? 5 : 11; const d = new Date(end.slice(0, 7) + "-01T12:00:00"); d.setMonth(d.getMonth() - m); from = iso(d); }
    if (META.data_from && from < META.data_from && chCfg.period !== "filter") from = META.data_from;   // без пустых месяцев до начала данных
    return [from, end];
  };
  const label = k => chCfg.group === "month" ? monthName(k) : chCfg.group === "week" ? `${ruDate(k).slice(0, 5)}–${ruDate(addDays(k, 6)).slice(0, 5)}` : ruDate(k).slice(0, 5);
  const draw = () => {
    $("#chartChips").innerHTML = LINES.map(([k, t], i) => `<span class="chip ${on.includes(k) ? "on" : ""}" data-k="${k}"><i style="background:${css(SERIES[i % SERIES.length])}"></i>${t}</span>`).join("");
    $$("#chartChips .chip").forEach(ch => ch.onclick = () => {
      on = on.includes(ch.dataset.k) ? on.filter(x => x !== ch.dataset.k) : [...on, ch.dataset.k]; store.set("chartLines", on); draw(); });
    if (chartObj) { charts = charts.filter(c => c !== chartObj); chartObj.destroy(); chartObj = null; }
    const ds = LINES.map(([k, t], i) => [k, t, i]).filter(([k]) => on.includes(k)).map(([k, t, i]) => ({
      label: t, data: series.map(x => x[k]), borderColor: css(SERIES[i % SERIES.length]), backgroundColor: css(SERIES[i % SERIES.length]),
      borderWidth: 2, pointRadius: series.length > 40 ? 0 : 3, pointHoverRadius: 5, tension: .25 }));
    chartObj = lineChart($("#cDaily"), series.map(x => label(x.key)), ds, v => rub(v)); charts.push(chartObj);
    $("#chNote").textContent = on.length ? "" : "Выберите хотя бы одну линию — нажмите на плашку выше.";
  };
  const loadChart = async () => {
    const [f, t] = range();
    $("#chTitle").firstChild.textContent = "Динамика " + { day: "по дням", week: "по неделям", month: "по месяцам" }[chCfg.group] + ` · ${ruDate(f)} – ${ruDate(t)} `;
    const R = chCfg.period === "filter" && chCfg.group === "day" ? { series: D.series.map(x => ({ key: x.day, ...x })) }
      : await api("chart?" + qs({ from: f, to: t, group: chCfg.group }));
    series = R.series;
    draw();
  };
  $$("#chGroup button").forEach(b => { b.classList.toggle("on", b.dataset.v === chCfg.group);
    b.onclick = () => { chCfg.group = b.dataset.v;
      if (b.dataset.v === "month" && ["filter", "d30"].includes(chCfg.period)) chCfg.period = "m12";   // по месяцам за 30 дней смысла нет
      store.set("chartCfg", chCfg); $$("#chGroup button").forEach(x => x.classList.toggle("on", x === b));
      $("#chPeriod").value = chCfg.period; loadChart(); }; });
  $("#chPeriod").innerHTML = Object.entries(PERIODS).map(([k, t]) => `<option value="${k}" ${k === chCfg.period ? "selected" : ""}>${t}</option>`).join("");
  $("#chPeriod").onchange = e => { chCfg.period = e.target.value; store.set("chartCfg", chCfg); loadChart(); };
  await loadChart();
  // топ-5
  $("#top5").innerHTML = D.top.length ? `<div class="tbl" style="max-height:none"><table><tr><th class="l">Товар</th><th>Доля в прибыли</th><th>Чист. прибыль</th><th>Маржа</th><th>Динамика</th></tr>
    ${D.top.map(r => { const dl = deltaHtml(r.profit, r.profit_prev, "up", rub); return `<tr><td class="l">${esc(r.article)}</td><td>${pct(r.profit_share)}</td><td>${rub(r.profit)}</td><td>${pct(r.margin)}</td><td>${dl.html}</td></tr>`; }).join("")}</table></div>` : `<div class="empty">Нет данных</div>`;
  // структура
  const c = D.cur, real = c.realization || 0;
  const parts = [["Комиссия и эквайринг", c.commission + c.acquiring], ["Логистика", c.logistics], ["Себестоимость", c.cost],
    ["Хранение, приёмка, штрафы, прочее", c.storage + c.acceptance + c.penalty + c.other], ["Реклама", c.ads], ["Налоги", c.tax],
    ["Опер. расходы", c.opex], ["Чистая прибыль", Math.max(c.profit, 0)]];
  $("#struct").innerHTML = real > 0 ? `<div class="structure">${parts.map(([t, v], i) => v > 0 ? `<div style="width:${v / real * 100}%;background:${css(SERIES[i])}" data-tip="${t}: ${rub(v)} (${pct(v / real * 100)})"></div>` : "").join("")}</div>
    <div class="legend">${parts.map(([t, v], i) => `<i style="background:${css(SERIES[i])}"></i><span>${t}</span><span class="n">${rub(v)}</span><span class="n muted">${pct(v / real * 100)}</span>`).join("")}</div>
    ${c.profit < 0 ? `<div class="notice warn" style="margin-top:10px">Убыток ${rub(c.profit)}</div>` : ""}
    ${c.compensation ? `<div class="muted small" style="margin-top:8px">Компенсации от МП: ${rub(c.compensation)}</div>` : ""}` : `<div class="empty">Нет данных</div>`;
  bindTips($("#struct"));
  // таблица
  productTable($("#prodTable"), D.table, D.cur);
  $("#csv").onclick = () => exportCsv("товары.csv", $("#prodTable table"));
  $("#colsCfg").onclick = () => pickList("Колонки таблицы", Object.keys(M).map(k => [k, M[k].t]), store.get("prodCols", PROD_COLS), v => { store.set("prodCols", v); render(); });
}
const PROD_COLS = ["orders_qty", "orders_sum", "sales_qty", "realization", "sales", "commission", "logistics", "storage", "cost", "tax", "profit", "margin", "roi", "buyout", "stock_qty", "turnover"];

function productTable(el, rows, total) {
  const cols = store.get("prodCols", PROD_COLS).filter(k => M[k]);
  let sort = store.get("prodSort", { k: "realization", d: -1 });
  const draw = () => {
    const rs = [...rows].sort((a, b) => sort.k === "article" ? String(a.article).localeCompare(b.article) * sort.d : ((a[sort.k] || 0) - (b[sort.k] || 0)) * sort.d);
    el.innerHTML = rows.length ? `<div class="tbl"><table><thead><tr><th class="l sticky" data-k="article">Артикул</th><th class="l">ABC</th>
      ${cols.map(k => `<th data-k="${k}">${M[k].t}${sort.k === k ? (sort.d > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead><tbody>
      <tr class="total"><td class="l sticky">Итого</td><td></td>${cols.map(k => `<td>${M[k].f(total[k])}</td>`).join("")}</tr>
      ${rs.map(r => `<tr><td class="l sticky" title="${esc(r.name)}">${esc(r.article)}</td><td class="l"><span class="abc ${r.abc_profit}" title="ABC по прибыли">${r.abc_profit}</span></td>
        ${cols.map(k => `<td class="${k === "profit" ? (r.profit < 0 ? "down" : "") : ""}">${M[k].f(r[k])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div>` : `<div class="empty">Нет данных за период</div>`;
    $$("th[data-k]", el).forEach(th => th.onclick = () => { sort = { k: th.dataset.k, d: sort.k === th.dataset.k ? -sort.d : -1 }; store.set("prodSort", sort); draw(); });
  };
  draw();
}

function lineChart(canvas, labels, datasets, fmt) {
  const grid = css("--line"), ink = css("--muted");
  return new Chart(canvas, {
    type: "line", data: { labels, datasets },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmt(c.parsed.y)}` } } },
      scales: { x: { grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkipPadding: 12 } },
        y: { grid: { color: grid }, border: { display: false }, ticks: { color: ink, callback: v => nf0.format(v) } } } } });
}

function bindTips(root) {
  const tip = $("#tip");
  $$("[data-tip]", root).forEach(el => {
    el.onmousemove = e => { tip.textContent = el.dataset.tip; tip.classList.remove("hidden"); tip.style.left = e.clientX + 12 + "px"; tip.style.top = e.clientY + 12 + "px"; };
    el.onmouseleave = () => tip.classList.add("hidden");
  });
}

function pickList(title, items, selected, onSave) {
  const sel = new Set(selected);
  openDrawer(`<h3>${title}<button class="btn ghost" data-close>✕</button></h3>
    <div class="colpick">${items.map(([k, t]) => `<label><input type="checkbox" value="${k}" ${sel.has(k) ? "checked" : ""}>${t}</label>`).join("")}</div>
    <div style="margin-top:16px;display:flex;gap:8px"><button class="btn primary" id="plOk">Сохранить</button><button class="btn" id="plReset">По умолчанию</button></div>`);
  $("#plOk").onclick = () => { const order = items.map(i => i[0]).filter(k => $(`#drawer input[value="${k}"]`).checked); closeDrawer(); onSave(order); };
  $("#plReset").onclick = () => { closeDrawer(); onSave(null); };
}

function exportCsv(name, table) {
  if (!table) return;
  const rows = $$("tr", table).map(tr => $$("th,td", tr).map(td => '"' + td.innerText.replace(/\s*₽|\s*шт|\s*%|\s*дн\./g, "").replace(/ | /g, "").replace(/"/g, '""') + '"').join(";"));
  const blob = new Blob(["﻿" + rows.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
}

// ---------- Сводный отчёт ----------
const SUM_COLS = ["price_before_spp", "avg_sale_price", "realization", "sales", "for_pay", "returns", "opex", "other", "cost", "penalty",
  "orders_qty", "orders_sum", "commission", "acquiring", "logistics_per_unit", "logistics", "storage", "buyout", "profit_per_unit",
  "tax", "tax_base", "profit", "profit_wo_opex", "roi", "margin", "ads", "acceptance", "compensation"];
async function pageSummary(root) {
  const g = store.get("sumGroup", "week");
  if (state.preset === "7" || state.preset === "14") { state.preset = "quarter"; [state.from, state.to] = presetRange("quarter"); saveState(); }
  filterBar({ extra: `<div class="seg" id="grp"><button data-v="day">По дням</button><button data-v="week">По неделям</button><button data-v="month">По месяцам</button></div>
    <button class="btn" id="sCols">Колонки</button><button class="btn" id="sCsv">Экспорт CSV</button>` });
  $$("#grp button").forEach(b => { b.classList.toggle("on", b.dataset.v === g); b.onclick = () => { store.set("sumGroup", b.dataset.v); render(); }; });
  const S = await api("summary?" + qs({ group: g }));
  noDataNotice();
  const cols = store.get("sumCols", SUM_COLS).filter(k => M[k]);
  const label = k => g === "week" ? `${weekNo(k)} неделя (${ruDate(k)} – ${ruDate(addDays(k, 6))})` : g === "month" ? monthName(k) : ruDate(k);
  root.innerHTML = S.rows.length ? `<div class="tbl"><table><thead><tr><th class="l sticky">${g === "week" ? "Неделя" : g === "month" ? "Месяц" : "День"}</th>${cols.map(k => `<th>${M[k].t}</th>`).join("")}</tr></thead>
    <tbody><tr class="total"><td class="l sticky">Итого за период</td>${cols.map(k => `<td>${M[k].f(S.total[k])}</td>`).join("")}</tr>
    ${S.rows.map(r => `<tr><td class="l sticky">${label(r.key)}</td>${cols.map(k => {
      const dl = r.prev ? deltaHtml(r.cur[k], r.prev[k], M[k].good, M[k].f) : null;
      return `<td>${M[k].f(r.cur[k])}${dl ? `<span class="sub ${dl.cls}">${dl.html.replace(/<[^>]+>/g, "")}</span>` : ""}</td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div>` : `<div class="empty">Нет данных за период</div>`;
  $("#sCols").onclick = () => pickList("Колонки сводного отчёта", Object.keys(M).map(k => [k, M[k].t]), cols, v => { store.set("sumCols", v); render(); });
  $("#sCsv").onclick = () => exportCsv("сводный.csv", $("#page table"));
}
function weekNo(s) { const d = new Date(s + "T12:00:00"); d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7); const w1 = new Date(d.getFullYear(), 0, 4); return 1 + Math.round(((d - w1) / 864e5 - 3 + (w1.getDay() + 6) % 7) / 7); }

// ---------- ОПиУ ----------
async function pagePnl(root) {
  if (["7", "14", "30"].includes(state.preset)) { state.preset = "year"; [state.from, state.to] = presetRange("year"); saveState(); }
  filterBar({ extra: `<button class="btn" id="pCsv">Экспорт CSV</button>` });
  const P = await api("pnl?" + qs());
  noDataNotice();
  const bold = new Set(["realization", "sales", "direct", "gross", "ebitda", "net"]);
  root.innerHTML = `<div class="tbl"><table><thead><tr><th class="l sticky">Статья</th>${P.columns.map(c => `<th>${monthName(c)}</th>`).join("")}</tr></thead><tbody>
    ${P.rows.map(r => `<tr class="${r.level ? "lvl1" : ""} ${bold.has(r.key) ? "bold" : ""}"><td class="l sticky">${r.name}</td>
      ${r.values.map(v => `<td class="${r.key === "net" && v.v < 0 ? "down" : ""}">${nf0.format(Math.round(v.v))}${r.key !== "realization" && v.v ? `<span class="sub muted">${nf2.format(v.pct)}%</span>` : ""}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div><p class="muted small">Проценты — доля от реализации. Операционные расходы и доходы/расходы ниже EBITDA берутся из раздела «Операции» по дате распределения.</p>`;
  $("#pCsv").onclick = () => exportCsv("опиу.csv", $("#page table"));
}

// ---------- ДДС ----------
async function pageDDS(root) {
  if (["7", "14", "30"].includes(state.preset)) { state.preset = "year"; [state.from, state.to] = presetRange("year"); saveState(); }
  const planned = store.get("ddsPlanned", false);
  filterBar({ mp: false, articles: false, extra: `<label class="row" style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="pl" ${planned ? "checked" : ""}> Учитывать плановые</label>
    <button class="btn primary" id="addOp">Добавить операцию</button>` });
  $("#pl").onchange = e => { store.set("ddsPlanned", e.target.checked); render(); };
  $("#addOp").onclick = () => opForm();
  const R = await api("dds?" + qs({ planned: planned ? 1 : 0 }));
  const ms = R.months;
  const row = (name, vals, cls = "", total) => `<tr class="${cls}"><td class="l sticky">${name}</td>${vals.map(v => `<td class="${v < 0 ? "down" : ""}">${v ? nf0.format(Math.round(v)) : "—"}</td>`).join("")}<td>${total === undefined ? "" : nf0.format(Math.round(total))}</td></tr>`;
  const net = ms.map((_, i) => R.groups.reduce((s, g) => s + g.values[i], 0));
  root.innerHTML = `<div class="grid" style="margin-bottom:14px">${R.accounts.map(a => `<div class="kpi"><div class="t">${esc(a.name)}</div><div class="v">${rub(a.balance)}</div><div class="p">остаток на сегодня</div></div>`).join("")}</div>
   <div class="tbl"><table><thead><tr><th class="l sticky">Статья</th>${ms.map(m => `<th>${monthName(m)}</th>`).join("")}<th>Итого</th></tr></thead><tbody>
   ${row("Остаток на начало", R.opening, "total")}
   ${R.groups.map(g => row(g.group, g.values, "bold", g.total) + g.lines.map(l => row(`<span class="pill ${l.kind === "income" ? "inc" : "exp"}">${l.kind === "income" ? "приход" : "расход"}</span> ${esc(l.name)}`, l.values, "lvl1", l.total)).join("")).join("")}
   ${row("Чистый денежный поток", net, "bold", net.reduce((a, b) => a + b, 0))}
   ${row("Остаток на конец", R.closing, "total")}
   </tbody></table></div>
   ${R.groups.every(g => !g.lines.length) ? `<div class="empty">Операций пока нет. Добавьте первую кнопкой «Добавить операцию» или в разделе «Операции».</div>` : ""}`;
}

// ---------- Операции ----------
async function pageOperations(root) {
  if (["7", "14"].includes(state.preset)) { state.preset = "month"; [state.from, state.to] = presetRange("month"); saveState(); }
  filterBar({ mp: false, articles: false, extra: `<select id="oKind"><option value="">Все типы</option><option value="income">Доходы</option><option value="expense">Расходы</option><option value="transfer">Переводы</option></select>
    <button class="btn primary" id="addOp">Добавить операцию</button><button class="btn" id="gsImp">Загрузить из Google Таблицы</button>` });
  $("#gsImp").onclick = async () => { await api("update?mode=gsheet", { method: "POST" }); poll(); };
  const kind = store.get("opKind", "");
  $("#oKind").value = kind;
  $("#oKind").onchange = e => { store.set("opKind", e.target.value); render(); };
  $("#addOp").onclick = () => opForm();
  const ops = await api("operations?" + new URLSearchParams({ from: state.from, to: addDays(state.to, 366 * 0), kind }));
  const sum = k => ops.filter(o => o.kind === k && !o.is_planned).reduce((s, o) => s + o.amount, 0);
  root.innerHTML = `${META.gsheet_import ? `<p class="muted small">Google Таблица: ${esc(META.gsheet_import)}. Строки из таблицы помечены «таблица» — правьте их в самой таблице, при следующей загрузке они перезапишутся.</p>` : ""}
    <div class="grid" style="margin-bottom:14px">
      <div class="kpi"><div class="t">Поступления</div><div class="v up">${rub(sum("income"))}</div></div>
      <div class="kpi"><div class="t">Списания</div><div class="v down">${rub(sum("expense"))}</div></div>
      <div class="kpi"><div class="t">Сальдо</div><div class="v">${rub(sum("income") - sum("expense"))}</div></div></div>
    ${ops.length ? `<div class="tbl"><table><thead><tr><th class="l">Дата</th><th class="l">Тип</th><th>Сумма</th><th class="l">Счёт</th><th class="l">Статья</th><th class="l">Контрагент</th><th class="l">Назначение</th><th class="l">Распределение</th><th></th></tr></thead><tbody>
      ${ops.map(o => `<tr data-id="${o.id}"><td class="l">${ruDate(o.pay_date)}${o.is_planned ? ` <span class="pill">план</span>` : ""}${o.src === "gsheet" ? ` <span class="pill">таблица</span>` : ""}</td>
        <td class="l"><span class="pill ${o.kind === "income" ? "inc" : o.kind === "expense" ? "exp" : ""}">${{ income: "Доход", expense: "Расход", transfer: "Перевод" }[o.kind]}</span></td>
        <td class="${o.kind === "income" ? "up" : o.kind === "expense" ? "down" : ""}">${o.kind === "expense" ? "−" : ""}${rub(o.amount)}</td>
        <td class="l">${esc(o.account || "")}${o.to_account ? " → " + esc(o.to_account) : ""}</td><td class="l">${esc(o.category || "")}</td>
        <td class="l">${esc(o.counterparty || "")}</td><td class="l" style="max-width:260px;overflow:hidden;text-overflow:ellipsis" title="${esc(o.purpose)}">${esc(o.purpose || "")}</td>
        <td class="l">${ruDate(o.accrual_date)}${o.distribute_months > 1 ? ` на ${o.distribute_months} мес.` : ""}</td>
        <td><button class="btn sm" data-edit>Изменить</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">За период операций нет</div>`}`;
  $$("[data-edit]", root).forEach(b => b.onclick = () => opForm(ops.find(o => o.id == b.closest("tr").dataset.id)));
}

function opForm(op) {
  const o = op || { kind: "expense", pay_date: today, accrual_date: today, distribute_months: 1, account_id: (META.accounts.find(a => !a.archived) || {}).id };
  const accOpts = sel => META.accounts.filter(a => !a.archived || a.id == sel).map(a => `<option value="${a.id}" ${a.id == sel ? "selected" : ""}>${esc(a.name)}</option>`).join("");
  const catOpts = (kind, sel) => `<option value="">— без статьи —</option>` + META.categories.filter(c => c.kind === kind && (!c.archived || c.id == sel)).map(c => `<option value="${c.id}" ${c.id == sel ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  openDrawer(`<h3>${op ? "Изменить операцию" : "Добавить операцию"}<button class="btn ghost" data-close>✕</button></h3>
    <div class="seg" id="kind" style="margin-bottom:16px;width:100%"><button data-v="income" style="flex:1">Доход</button><button data-v="expense" style="flex:1">Расход</button><button data-v="transfer" style="flex:1">Перевод</button></div>
    <div class="form">
      <label>Сумма, ₽ (с НДС) *<input id="oAmount" type="number" step="0.01" value="${o.amount ?? ""}"></label>
      <label>Сумма НДС, ₽<input id="oNds" type="number" step="0.01" value="${o.nds || ""}"></label>
      ${op ? "" : `<div class="full row"><label><input type="radio" name="rep" value="1" checked> Разовая</label><label><input type="radio" name="rep" value="n"> Регулярная (ежемесячно)</label>
        <label id="repN" style="display:none">повторить <input id="oRepeat" type="number" min="2" max="60" value="12" style="width:70px"> мес.</label></div>`}
      <label>Дата списания / поступления *<input id="oPay" type="date" value="${o.pay_date}"></label>
      <label class="opnl">Дата распределения (для ОПиУ)<input id="oAccr" type="date" value="${o.accrual_date || o.pay_date}"></label>
      <label>Счёт *<select id="oAcc">${accOpts(o.account_id)}</select></label>
      <label class="tr">На счёт *<select id="oAcc2">${accOpts(o.to_account_id)}</select></label>
      <label class="ntr">Статья<select id="oCat"></select></label>
      <label class="ntr">Контрагент<input id="oCp" list="cpList" value="${esc(o.counterparty || "")}"><datalist id="cpList"></datalist></label>
      <label class="ntr">Проект<input id="oPrj" value="${esc(o.project || "")}"></label>
      <label class="full">Назначение платежа<textarea id="oPurp" rows="2">${esc(o.purpose || "")}</textarea></label>
      <div class="full row ntr"><label><input type="checkbox" id="oDist" ${o.distribute_months > 1 ? "checked" : ""}> Распределить расход на</label>
        <input id="oMonths" type="number" min="1" max="60" value="${o.distribute_months || 1}" style="width:70px"> мес.</div>
      <div class="full row"><label><input type="checkbox" id="oPlan" ${o.is_planned ? "checked" : ""}> Плановая (ещё не оплачена)</label>
        <label class="ntr"><input type="checkbox" id="oOff" ${o.official ? "checked" : ""}> Официальный расход</label></div>
    </div>
    <div style="margin-top:18px;display:flex;gap:8px;align-items:center"><button class="btn primary" id="oSave">${op ? "Сохранить" : "Добавить"}</button>
      ${op ? `<button class="btn danger" id="oDel">Удалить</button>${op.series_id ? `<button class="btn danger" id="oDelS">Удалить эту и следующие</button>` : ""}` : ""}<span id="oErr" class="down small"></span></div>`);
  let kind = o.kind;
  const setKind = k => { kind = k; $$("#kind button").forEach(b => b.classList.toggle("on", b.dataset.v === k));
    $$(".tr").forEach(e => e.style.display = k === "transfer" ? "" : "none"); $$(".ntr").forEach(e => e.style.display = k === "transfer" ? "none" : "");
    $(".opnl").style.display = k === "transfer" ? "none" : ""; $("#oCat").innerHTML = catOpts(k, o.category_id); };
  $$("#kind button").forEach(b => b.onclick = () => setKind(b.dataset.v));
  setKind(kind);
  $$("input[name=rep]").forEach(r => r.onchange = () => $("#repN").style.display = r.value === "n" && r.checked ? "" : "none");
  api("operations?from=2000-01-01&to=2100-01-01").then(all => { $("#cpList").innerHTML = [...new Set(all.map(x => x.counterparty).filter(Boolean))].map(c => `<option value="${esc(c)}">`).join(""); });
  $("#oSave").onclick = async () => {
    const body = { kind, amount: $("#oAmount").value, nds: $("#oNds").value, pay_date: $("#oPay").value,
      accrual_date: kind === "transfer" ? $("#oPay").value : $("#oAccr").value, account_id: $("#oAcc").value,
      to_account_id: kind === "transfer" ? $("#oAcc2").value : null, category_id: kind === "transfer" ? null : $("#oCat").value,
      counterparty: $("#oCp").value, project: $("#oPrj").value, purpose: $("#oPurp").value,
      distribute_months: $("#oDist").checked ? $("#oMonths").value : 1, is_planned: $("#oPlan").checked, official: $("#oOff").checked,
      repeat_months: !op && $("input[name=rep]:checked").value === "n" ? $("#oRepeat").value : 1 };
    if (!(+body.amount > 0) || !body.pay_date || !body.account_id) { $("#oErr").textContent = "Заполните сумму, дату и счёт"; return; }
    if (kind === "transfer" && body.account_id === body.to_account_id) { $("#oErr").textContent = "Счета перевода должны различаться"; return; }
    await api(op ? "operations/" + op.id : "operations", { method: op ? "PUT" : "POST", body });
    closeDrawer(); render();
  };
  if (op) {
    $("#oDel").onclick = async () => { await api("operations/" + op.id, { method: "DELETE", body: {} }); closeDrawer(); render(); };
    $("#oDelS") && ($("#oDelS").onclick = async () => { await api("operations/" + op.id, { method: "DELETE", body: { series: true, series_id: op.series_id } }); closeDrawer(); render(); });
  }
}

// ---------- Склады ----------
const covCls = (cover, perDay) => perDay <= 0 ? "cv-none" : cover < 14 ? "cv-red" : cover < 30 ? "cv-amb" : "cv-ok";
const covTxt = c => c === null || c === undefined ? "—" : c >= 999 ? "∞" : nf0.format(Math.round(c));
const n0 = v => v ? nf0.format(Math.round(v)) : "—";
const n1 = v => v ? nf1.format(v) : "—";
function whControls(extra = "") {
  const cfg = store.get("whCfg", { days: 14, target: 30 });
  $("#filters").innerHTML = `<div class="ctl">
    <label>Спрос за <select id="whDays">${[7, 14, 30].map(x => `<option value="${x}" ${x == cfg.days ? "selected" : ""}>${x} дней</option>`).join("")}</select></label>
    <label>Запас на <input id="whTarget" type="number" min="7" max="120" value="${cfg.target}" style="width:70px"> дней</label>${extra}</div>`;
  $("#whDays").onchange = e => { cfg.days = +e.target.value; store.set("whCfg", cfg); render(); };
  $("#whTarget").onchange = e => { cfg.target = +e.target.value || 30; store.set("whCfg", cfg); render(); };
  return cfg;
}
const WH_LEGEND = `<div class="legend-row"><span><i class="cv-red" style="background:var(--bad-bg);border:1px solid var(--bad)"></i>запаса меньше 14 дней</span>
  <span><i style="background:#fdf3dc;border:1px solid #c98500"></i>14–30 дней</span><span><i style="border:1px solid var(--line-strong)"></i>больше 30 дней</span>
  <span class="muted">«—» — нет продаж в регионе</span></div>`;

async function pageWhOzon(root) {
  const cfg = whControls(`<button class="btn primary" id="whUpd">Обновить склады Ozon</button><button class="btn" id="whPlan">План поставок (Excel)</button><button class="btn" id="whCsv">Экспорт CSV</button>`);
  $("#whUpd").onclick = async () => { await api("update?mode=ozon_wh", { method: "POST" }); poll(); };
  $("#whPlan").onclick = () => { location.href = "/api/wh/ozon_plan?" + new URLSearchParams({ days: cfg.days, target: cfg.target }); };
  const R = await api("wh/ozon?" + new URLSearchParams({ days: cfg.days, target: cfg.target }));
  const view = store.get("whOzView", "cover");
  if (!R.snapshot) {
    root.innerHTML = `<div class="notice">Остатков Ozon по складам ещё нет. Нажмите «Обновить склады Ozon» — загрузка займёт 1–2 минуты.</div>`; return;
  }
  const cl = R.clusters;
  const ct = R.cluster_totals;
  const sumNeed = cl.reduce((a, c) => a + ct[c].need, 0);
  root.innerHTML = `<p class="muted small">Остатки на ${ruDate(R.snapshot)}${R.snapshot_at ? " (снято " + esc(R.snapshot_at) + ")" : ""}. Спрос — заказы без отмен за ${ruDate(R.from)}–${ruDate(R.to)} по кластеру доставки.
      «Везти» = заказов в день × ${R.target} дн. − остаток − в пути, по каждому кластеру отдельно.</p>
    <div class="panel"><h2>Кластеры<span class="sp"></span><span class="muted small">всего везти: <b>${nf0.format(Math.round(sumNeed))} шт.</b></span></h2>
    <div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Кластер</th><th>Заказов в день</th><th>Остаток, шт</th><th>В пути</th><th>Дней запаса</th><th>Нелокальных заказов</th><th>Артикулов в дефиците</th><th>Везти, шт</th></tr></thead><tbody>
    ${cl.map(c => { const t = ct[c]; return `<tr><td class="l">${esc(c)}</td><td>${n1(t.per_day)}</td><td>${n0(t.stock)}</td><td>${n0(t.in_way)}</td>
      <td class="${covCls(t.cover, t.per_day)}">${covTxt(t.cover)}</td><td>${t.nonlocal === null ? "—" : nf1.format(t.nonlocal) + " %"}</td>
      <td>${t.deficit_skus || "—"}</td><td><b>${n0(t.need)}</b></td></tr>`; }).join("")}</tbody></table></div></div>
    <div class="panel"><h2>Артикулы по кластерам<span class="sp"></span>
      <div class="seg" id="whView"><button data-v="cover">Дней запаса</button><button data-v="stock">Остаток</button><button data-v="per_day">Заказов в день</button><button data-v="need">Везти</button><button data-v="nonlocal">Нелокальные %</button></div></h2>
      ${WH_LEGEND}<div id="whMtx"></div></div>`;
  $$("#whView button").forEach(b => { b.classList.toggle("on", b.dataset.v === view); b.onclick = () => { store.set("whOzView", b.dataset.v); render(); }; });
  const cellVal = (x, v) => v === "cover" ? covTxt(x.cover) : v === "stock" ? n0(x.stock) : v === "per_day" ? n1(x.per_day) : v === "need" ? n0(x.need) : (x.nonlocal === null ? "—" : nf0.format(x.nonlocal) + "%");
  $("#whMtx").innerHTML = `<div class="tbl mtx"><table><thead><tr><th class="l sticky">Артикул</th><th>Заказов в день</th><th>Остаток</th><th>Дней</th><th>Везти</th>
      ${cl.map(c => `<th title="${esc(c)}">${esc(c)}</th>`).join("")}</tr></thead><tbody>
    ${R.rows.map(r => `<tr><td class="l sticky" title="${esc(r.name)}">${esc(r.article)}</td><td>${n1(r.total.per_day)}</td><td>${n0(r.total.stock)}</td>
      <td class="${covCls(r.total.cover, r.total.per_day)}">${covTxt(r.total.cover)}</td><td><b>${n0(r.total.need)}</b></td>
      ${cl.map(c => { const x = r.cells[c]; return `<td class="cell ${covCls(x.cover, x.per_day)}" title="${esc(c)}: заказов в день ${nf1.format(x.per_day)}, остаток ${nf0.format(x.stock)}, в пути ${nf0.format(x.in_way)}, дней запаса ${covTxt(x.cover)}, везти ${nf0.format(Math.round(x.need))}">${cellVal(x, view)}</td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div>`;
  $("#whCsv").onclick = () => exportCsv("склады_ozon.csv", $("#whMtx table"));
}

// закладка для браузера: на странице магазина/бренда WB копирует «артикул WB → дата доставки» с карточек
const WB_BOOKMARKLET = "javascript:" + encodeURIComponent(`(()=>{const R=/(?:^|[^\\d])(послезавтра|завтра|сегодня|\\d{1,2}\\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))/i;
const dateIn=c=>{const w=document.createTreeWalker(c,NodeFilter.SHOW_TEXT);let n;while((n=w.nextNode())){const m=n.nodeValue.match(R);if(m)return m[1]}return null};
const nmOf=e=>{const v=e.getAttribute('data-nm-id');if(v)return v;const m=(e.getAttribute('href')||'').match(/catalog\\/(\\d+)\\/detail/);return m?m[1]:null};
const ids=c=>new Set([...c.querySelectorAll('[data-nm-id],a[href*="/catalog/"]')].map(nmOf).filter(Boolean));
const seen={},out=[];
document.querySelectorAll('[data-nm-id],a[href*="/catalog/"]').forEach(e=>{const nm=nmOf(e);if(!nm||seen[nm])return;let c=e,hit=null;for(let i=0;i<8&&c;i++){if(ids(c).size>1)break;const h=dateIn(c);if(h){hit=h;break}c=c.parentElement}if(hit){seen[nm]=1;out.push([nm,hit])}});
const a=document.querySelector('[class*="address"],[class*="geo"]');
const s=JSON.stringify({src:'wb-delivery',at:new Date().toISOString(),addr:a?(a.innerText||'').trim().slice(0,150):'',url:location.href.slice(0,200),items:out});
const D={'Центральный':['москв','тул','подольск','коледино','электросталь','рязан','владимир','твер','калуг','ярослав','воронеж'],'Северо-Западный':['петербург','шушар','калининград','вологд'],'Южный':['краснодар','ростов','волгоград','астрахан'],'Северо-Кавказский':['невинномысск','ставропол','пятигорск','махачкал'],'Приволжский':['казан','нижний новгород','самар','уф','перм','саратов'],'Уральский':['екатеринбург','челябинск','тюмен'],'Сибирский':['новосибирск','омск','красноярск','барнаул'],'Дальневосточный':['хабаровск','владивосток','якутск']};
const al=(a?(a.innerText||''):'').toLowerCase();let dn='';for(const k in D)if(D[k].some(x=>al.includes(x))){dn=k;break}
const t=document.createElement('textarea');t.value=s;document.body.appendChild(t);t.select();document.execCommand('copy');t.remove();
alert(out.length?('Скопировано карточек: '+out.length+(dn?('\\nОкруг по адресу: '+dn+'.'):'\\nОкруг по адресу не определился — выберите его в дашборде.')+'\\nТеперь в дашборде: Склады → Wildberries → «Вставить данные с WB».'):'Не нашёл карточек с датой доставки. Откройте страницу магазина или бренда и прокрутите её до конца.')})()`);

async function pageWhWb(root) {
  const cfg = whControls(`<button class="btn primary" id="whUpd">Обновить склады WB</button><button class="btn" id="whXls">План поставок (Excel)</button><button class="btn" id="whCsv">Экспорт CSV</button>`);
  $("#whUpd").onclick = async () => { await api("update?mode=wb_wh", { method: "POST" }); poll(); };
  const qp = new URLSearchParams({ days: cfg.days, target: cfg.target });
  $("#whXls").onclick = () => { location.href = "/api/wh/wb_plan?" + qp; };
  const R = await api("wh/wb?" + qp);
  const S = R.settings, ds = R.districts, dt = R.district_totals;
  const view = store.get("whWbView", "ship");
  const short = x => x.replace(" федеральный округ", "").replace("Северо-Кавказский", "Сев.-Кавказский");
  const whNames = [...new Set(Object.values(S.map).filter(Boolean).concat(["Коледино", "Электросталь", "Подольск", "Тула", "Рязань (Тюшевское)", "Котовск", "Владимир", "Санкт-Петербург (Шушары)", "Казань", "Самара (Новосемейкино)", "Краснодар", "Волгоград", "Невинномысск", "Екатеринбург", "Новосибирск", "Хабаровск"]))];
  const checked = ds.filter(x => dt[x].checked > 0).length;
  root.innerHTML = `<div class="notice">WB не раскрывает остатки по складам, поэтому общий остаток раскладывается по округам пропорционально спросу.
      Если по срокам доставки видно, что в округе товара нет (доставка ${S.threshold} дн. и дольше), остаток там считается нулевым и поставка идёт туда.
      Отметки о наличии действуют ${R.fresh_days} дней. ${checked ? `Сейчас проверено округов: <b>${checked}</b> из ${ds.length}.` : "Проверок наличия ещё не было — план считается только по доле спроса."}</div>
    <div class="grid" style="margin-bottom:6px">
      <div class="kpi"><div class="t">Заказов в день</div><div class="v">${nf1.format(R.total.per_day)}</div><div class="p">за ${ruDate(R.from)}–${ruDate(R.to)}</div></div>
      <div class="kpi"><div class="t">Остаток на складах WB</div><div class="v">${n0(R.total.stock)} шт</div><div class="p">на ${ruDate(R.snapshot)}${R.snapshot_at ? ", обновлено " + esc(R.snapshot_at) : ""}</div></div>
      <div class="kpi ${R.total.cover < 14 ? "bad" : ""}"><div class="t">Дней запаса</div><div class="v">${covTxt(R.total.cover)}</div></div>
      <div class="kpi"><div class="t">Везти всего</div><div class="v">${n0(R.total.need)} шт</div><div class="p">до запаса в ${R.target} дн., по складам</div></div></div>
    <div class="two"><div>
      <div class="card"><h2>Округа и склады отгрузки<span class="sp"></span><button class="btn sm primary" id="mapSave">Сохранить склады</button></h2>
        <div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Округ</th><th>Доля спроса</th><th>В день</th><th class="l">Склад отгрузки</th><th class="l">Наличие</th><th title="До переноса мелких партий на основной склад">Потребность, шт</th></tr></thead><tbody>
        ${ds.map(x => { const t = dt[x]; return `<tr><td class="l">${esc(short(x))}</td><td>${nf1.format(t.share)} %</td><td>${n1(t.per_day)}</td>
          <td class="l"><input class="whmap" data-d="${esc(x)}" list="whList" value="${esc(S.map[x] || "")}" placeholder="не везём" style="width:170px"></td>
          <td class="l small">${t.checked ? `${ruDate(t.last_check)}: <b class="${t.missing ? "down" : ""}">нет у ${t.missing}</b> из ${t.checked} <button class="btn sm ghost" data-clr="${esc(x)}" title="Удалить отметки округа">✕</button>` : `<span class="muted">не проверено</span>`}</td>
          <td><b>${n0(t.need)}</b></td></tr>`; }).join("")}</tbody></table></div>
        <datalist id="whList">${whNames.map(w => `<option value="${esc(w)}">`).join("")}</datalist>
        <p class="muted small">Пустой склад — в этот округ не везём (его спрос всё равно учитывается в расходе общего остатка).</p></div>
      <div class="card panel"><h2>План по складам</h2><div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Склад</th><th class="l">Округа</th><th>Артикулов</th><th>Везти, шт</th></tr></thead><tbody>
        ${R.warehouses.map(w => `<tr><td class="l"><b>${esc(w.warehouse)}</b></td><td class="l">${esc(w.districts.join(", "))}</td><td>${w.articles}</td><td><b>${n0(w.qty)}</b></td></tr>`).join("") || `<tr><td class="l muted" colspan="4">Везти ничего не нужно</td></tr>`}</tbody></table></div>
        <p class="muted small">Партии меньше ${S.min_qty} шт. переносятся на основной склад артикула.</p></div>
    </div><div>
      <div class="card"><h2>Проверка наличия по срокам доставки</h2>
        <ol class="steps">
          <li>Один раз перетащите кнопку <a class="btn sm primary" id="bmk" href="#">WB → дашборд</a> на панель закладок браузера.</li>
          <li>Один раз сохраните в своём профиле WB восемь адресов — любой пункт выдачи WB в каждом городе из списка ниже. Дальше адрес меняется в два клика: адрес в шапке сайта → выбрать из сохранённых.</li>
          <li>Выберите адрес первого города, откройте страницу бренда MOCHEQI и прокрутите её до конца, чтобы прогрузились все товары.</li>
          <li>Нажмите закладку «WB → дашборд» — данные скопируются.</li>
          <li>Здесь нажмите <button class="btn sm" id="presIn">Вставить данные с WB</button> и выберите округ.</li>
        </ol>
        <div class="tbl" style="max-height:none;margin:8px 0"><table><thead><tr><th class="l">Округ</th><th class="l">Адрес: пункт выдачи в г.</th><th class="l">Проверено</th></tr></thead><tbody>
          ${Object.entries(R.check_city).map(([x, city]) => { const t = dt[x] || {}; const age = t.last_check ? Math.round((new Date(today) - new Date(t.last_check)) / 864e5) : null;
            return `<tr><td class="l">${esc(short(x))}</td><td class="l"><b>${esc(city)}</b></td><td class="l small">${age === null ? `<span class="down">нужно проверить</span>` : age <= 7 ? `<span class="up">✓ ${age === 0 ? "сегодня" : ruDate(t.last_check)}</span>` : `<span class="down">${ruDate(t.last_check)} — пора обновить</span>`}</td></tr>`; }).join("")}</tbody></table></div>
        <p class="muted small">Порядок не важен. После вставки округ подставляется сам по адресу на WB — проверьте, что он верный.</p>
        <div class="form" style="margin-top:8px">
          <label>«Нет на месте», если доставка от, дней<input id="thr" type="number" min="2" max="14" step="1" value="${S.threshold}"></label>
          <label>Мин. партия на склад, шт<input id="minq" type="number" min="0" max="100" value="${S.min_qty}"></label></div>
        <div style="margin-top:8px"><button class="btn sm" id="setSave">Применить</button></div></div>
    </div></div>
    <div class="panel"><h2>Артикулы по округам<span class="sp"></span>
      <div class="seg" id="whView"><button data-v="ship">Везти</button><button data-v="days">Доставка, дн.</button><button data-v="est">Оценка остатка</button><button data-v="per_day">Заказов в день</button><button data-v="share">Доля спроса</button></div></h2>
      <div class="legend-row"><span><i style="background:var(--bad-bg);border:1px solid var(--bad)"></i>в округе нет (долгая доставка)</span><span><i style="background:var(--good-bg);border:1px solid var(--good)"></i>есть на месте</span><span><i style="border:1px solid var(--line-strong)"></i>не проверено</span></div>
      <div id="whMtx"></div></div>`;
  $("#bmk").href = WB_BOOKMARKLET;
  $("#bmk").onclick = e => { e.preventDefault(); alert("Эту кнопку нужно не нажимать, а перетащить мышкой на панель закладок браузера (Ctrl+Shift+B — показать панель)."); };
  $("#mapSave").onclick = async () => { const map = {}; $$(".whmap").forEach(i => map[i.dataset.d] = i.value.trim());
    await api("wh/wb_settings", { method: "POST", body: { map } }); render(); };
  $("#setSave").onclick = async () => { await api("wh/wb_settings", { method: "POST", body: { threshold: +$("#thr").value || 4, min_qty: +$("#minq").value || 0 } }); render(); };
  $$("[data-clr]").forEach(b => b.onclick = async () => { await api("wh/wb_presence?district=" + encodeURIComponent(b.dataset.clr), { method: "DELETE", body: {} }); render(); });
  $("#presIn").onclick = () => {
    openDrawer(`<h3>Данные с WB<button class="btn ghost" data-close>✕</button></h3>
      <p class="muted small">Вставьте сюда (Ctrl+V) то, что скопировала закладка «WB → дашборд».</p>
      <textarea id="pTxt" rows="6" style="width:100%;font:12px ui-monospace,Consolas,monospace"></textarea>
      <div id="pInfo" class="small" style="margin:8px 0"></div>
      <div class="form"><label class="full">Округ, для которого смотрели сроки<select id="pDist"><option value="">— выберите —</option>${ds.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("")}</select></label></div>
      <div id="pErr" class="lg-err"></div>
      <div style="margin-top:12px;display:flex;gap:8px"><button class="btn primary" id="pSave">Сохранить</button></div>`);
    const guess = addr => { const a = (addr || "").toLowerCase();
      for (const [d, keys] of Object.entries(R.city_district || {})) if (keys.some(k => a.includes(k))) return d; return ""; };
    $("#pTxt").oninput = () => { try { const j = JSON.parse($("#pTxt").value);
        $("#pInfo").innerHTML = `Карточек: <b>${j.items.length}</b>${j.addr ? ` · адрес на WB: <b>${esc(j.addr)}</b>` : ""}`;
        const g = guess(j.addr); if (g && !$("#pDist").value) $("#pDist").value = g;
      } catch { $("#pInfo").textContent = ""; } };
    $("#pTxt").focus();
    $("#pSave").onclick = async () => {
      try { const r = await api("wh/wb_presence", { method: "POST", body: { district: $("#pDist").value, data: $("#pTxt").value } });
        $("#pErr").textContent = ""; closeDrawer();
        alert(`Сохранено: ${r.saved} артикулов для округа «${r.district}».` + (r.skipped ? ` Чужих карточек пропущено: ${r.skipped}.` : "") + (r.unparsed ? ` Без даты: ${r.unparsed}.` : ""));
        render();
      } catch (e) { $("#pErr").textContent = e.message; } };
  };
  const cls = c => c.status === "no" ? "cv-red" : c.status === "yes" ? "cv-ok-g" : "";
  const cv = (c, v) => v === "per_day" ? n1(c.per_day) : v === "share" ? (c.share ? nf0.format(c.share) + "%" : "—") : v === "est" ? n0(c.est)
    : v === "days" ? (c.days === null || c.days === undefined ? "?" : nf0.format(c.days)) : (c.ship ? nf0.format(c.ship) : "—");
  $$("#whView button").forEach(b => { b.classList.toggle("on", b.dataset.v === view); b.onclick = () => { store.set("whWbView", b.dataset.v); render(); }; });
  $("#whMtx").innerHTML = `<div class="tbl mtx"><table><thead><tr><th class="l sticky">Артикул</th><th>Заказов в день</th><th>Остаток WB</th><th>Дней</th><th>Везти</th>
      ${ds.map(x => `<th title="${esc(x)}">${esc(short(x))}</th>`).join("")}</tr></thead><tbody>
    ${R.rows.map(r => `<tr><td class="l sticky" title="${esc(r.name)} · WB ${esc(r.nm)}">${esc(r.article)}</td><td>${n1(r.total.per_day)}</td><td>${n0(r.total.stock)}</td>
      <td class="${covCls(r.total.cover, r.total.per_day)}">${covTxt(r.total.cover)}</td><td><b>${n0(r.total.need)}</b></td>
      ${ds.map(x => { const c = r.cells[x]; return `<td class="cell ${cls(c)}" title="${esc(x)}: заказов в день ${nf1.format(c.per_day)}, держать ${nf0.format(Math.round(c.keep))}, оценка остатка ${nf0.format(Math.round(c.est))}${c.label ? ", доставка «" + esc(c.label) + "» (" + ruDate(c.checked) + ")" : ", наличие не проверено"}">${cv(c, view)}</td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div>`;
  $("#whCsv").onclick = () => exportCsv("склады_wb.csv", $("#whMtx table"));
}

// ---------- Себестоимость ----------
const FLOPPY = `<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M2 2.5A1.5 1.5 0 0 1 3.5 1h7.38a1.5 1.5 0 0 1 1.06.44l1.62 1.62A1.5 1.5 0 0 1 14 4.12V12.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-10Zm2 0V5h6V2.5H4Zm4 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z"/></svg>`;
async function pageCosts(root) {
  const scheme = store.get("costScheme", "FBO"), empty = store.get("costEmpty", false);
  filterBar({ period: false, articles: false, extra: `<div class="seg" id="sch"><button data-v="FBO">FBO</button><button data-v="FBS">FBS</button></div>
    <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="cEmpty" ${empty ? "checked" : ""}> Себестоимость не заполнена</label>
    <input type="search" id="cSearch" placeholder="Поиск артикула">
    <button class="btn" id="cImport">Загрузить из Excel</button><input type="file" id="cFile" accept=".xlsx" hidden>` });
  $$("#sch button").forEach(b => { b.classList.toggle("on", b.dataset.v === scheme); b.onclick = () => { store.set("costScheme", b.dataset.v); render(); }; });
  $("#cEmpty").onchange = e => { store.set("costEmpty", e.target.checked); render(); };
  $("#cImport").onclick = () => $("#cFile").click();
  $("#cFile").onchange = e => importCosts(e.target.files[0]);
  const C = await api("costs?" + new URLSearchParams({ scheme, mp: state.mp, empty: empty ? 1 : 0 }));
  const draw = (q = "") => {
    const rows = C.rows.filter(r => !q || (r.article + r.mp_sku).toLowerCase().includes(q.toLowerCase()));
    $("#costTbl").innerHTML = `<div class="tbl"><table><thead><tr><th class="l">Артикул</th><th class="l">МП</th><th class="l">Артикул МП</th><th class="l">Название</th><th>Себестоимость, ₽</th><th>Фулфилмент, ₽</th><th>НДС, ₽</th><th></th></tr></thead><tbody>
      ${rows.map(r => `<tr data-sku="${esc(r.mp_sku)}" data-mp="${r.mp}" data-art="${esc(r.article)}"><td class="l">${esc(r.article)}</td><td class="l">${r.mp === "wb" ? "WB" : "Ozon"}</td><td class="l">${esc(r.mp_sku)}</td>
        <td class="l" style="max-width:280px;overflow:hidden;text-overflow:ellipsis">${esc(r.name)}</td>
        <td><input type="number" data-f="cost" value="${r.cost || 0}" class="${r.cost ? "" : "down"}"></td><td><input type="number" data-f="fulfillment" value="${r.fulfillment || 0}"></td>
        <td><input type="number" data-f="nds" value="${r.nds || 0}"></td><td class="small muted" data-st></td></tr>`).join("")}</tbody></table></div>`;
    // у каждого поля своя иконка-дискета: серая — сохранено, жёлтая — есть изменения, зелёная — только что сохранено, красная — ошибка.
    // Сохраняется само: через секунду после того, как перестали печатать, по Enter/Tab или при уходе из поля.
    $$("#costTbl input").forEach(inp => {
      inp.dataset.saved = inp.value;
      const ic = document.createElement("span"); ic.className = "sv sv-idle"; ic.innerHTML = FLOPPY; ic.title = "Сохранено";
      inp.after(ic);
      const set = (cls, tip) => { ic.className = "sv " + cls; ic.title = tip; };
      let timer = null;
      const save = async () => {
        clearTimeout(timer);
        if (inp.value === inp.dataset.saved) return;
        const tr = inp.closest("tr"), val = inp.value;
        set("sv-saving", "Сохраняю…");
        try {
          const row = { mp: tr.dataset.mp, mp_sku: tr.dataset.sku, article: tr.dataset.art, scheme };
          $$("input", tr).forEach(i => row[i.dataset.f] = +(i.dataset.f === inp.dataset.f ? val : i.dataset.saved) || 0);
          await api("costs", { method: "POST", body: { rows: [row] } });
          inp.dataset.saved = val;
          set(inp.value === val ? "sv-ok" : "sv-dirty", "Сохранено " + new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }));
          if (inp.value !== val) timer = setTimeout(save, 1000);   // пока сохраняли, успели ещё что-то ввести
          inp.classList.toggle("down", inp.dataset.f === "cost" && !+inp.dataset.saved);
          $("[data-st]", tr).textContent = "";
        } catch (e) {
          set("sv-err", "Не сохранено: " + e.message);
          $("[data-st]", tr).innerHTML = `<span class="st-err">не сохранено: ${esc(e.message)}</span>`;
        }
      };
      inp.oninput = () => { set(inp.value === inp.dataset.saved ? "sv-idle" : "sv-dirty", "Есть несохранённые изменения");
        clearTimeout(timer); timer = setTimeout(save, 1000); };
      inp.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); save(); } };
      inp.onblur = save;
      inp.onchange = save;
    });
  };
  const zero = C.rows.filter(r => !r.cost).length;
  root.innerHTML = `${C.missing.length ? `<div class="notice warn">Продаются, но нет в таблице себестоимости: ${C.missing.map(m => `<b>${esc(m.article || m.mp_sku)}</b> (${m.mp === "wb" ? "WB" : "Ozon"} ${esc(m.mp_sku)})`).join(", ")}.
      <button class="btn sm" id="addMissing">Добавить их в таблицу</button></div>` : ""}
    <p class="muted small">Себестоимость и фулфилмент — в рублях за 1 шт. Изменения сохраняются сами — через секунду после ввода, по Enter или при уходе из поля. Иконка-дискета рядом с полем: жёлтая — есть несохранённые изменения, зелёная — сохранено, красная — ошибка (наведите мышь, чтобы увидеть причину). Всего строк: ${C.rows.length}${zero ? `, без себестоимости: <b class="down">${zero}</b>` : ""}.</p>
    <div id="costTbl"></div>`;
  draw();
  $("#cSearch").oninput = e => draw(e.target.value);
  $("#addMissing") && ($("#addMissing").onclick = async () => {
    await api("costs", { method: "POST", body: { rows: C.missing.flatMap(m => ["FBO", "FBS"].map(s => ({ mp: m.mp, mp_sku: m.mp_sku, article: m.article, scheme: s, cost: 0 }))) } });
    render();
  });
}

function importCosts(file) {
  if (!file) return;
  const rd = new FileReader();
  rd.onload = async () => {
    const b64 = rd.result.split(",")[1];
    const r = await api("costs/import", { method: "POST", body: { file: b64 } });
    alert(`Загружено строк: ${r.imported}`); render();
  };
  rd.readAsDataURL(file);
}

// ---------- Настройки ----------
async function pageSettings(root) {
  filterBar({ period: false, mp: false, articles: false });
  const t = META.tax;
  const pnlNames = { opex: "Операционные расходы", none: "Не попадает в ОПиУ", fin_income: "Доходы ниже EBITDA", inv_income: "Инвест. доходы",
    fin_expense: "Финансовые расходы", inv_expense: "Инвест. расходы", dividends: "Дивиденды", tax: "Налоги" };
  const grpNames = { operating: "Операционная", financial: "Финансовая", investing: "Инвестиционная" };
  root.innerHTML = `<div class="two"><div>
     <div class="card"><h2>Счета<span class="sp"></span><button class="btn sm primary" id="accAdd">Добавить счёт</button></h2>
       <div class="tbl" style="max-height:none"><table><tr><th class="l">Название</th><th>Начальный остаток</th><th class="l">На дату</th><th></th></tr>
       ${META.accounts.map(a => `<tr data-id="${a.id}" class="${a.archived ? "muted" : ""}"><td class="l">${esc(a.name)}${a.archived ? " (архив)" : ""}</td><td>${rub(a.opening_balance)}</td><td class="l">${ruDate(a.opening_date)}</td><td><button class="btn sm" data-acc>Изменить</button></td></tr>`).join("")}</table></div></div>
     <div class="card panel"><h2>Статьи доходов и расходов<span class="sp"></span><button class="btn sm primary" id="catAdd">Добавить статью</button></h2>
       <div class="tbl" style="max-height:none"><table><tr><th class="l">Статья</th><th class="l">Тип</th><th class="l">ДДС</th><th class="l">ОПиУ</th><th></th></tr>
       ${META.categories.filter(c => !c.archived).map(c => `<tr data-id="${c.id}"><td class="l">${esc(c.name)}</td><td class="l"><span class="pill ${c.kind === "income" ? "inc" : "exp"}">${c.kind === "income" ? "доход" : "расход"}</span></td><td class="l">${grpNames[c.dds_group] || ""}</td><td class="l">${pnlNames[c.pnl_line] || ""}</td><td><button class="btn sm" data-cat>Изменить</button></td></tr>`).join("")}</table></div></div>
   </div><div>
     <div class="card"><h2>Налоги</h2>
       <div class="seg" id="taxMode" style="margin-bottom:10px"><button data-v="actual">По факту (Налог ИП из операций)</button><button data-v="rates">По ставкам</button></div>
       <p class="muted small"><b>По факту</b> — в прибыли учитываются реально уплаченные налоги ИП из операций (статьи со строкой ОПиУ «Налоги»), по месяцу начисления. Для отборов по артикулу или площадке налог всё равно считается по ставкам.<br>
       <b>По ставкам</b> — УСН ${t.usn}% и НДС ${t.nds}% от ${{ sales: "фактических продаж", realization: "реализации", for_pay: "суммы к перечислению" }[t.base] || t.base} (ставки — в разделе <a href="#/config">Настройки</a>). Включать оба способа одновременно нельзя — налоги задвоятся.</p></div>
     <div class="card panel"><h2>Данные</h2><p>Загружены данные с <b>${ruDate(META.data_from) || "—"}</b> по <b>${ruDate(META.data_to) || "—"}</b>.</p>
       <p>Последнее обновление: ${META.last_update ? esc(META.last_update) : "не было"}</p>
       <button class="btn" id="fullUpd">Перезагрузить всю историю</button><p class="muted small">Полная перезагрузка тянет данные за всё доступное время и занимает до получаса из-за лимитов API.</p></div>
   </div></div>`;
  $("#accAdd").onclick = () => accForm();
  $$("[data-acc]").forEach(b => b.onclick = () => accForm(META.accounts.find(a => a.id == b.closest("tr").dataset.id)));
  $("#catAdd").onclick = () => catForm();
  $$("[data-cat]").forEach(b => b.onclick = () => catForm(META.categories.find(c => c.id == b.closest("tr").dataset.id)));
  $("#fullUpd").onclick = () => startUpdate(true);
  $$("#taxMode button").forEach(b => { b.classList.toggle("on", b.dataset.v === (t.mode || "actual"));
    b.onclick = async () => { await api("settings", { method: "POST", body: { tax_mode: b.dataset.v } }); await loadMeta(); render(); }; });
  function accForm(a) {
    a = a || { name: "", kind: "bank", opening_balance: 0, opening_date: today.slice(0, 4) + "-01-01" };
    openDrawer(`<h3>${a.id ? "Счёт" : "Новый счёт"}<button class="btn ghost" data-close>✕</button></h3><div class="form">
      <label class="full">Название<input id="aN" value="${esc(a.name)}"></label>
      <label>Начальный остаток, ₽<input id="aB" type="number" step="0.01" value="${a.opening_balance || 0}"></label>
      <label>На дату<input id="aD" type="date" value="${a.opening_date}"></label></div>
      <div style="margin-top:16px;display:flex;gap:8px"><button class="btn primary" id="aS">Сохранить</button>${a.id ? `<button class="btn danger" id="aX">Удалить</button>` : ""}</div>`);
    $("#aS").onclick = async () => { const body = { name: $("#aN").value, kind: a.kind, opening_balance: +$("#aB").value || 0, opening_date: $("#aD").value, archived: 0 };
      await api(a.id ? "accounts/" + a.id : "accounts", { method: a.id ? "PUT" : "POST", body }); closeDrawer(); await loadMeta(); render(); };
    a.id && ($("#aX").onclick = async () => { await api("accounts/" + a.id, { method: "DELETE", body: {} }); closeDrawer(); await loadMeta(); render(); });
  }
  function catForm(c) {
    c = c || { name: "", kind: "expense", dds_group: "operating", pnl_line: "opex" };
    const opt = (o, v) => Object.entries(o).map(([k, t]) => `<option value="${k}" ${k === v ? "selected" : ""}>${t}</option>`).join("");
    openDrawer(`<h3>${c.id ? "Статья" : "Новая статья"}<button class="btn ghost" data-close>✕</button></h3><div class="form">
      <label class="full">Название<input id="cN" value="${esc(c.name)}"></label>
      <label>Тип<select id="cK">${opt({ income: "Доход", expense: "Расход" }, c.kind)}</select></label>
      <label>Раздел ДДС<select id="cG">${opt(grpNames, c.dds_group)}</select></label>
      <label class="full">Строка ОПиУ<select id="cP">${opt(pnlNames, c.pnl_line)}</select></label></div>
      <p class="muted small">«Не попадает в ОПиУ» — для закупки товара (она уже учтена через себестоимость), поступлений от МП, займов, налогов (считаются автоматически).</p>
      <div style="margin-top:16px;display:flex;gap:8px"><button class="btn primary" id="cS">Сохранить</button>${c.id ? `<button class="btn danger" id="cX">Удалить</button>` : ""}</div>`);
    $("#cS").onclick = async () => { const body = { name: $("#cN").value, kind: $("#cK").value, dds_group: $("#cG").value, pnl_line: $("#cP").value, archived: 0 };
      await api(c.id ? "categories/" + c.id : "categories", { method: c.id ? "PUT" : "POST", body }); closeDrawer(); await loadMeta(); render(); };
    c.id && ($("#cX").onclick = async () => { await api("categories/" + c.id, { method: "DELETE", body: {} }); closeDrawer(); await loadMeta(); render(); });
  }
}

// ---------- Блок «Сегодня» на дашборде ----------
// сборочные задания WB FBS, которые ещё не ушли: новые, на сборке, собраны и ждут приёмки WB
function fbsCard(F) {
  if (F.access && F.access.startsWith("нет доступа")) return `<div class="kpi"><div class="t">WB FBS — не отправлено</div>
    <div class="p">Нет доступа: у токена WB нужна категория <b>«Маркетплейс»</b> (Профиль → Настройки → Доступ к API). Замените токен в Настройках.</div></div>`;
  if (!F.checked) return `<div class="kpi"><div class="t">WB FBS — не отправлено</div><div class="p">Загрузится при следующем обновлении заказов (кнопка «Обновить сейчас»).</div></div>`;
  const open = F.new + F.confirm, h = F.oldest_h, late = h !== undefined && h >= 24;
  return `<div class="kpi ${late ? "bad" : ""}"><div class="t" title="Сборочные задания из кабинета WB → Маркетплейс. Обновлено: ${esc(F.checked)}">WB FBS — не отправлено</div>
    <div class="v">${nf0.format(open)} <small>заданий</small></div>
    <div class="p sch"><strong>${nf0.format(F.new)}</strong> новые · <strong>${nf0.format(F.confirm)}</strong> на сборке</div>
    <div class="p sch"><strong>${nf0.format(F.waiting)}</strong> собраны, ждут приёмки WB</div>
    ${h !== undefined ? `<div class="p sch ${late ? "down" : ""}">самое старое — ${h < 1 ? "меньше часа" : nf0.format(Math.floor(h)) + " ч"} назад</div>` : ""}
    ${F.items.length ? `<div class="p sch muted" title="${esc(F.items.map(x => `${x.article}: новые ${x.new}, на сборке ${x.confirm}, ждут WB ${x.waiting}`).join("\n"))}">${F.items.slice(0, 3).map(x => esc(x.article) + " — " + (x.new + x.confirm + x.waiting)).join(", ")}${F.items.length > 3 ? "…" : ""}</div>` : ""}</div>`;
}

async function todayPanel() {
  const box = $("#todayBox"); if (!box) return;
  let T;
  try { T = await api("today?" + new URLSearchParams({ mp: state.mp, scheme: state.scheme || "" })); } catch (e) { box.innerHTML = `<div class="muted small">Заказы за сегодня недоступны: ${esc(e.message)}</div>`; return; }
  if (!box.isConnected) return;   // пока грузилось, страницу перерисовали (сменили фильтр)
  const t = T.totals, hm = T.now.slice(11, 16);
  const card = (title, c, p) => { const d = c.sum - p.sum, pc = p.sum ? d / p.sum * 100 : null;
    const cls = Math.abs(d) < 1 ? "flat" : d > 0 ? "up" : "down";
    return `<div class="kpi"><div class="t">${title}</div><div class="v">${rub(c.sum)} <small>/ ${nf0.format(c.qty)} шт</small></div>
      <div class="p">вчера к ${hm}: ${rub(p.sum)} <span class="delta ${cls}">${d > 0 ? "+" : ""}${rub(d)}${pc !== null ? ` (${d > 0 ? "+" : ""}${nf0.format(pc)}%)` : ""}</span></div>${title === "Wildberries" ? schLines() : ""}</div>`; };
  const schLines = () => [["FBO", "wb_fbo"], ["FBS", "wb_fbs"]].map(([n, k]) => { const c = t.today[k], p = t.yday_same[k], d = c.qty - p.qty;
    return `<div class="p sch"><b>${n}</b> ${nf0.format(c.qty)} шт · ${rub(c.sum)} <span class="muted">вчера ${nf0.format(p.qty)} шт</span>${d ? ` <span class="delta ${d > 0 ? "up" : "down"}">${d > 0 ? "+" : ""}${nf0.format(d)}</span>` : ""}</div>`; }).join("");
  const fl = T.filter, flName = [fl.mp === "wb" ? "Wildberries" : fl.mp === "ozon" ? "Ozon" : "", fl.scheme].filter(Boolean).join(" · ");
  const cards = !fl.mp && !fl.scheme ? [card("Все заказы", t.today.all, t.yday_same.all), card("Wildberries", t.today.wb, t.yday_same.wb), card("Ozon", t.today.ozon, t.yday_same.ozon)]
    : [card(fl.mp === "wb" && !fl.scheme ? "Wildberries" : "Заказы: " + flName, fl.mp === "wb" && !fl.scheme ? t.today.wb : t.today.all, fl.mp === "wb" && !fl.scheme ? t.yday_same.wb : t.yday_same.all)];
  if (T.fbs) cards.push(fbsCard(T.fbs));
  const jump = T.settings.jump_rub, big = jump && Math.abs(T.delta_sum) >= jump;
  box.innerHTML = `<h2>Сегодня, ${ruDate(T.today)} · ${hm}<span class="sp"></span>
      <span class="muted small" style="font-weight:400">заказы обновлены: ${esc(T.checked || "—")}</span>
      <button class="btn sm" id="tdUpd" style="margin-left:8px">Обновить сейчас</button></h2>
    ${big ? `<div class="notice warn" style="margin-bottom:10px">${T.delta_sum > 0 ? "Резкий рост" : "Резкое падение"} заказов: ${T.delta_sum > 0 ? "+" : ""}${rub(T.delta_sum)} к вчера на это время.
      ${T.delta_sum > 0 ? "Проверьте, не попал ли товар в акцию, и цены в «Контроле цен»." : ""}</div>` : ""}
    <div class="grid" style="grid-template-columns:repeat(${cards.length},minmax(0,1fr))">${cards.join("")}</div>
    <div class="two eq" style="margin-top:12px"><div><div class="muted small" style="margin-bottom:4px">Заказы нарастающим итогом по часам, ₽</div><div class="chart" style="height:190px"><canvas id="tdChart"></canvas></div></div>
      <div><div class="muted small" style="margin-bottom:4px">Больше всего заказов сегодня</div>
      ${T.top.length ? `<div class="tbl" style="max-height:190px"><table><thead><tr><th class="l"></th><th class="l">Артикул</th><th>Сегодня</th><th>Вчера к ${hm}</th></tr></thead><tbody>
        ${T.top.map(x => `<tr><td class="l">${x.mp === "wb" ? "WB" : "Ozon"}</td><td class="l">${esc(x.article)}</td><td><b>${rub(x.sum)}</b> <span class="muted">${nf0.format(x.qty)} шт${x.fbs_qty ? `, FBS ${nf0.format(x.fbs_qty)}` : ""}</span></td><td>${rub(x.y_sum)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Сегодня заказов пока нет</div>`}</div></div>
    <div class="muted small" style="margin-top:6px">Сумма — по цене до СПП, как колонка «Заказы». WB показывает заказы с задержкой до часа. Сигнал в виджете, если разница со вчера больше
      <input id="tdJump" type="number" step="10000" min="0" value="${jump}" style="width:100px;padding:2px 6px"> ₽.</div>`;
  const hrs = [...Array(24).keys()];
  charts.push(lineChart($("#tdChart", box), hrs.map(h => String(h).padStart(2, "0") + ":00"), [
    { label: "Сегодня", data: T.cum.today.map((v, h) => h <= T.hour_now ? v : null), borderColor: css(SERIES[0]), backgroundColor: css(SERIES[0]), borderWidth: 2, pointRadius: 0, tension: .2 },
    { label: "Вчера", data: T.cum.yday, borderColor: css("--muted"), backgroundColor: css("--muted"), borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, tension: .2 }], v => rub(v)));
  $("#tdUpd", box).onclick = async () => { await api("update?mode=today", { method: "POST" }); poll(); };
  $("#tdJump", box).onchange = async e => { await api("today", { method: "POST", body: { jump_rub: +e.target.value || 0 } }); };
}

// ---------- Месячный отчёт ----------
async function pageMonthly(root) {
  const sel = store.get("monthlyYm", "");
  const R = await api("monthly" + (sel ? "?ym=" + sel : ""));
  const T = ym => { const [y, m] = ym.split("-"); return MONTHS[+m - 1][0].toUpperCase() + MONTHS[+m - 1].slice(1) + " " + y; };
  $("#filters").innerHTML = `<div class="ctl"><label>Месяц <select id="mYm">${R.months.map(m => `<option value="${m}" ${m === R.ym ? "selected" : ""}>${T(m)}${m > R.default ? " (идёт / ждём отчёты)" : ""}</option>`).join("")}</select></label>
    <button class="btn" id="mPrint">Печать / PDF</button></div>`;
  $("#mYm").onchange = e => { store.set("monthlyYm", e.target.value === R.default ? "" : e.target.value); render(); };
  $("#mPrint").onclick = () => window.print();
  const wk = n => n === 1 ? "неделя" : n < 5 ? "недели" : "недель";
  const per = `${ruDate(R.from)} – ${ruDate(R.to)}, ${R.weeks.length} ${wk(R.weeks.length)}`;
  const pper = `${ruDate(R.prev.from)} – ${ruDate(R.prev.to)}, ${R.prev.weeks.length} ${wk(R.prev.weeks.length)}`;
  const dl = (d, good) => { if (d.pct === null || d.pct === undefined) return `<span class="muted">—</span>`;
    const up = d.pct > 0, ok = good === "down" ? !up : up; const cls = Math.abs(d.pct) < 0.5 ? "flat" : ok ? "up" : "down";
    return `<span class="delta ${cls}">${up ? "+" : ""}${nf1.format(d.pct)}%</span>`; };
  const money = v => rub(v), sh = v => v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + nf0.format(Math.round(v)) + "%";
  const artTable = (rows, empty) => rows.length ? `<div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Артикул</th><th>Заказы в нед., было</th><th>Стало</th><th>Изменение</th><th>%</th></tr></thead><tbody>
    ${rows.map(x => `<tr><td class="l" title="${esc(x.name)}">${esc(x.article)}</td><td>${rub(x.orders_w_prev)}</td><td>${rub(x.orders_w)}</td>
      <td class="${x.delta > 0 ? "up" : "down"}">${x.delta > 0 ? "+" : ""}${rub(x.delta)}</td><td>${sh(x.delta_pct)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">${empty}</div>`;
  root.innerHTML = `<div class="report">
    <div class="rep-head"><div><h2 style="margin:0">Отчёт за ${R.title.toLowerCase()}</h2>
      <div class="muted">${per} · сравнение с прошлым месяцем (${R.prev.title.toLowerCase()}: ${pper}) · сформирован ${esc(R.generated)}</div></div></div>
    ${R.notes.map(n => `<div class="notice warn">${esc(n)}</div>`).join("")}
    <div class="card"><h2>Главное</h2><ul class="hl">${R.highlights.map(h => `<li>${esc(h)}</li>`).join("")}</ul>
      <div class="muted small">В месяцах разное число недель (4 или 5), поэтому изменения считаются по средним за неделю.</div></div>
    <div class="panel"><h2>Показатели</h2><div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Показатель</th><th>${esc(R.title)}</th><th>${esc(R.prev.title)}</th><th>В неделю сейчас</th><th>В неделю было</th><th>Изменение</th></tr></thead><tbody>
      ${R.kpis.filter(k => M[k.key]).map(k => `<tr><td class="l">${M[k.key].t}</td><td><b>${M[k.key].f(k.cur)}</b></td><td>${M[k.key].f(k.prev)}</td>
        <td>${k.ratio ? "" : M[k.key].f(k.cur_w)}</td><td>${k.ratio ? "" : M[k.key].f(k.prev_w)}</td><td>${dl(k.delta, M[k.key].good)}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="two eq panel"><div class="card"><h2>По неделям</h2><div class="chart" style="height:260px"><canvas id="mWeeks"></canvas></div></div>
      <div class="card"><h2>Площадки</h2><div class="tbl" style="max-height:none"><table><thead><tr><th class="l"></th><th>Реализация</th><th>Доля</th><th>Заказы</th><th>Чист. прибыль</th><th>Маржа</th></tr></thead><tbody>
      ${R.mps.map(m => `<tr><td class="l"><b>${m.name}</b></td><td>${rub(m.cur.realization)}<div class="sub">было ${rub(m.prev.realization)}</div></td><td>${nf0.format(m.share)}%</td>
        <td>${rub(m.cur.orders_sum)}<div class="sub">было ${rub(m.prev.orders_sum)}</div></td><td>${rub(m.cur.profit)}<div class="sub">было ${rub(m.prev.profit)}</div></td>
        <td>${pct(m.cur.margin)}<div class="sub">было ${pct(m.prev.margin)}</div></td></tr>`).join("")}</tbody></table></div></div></div>
    <div class="two eq panel"><div class="card"><h2>Выросли заказы</h2>${artTable(R.grow, "Роста нет")}</div><div class="card"><h2>Упали заказы</h2>${artTable(R.fall, "Падения нет")}</div></div>
    <div class="two eq panel"><div class="card"><h2>Новые в продажах</h2>${artTable(R.new, "Новых товаров нет")}</div><div class="card"><h2>Перестали продаваться</h2>${artTable(R.gone, "Таких нет")}</div></div>
    <div class="panel card"><h2>Топ-10 по чистой прибыли</h2><div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Артикул</th><th>Реализация</th><th>Чист. прибыль</th><th>Было</th><th>Маржа</th></tr></thead><tbody>
      ${R.top_profit.map(x => `<tr><td class="l" title="${esc(x.name)}">${esc(x.article)}</td><td>${rub(x.realization)}</td><td><b>${rub(x.profit)}</b></td><td>${rub(x.profit_prev)}</td><td>${pct(x.margin)}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="panel card"><h2>Нет в наличии</h2>
      <p class="muted small">${R.oos_method === "stocks" ? "По ежедневным снимкам остатков: дни, когда остаток на площадке был 0, у товаров, которые продавались." :
        "Снимков остатков за этот месяц мало, поэтому аут-оф-сток определён косвенно: товар продавался в среднем хотя бы раз в день, а потом 3+ дня подряд не было ни одного заказа. С ноября программа хранит остатки каждый день — дальше отчёт будет точнее."}</p>
      ${R.oos.length ? `<div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Площадка</th><th class="l">Артикул</th><th>Дней подряд</th><th class="l">Период</th>${R.oos_method === "orders" ? "<th>Обычно заказов в день</th>" : ""}</tr></thead><tbody>
      ${R.oos.map(o => `<tr><td class="l">${o.mp === "wb" ? "WB" : "Ozon"}</td><td class="l">${esc(o.article)}</td><td><b>${o.days}</b></td><td class="l">${ruDate(o.from)} – ${ruDate(o.to)}</td>${R.oos_method === "orders" ? `<td>${nf1.format(o.prev_rate)}</td>` : ""}</tr>`).join("")}</tbody></table></div>` : `<div class="empty">Перебоев не найдено</div>`}</div>
    <div class="panel card"><h2>Продажи ниже МРЦ</h2>
      <p class="muted small">По каждому заказу месяца: цена, которую заплатил покупатель (на WB — уже со СПП), сравнивается с МРЦ${R.price_tolerance ? ` (допуск ${R.price_tolerance}%)` : ""}.</p>
      ${R.price_viol.length ? `<div class="tbl" style="max-height:none"><table><thead><tr><th class="l">Площадка</th><th class="l">Артикул</th><th>МРЦ</th><th>Заказов ниже МРЦ</th><th>из всех</th><th>Дней</th><th>Мин. цена</th><th>Мин. отклонение</th></tr></thead><tbody>
      ${R.price_viol.map(v => `<tr><td class="l">${v.mp === "wb" ? "WB" : "Ozon"}</td><td class="l">${esc(v.article)}</td><td>${rub(v.rrp)}</td><td><b>${nf0.format(v.below)}</b></td><td>${nf0.format(v.orders)} (${nf0.format(v.share)}%)</td><td>${v.days}</td><td>${rub(v.min)}</td><td class="down">${nf1.format(v.min_dev)}%</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Продаж ниже МРЦ не было</div>`}</div>
  </div>`;
  const css2 = v => css(v);
  charts.push(new Chart($("#mWeeks"), { type: "bar",
    data: { labels: R.weekly.map(w => `${ruDate(w.week).slice(0, 5)}–${ruDate(addDays(w.week, 6)).slice(0, 5)}`),
      datasets: [{ label: "Заказы", data: R.weekly.map(w => w.orders_sum), backgroundColor: css2(SERIES[0]) },
                 { label: "Реализация", data: R.weekly.map(w => w.realization), backgroundColor: css2(SERIES[2]) },
                 { label: "Чистая прибыль", data: R.weekly.map(w => w.profit), backgroundColor: css2(SERIES[3]) }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } },
      tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${rub(c.parsed.y)}` } } },
      scales: { x: { grid: { display: false } }, y: { ticks: { callback: v => nf0.format(v / 1e6) + " млн" } } } } }));
}

// ---------- Контроль цен ----------
// ссылки: карточка на сайте и кабинет продавца (шаблоны легко поправить, если маркетплейс сменит адреса)
const SHOP_URL = { wb: r => r.sku ? `https://www.wildberries.ru/catalog/${r.sku}/detail.aspx` : "",
                   ozon: r => r.sku ? `https://www.ozon.ru/product/${r.sku}/` : "" };
const CABINET_URL = { wb: r => "https://seller.wildberries.ru/discount-and-prices",
                      ozon: r => r.product_id ? `https://seller.ozon.ru/app/products/${r.product_id}/edit` : "https://seller.ozon.ru/app/products" };
function toast(msg) { const t = $("#tip"); t.textContent = msg; t.classList.remove("hidden"); t.style.cssText = "left:50%;top:18px;transform:translateX(-50%);position:fixed";
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.classList.add("hidden"); t.style.cssText = ""; }, 2600); }
async function pagePrices(root) {
  const cfg = store.get("prCfg", { mp: "", onlyRrp: true });
  $("#filters").innerHTML = `<div class="ctl">
    <div class="seg" id="prMp"><button data-v="">Все</button><button data-v="wb">WB</button><button data-v="ozon">Ozon</button></div>
    <label class="chk" style="margin:0 4px"><input type="checkbox" id="prOnly" ${cfg.onlyRrp ? "checked" : ""}> только с МРЦ</label>
    <button class="btn primary" id="prChk">Проверить сейчас</button><button class="btn" id="prImp">Загрузить МРЦ</button><button class="btn" id="prCsv">Экспорт CSV</button></div>`;
  $$("#prMp button").forEach(b => { b.classList.toggle("on", b.dataset.v === cfg.mp); b.onclick = () => { cfg.mp = b.dataset.v; store.set("prCfg", cfg); render(); }; });
  $("#prOnly").onchange = e => { cfg.onlyRrp = e.target.checked; store.set("prCfg", cfg); render(); };
  $("#prChk").onclick = async () => { await api("update?mode=prices", { method: "POST" }); poll(); };
  $("#prImp").onclick = () => importRrp();
  const R = await api("prices?" + new URLSearchParams({ mp: cfg.mp }));
  const S = R.settings, C = R.counts;
  const rows = R.rows.filter(r => !cfg.onlyRrp || r.rrp);
  const mpN = { wb: "WB", ozon: "Ozon" };
  const money = v => v ? nf0.format(Math.round(v)) + " ₽" : "—";
  const st = { low: ["cv-red", "ниже МРЦ"], near: ["cv-amb", "близко к МРЦ"], ok: ["", "в норме"], nodata: ["", "нет заказов"], nostock: ["cv-none", "нет в наличии"], norrp: ["", "МРЦ не задана"] };
  const ago = ts => { if (!ts) return "—"; const d = (Date.now() - new Date(ts.replace(" ", "T"))) / 36e5; return d < 1 ? "меньше часа назад" : d < 24 ? Math.round(d) + " ч назад" : ruDate(ts.slice(0, 10)); };
  root.innerHTML = `${R.rrp_count ? "" : `<div class="notice">Минимальные цены (МРЦ) ещё не загружены. Нажмите «Загрузить МРЦ» — можно вставить список «артикул цена» или загрузить Excel. Одну цену можно вписать прямо в таблице: щёлкните по ячейке «МРЦ».</div>`}
    ${R.wb_prices_access === "0" ? `<div class="notice">У токена WB нет доступа к разделу «Цены и скидки», поэтому ваша цена на WB (до СПП) берётся из последнего заказа. Цена для покупателя от этого не зависит.</div>` : ""}
    <div class="grid" style="margin-bottom:6px">
      <div class="kpi ${C.low ? "bad" : "good"}"><div class="t">Ниже МРЦ</div><div class="v">${C.low}</div><div class="p">${S.tolerance ? "больше чем на " + S.tolerance + "%" : "продаются дешевле минимальной цены"}</div></div>
      <div class="kpi"><div class="t">Близко к МРЦ</div><div class="v">${C.near}</div><div class="p">запас меньше ${S.warn}%</div></div>
      <div class="kpi"><div class="t">В норме</div><div class="v">${C.ok}</div>${C.nostock ? `<div class="p">ещё ${C.nostock} нет в наличии — не проверяются</div>` : ""}</div>
      <div class="kpi"><div class="t">Последняя проверка</div><div class="v" style="font-size:18px">${esc(R.checked || "—")}</div><div class="p">автоматически ночью и в 10:00, 14:00, 18:00</div></div></div>
    <div class="tbl" style="max-height:none"><table id="prTbl"><thead><tr><th class="l">Площадка</th><th class="l">Артикул</th><th title="Минимальная розничная цена — ниже продавать нельзя">МРЦ</th><th title="Ваша цена со скидкой продавца, до СПП">Ваша цена</th><th title="WB: обычная скидка WB за свой счёт (медиана по последним 10 заказам). Ozon: скидка за счёт Ozon по индексу цен">СПП / скидка Ozon</th><th title="WB: ваша цена × (1 − обычная СПП) — что видит обычный покупатель сейчас. Ozon: цена на сайте, оценка по индексу цен Ozon">Цена для покупателя</th><th>Отклонение</th><th title="Минимальная цена покупателя за последние ${S.hours} ч">Мин. за ${S.hours} ч</th><th class="l" title="Сколько заплатил последний покупатель — с его личными скидками">Последний заказ</th><th class="l">Статус</th></tr></thead><tbody>
    ${rows.map((r, i) => `<tr><td class="l">${mpN[r.mp]}</td><td class="l nowrap"><button class="pen" data-i="${i}" title="Открыть кабинет ${mpN[r.mp]} (артикул скопируется — вставьте его в поиск)">✎</button>${SHOP_URL[r.mp](r) ? `<a href="${SHOP_URL[r.mp](r)}" target="_blank" rel="noopener" title="${esc(r.name)} — открыть на сайте ${mpN[r.mp]}">${esc(r.article)}</a>` : `<span title="${esc(r.name)}">${esc(r.article)}</span>`}</td>
      <td class="rrp" data-a="${esc(r.article)}" title="Щёлкните, чтобы изменить">${money(r.rrp)}</td><td>${money(r.seller_price)}</td>
      <td>${r.spp !== null && r.spp !== undefined ? nf0.format(r.spp) + "%" : "—"}</td><td><b>${money(r.buyer_price)}</b>${r.mp === "ozon" ? (r.buyer_src === "similar" || r.buyer_src === "median" ? `<div class="muted small" title="У товара нет индекса цен Ozon. Скидка Ozon взята как у товаров ${r.buyer_src === "similar" ? "с близкой ценой" : "с индексом (медиана)"} — оценка, сверьте с сайтом.">оценка по похожим товарам</div>` : r.buyer_src === "index" ? `<div class="muted small" title="Ozon не отдаёт цену на сайте в API. Оценка по индексу цен Ozon — точность ±2–3%.">оценка, со скидкой Ozon</div>` : `<div class="muted small" title="Индекс цен Ozon по товару недоступен — показана ваша предельная цена. На сайте со скидкой за счёт Ozon цена может быть заметно ниже.">без скидки Ozon</div>`) : ""}</td>
      <td class="${st[r.status][0]}">${r.dev !== null && r.dev !== undefined ? (r.dev > 0 ? "+" : "") + nf1.format(r.dev) + "%" : "—"}</td>
      <td>${money(r.min_window)}</td><td class="l small nowrap">${r.last_paid ? money(r.last_paid) + " · " : ""}${ago(r.last_order)}${r.order_below ? `<div class="muted" title="Отдельный покупатель заплатил меньше МРЦ — у него личная скидка WB (кошелёк, персональная СПП). На витрине для всех цена выше.">заказ ниже МРЦ — личная скидка</div>` : ""}</td>
      <td class="l small">${st[r.status][1]}${r.reason ? ` — <span class="muted">${esc(r.reason)}</span>` : ""}</td></tr>`).join("") || `<tr><td class="l muted" colspan="10">Нет строк</td></tr>`}
    </tbody></table></div>
    <div class="card panel"><h2>Настройки</h2><div class="form" style="max-width:520px">
      <label>«Ниже МРЦ», если ниже больше чем на, %<input id="prTol" type="number" min="0" max="50" step="0.5" value="${S.tolerance}"></label>
      <label>«Близко к МРЦ», если запас меньше, %<input id="prWarn" type="number" min="0" max="50" step="0.5" value="${S.warn}"></label>
      <label>Окно для минимальной цены, часов<input id="prHrs" type="number" min="1" max="168" value="${S.hours}"></label></div>
      <div style="margin-top:8px"><button class="btn sm" id="prSet">Применить</button></div>
      <p class="muted small">Цена для покупателя на WB — ваша текущая цена из кабинета, уменьшенная на обычную СПП (медиана по последним 10 заказам). Отдельные покупатели платят меньше — у них личные скидки WB (кошелёк, персональная СПП); это видно в колонке «Последний заказ» и на МРЦ не влияет. На Ozon — текущая цена с акциями из API, а если её нет — из последнего заказа.
      Статус подсказывает, кто снизил цену: «ваша цена ниже МРЦ» — это настройка в кабинете; «СПП WB» — скидку даёт WB за свой счёт, поднять цену можно только через вашу цену.</p></div>`;
  $("#prSet").onclick = async () => { await api("prices/settings", { method: "POST", body: { tolerance: +$("#prTol").value, warn: +$("#prWarn").value, hours: +$("#prHrs").value } }); await loadMeta(); render(); };
  $("#prCsv").onclick = () => exportCsv("контроль_цен.csv", $("#prTbl"));
  $$("#prTbl .pen").forEach(b => b.onclick = () => {
    const r = rows[+b.dataset.i];
    const code = r.mp === "wb" ? (r.sku || r.article) : r.article;
    const ta = document.createElement("textarea"); ta.value = code; document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (e) { }
    ta.remove();
    toast(ok ? `Скопировано: ${code} — вставьте в поиск в кабинете` : `Артикул: ${code}`);
    window.open(CABINET_URL[r.mp](r), "_blank", "noopener");
  });
  $$("td.rrp").forEach(td => td.onclick = () => {
    if (td.querySelector("input")) return;
    const old = td.textContent.replace(/\D/g, "");
    td.innerHTML = `<input type="number" min="0" step="1" value="${old}" style="width:90px;text-align:right">`;
    const inp = td.querySelector("input"); inp.focus(); inp.select();
    const save = async () => { const v = inp.value.trim(); if (v === old) { render(); return; }
      await api("prices/rrp", { method: "POST", body: { rows: [{ article: td.dataset.a, price: v ? +v : 0 }] } }); await loadMeta(); render(); };
    inp.onkeydown = e => { if (e.key === "Enter") save(); if (e.key === "Escape") render(); };
    inp.onblur = save;
  });
  function importRrp() {
    openDrawer(`<h3>Минимальные цены (МРЦ)<button class="btn ghost" data-close>✕</button></h3>
      <p class="muted small">Вставьте список — по строке на артикул: «артикул цена» (можно через пробел, ; или Tab, например скопировать два столбца из Excel). Одна МРЦ действует на WB и Ozon.</p>
      <textarea id="rTxt" rows="10" style="width:100%;font:13px ui-monospace,Consolas,monospace" placeholder="106-M-518   3500&#10;104-M-518   3300"></textarea>
      <div class="muted small" style="margin:8px 0">…или загрузите Excel: столбец с артикулом и столбец «МРЦ» / «Цена».</div>
      <input type="file" id="rFile" accept=".xlsx">
      <label class="chk" style="margin-top:10px"><input type="checkbox" id="rRep"> заменить все МРЦ (удалить старые)</label>
      <div id="rErr" class="lg-err"></div>
      <div style="margin-top:12px"><button class="btn primary" id="rSave">Загрузить</button></div>`);
    $("#rSave").onclick = async () => {
      const body = { replace: $("#rRep").checked };
      const file = $("#rFile").files[0];
      if (file) body.file = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(",")[1]); fr.readAsDataURL(file); });
      else body.text = $("#rTxt").value;
      try { const r = await api("prices/rrp", { method: "POST", body }); closeDrawer(); alert("Загружено МРЦ: " + r.saved); await loadMeta(); render(); }
      catch (e) { $("#rErr").textContent = e.message; }
    };
  }
}

// ---------- Поставки ----------
// кабинеты: список поставок (номер копируется — вставьте его в поиск)
const SUPPLY_URL = { wb: "https://seller.wildberries.ru/supplies-management/all-supplies",
                     ozon: "https://seller.ozon.ru/app/supply/orders" };
const STAGE_NAME = { plan: "Готовится", way: "В пути / приёмка", done: "Принята", bad: "Отмена / отказ" };
async function pageSupplies(root) {
  const cfg = store.get("supCfg", { mp: "", f: "docs", q: "" });
  filterBar({ period: false, mp: false, articles: false, extra: `<div class="ctl">
    <div class="seg" id="spMp"><button data-v="">Все</button><button data-v="wb">WB</button><button data-v="ozon">Ozon</button></div>
    <div class="seg" id="spF"><button data-v="docs">Нужны документы</button><button data-v="way">В пути / приёмка</button><button data-v="plan">Готовятся</button><button data-v="done">Принятые</button><button data-v="bad">Отмены</button><button data-v="">Все</button></div>
    <input id="spQ" type="search" placeholder="№ поставки или склад" value="${esc(cfg.q)}" style="width:180px">
    <button class="btn primary" id="spUpd">Обновить статусы</button><button class="btn" id="spCsv">Экспорт CSV</button></div>` });
  $$("#spMp button").forEach(b => { b.classList.toggle("on", b.dataset.v === cfg.mp); b.onclick = () => { cfg.mp = b.dataset.v; store.set("supCfg", cfg); draw(); }; });
  $$("#spF button").forEach(b => { b.onclick = () => { cfg.f = b.dataset.v; store.set("supCfg", cfg); draw(); }; });
  $("#spQ").oninput = e => { cfg.q = e.target.value; store.set("supCfg", cfg); draw(); };
  $("#spUpd").onclick = async () => { await api("update?mode=supplies", { method: "POST" }); poll(); };
  const R = await api("supplies");
  const C = R.counts, mpN = { wb: "WB", ozon: "Ozon" };
  const dd = s => s ? ruDate(s.slice(0, 10)) + (s.length > 10 && s.slice(11, 16) !== "00:00" ? " " + s.slice(11, 16) : "") : "—";
  const d0 = s => s ? ruDate(s.slice(0, 10)) : "—";
  const n0 = v => v === null || v === undefined ? "—" : nf0.format(v);
  const noAcc = v => v && v.startsWith("нет доступа");
  const recentDone = R.rows.filter(r => r.stage === "done" && (r.fact || r.updated || "") >= addDays(today, -30)).length;
  root.innerHTML = `${!R.checked ? `<div class="notice">Поставки ещё не загружались. Нажмите «Обновить статусы» — дальше они обновляются сами: ночью и в 10:00, 14:00, 18:00.</div>` : ""}
    ${noAcc(R.wb_access) ? `<div class="notice warn">WB не отдаёт поставки: у токена нет категории <b>«Поставки»</b>. Создайте в кабинете WB (Профиль → Настройки → Доступ к API) токен «Только чтение» с категориями, что уже есть, плюс «Поставки», и вставьте его в <a href="#/config">Настройках</a>.</div>` : ""}
    ${noAcc(R.oz_access) ? `<div class="notice warn">Ozon не отдаёт заявки на поставку (${esc(R.oz_access)}). Проверьте, что у API-ключа Ozon есть роль с доступом к поставкам FBO (например, «Admin» или «Поставки»).</div>` : ""}
    <div class="grid" style="margin-bottom:6px">
      <div class="kpi ${C.docs_pending ? "bad" : "good"} sp-k" data-f="docs"><div class="t">Нужны документы</div><div class="v">${C.docs_pending}</div><div class="p">приняты, а акт и УПД не отмечены</div></div>
      <div class="kpi sp-k" data-f="way"><div class="t">В пути / на приёмке</div><div class="v">${C.way}</div></div>
      <div class="kpi sp-k" data-f="plan"><div class="t">Готовятся</div><div class="v">${C.plan}</div><div class="p">черновики, запланированы, ждут отгрузки</div></div>
      <div class="kpi sp-k" data-f="done"><div class="t">Принято за 30 дней</div><div class="v">${recentDone}</div><div class="p">проверено: ${esc(R.checked || "—")}</div></div></div>
    <div id="spBody"></div>
    <p class="muted small">«Принята» — WB: статус «Принято»; Ozon: «Принята — согласование актов» или «Завершена». После этого: скачайте акт приёма-передачи в кабинете,
      оформите УПД и отметьте галочки «Акт» и «УПД» — поставка уйдёт из списка «Нужны документы». Отметки видны всем пользователям.
      В «Нужны документы» попадают поставки, принятые начиная с ${ruDate(R.marks_from)}.</p>`;
  $$(".sp-k").forEach(k => { k.style.cursor = "pointer"; k.onclick = () => { cfg.f = k.dataset.f; store.set("supCfg", cfg); draw(); }; });
  $("#spCsv").onclick = () => exportCsv("поставки.csv", $("#spTbl"));
  function draw() {
    $$("#spF button").forEach(b => b.classList.toggle("on", b.dataset.v === cfg.f));
    $$("#spMp button").forEach(b => b.classList.toggle("on", b.dataset.v === cfg.mp));
    const q = cfg.q.trim().toLowerCase();
    const rows = R.rows.filter(r => (!cfg.mp || r.mp === cfg.mp)
      && (!cfg.f || (cfg.f === "docs" ? r.docs_pending : r.stage === cfg.f))
      && (!q || (r.number || "").toLowerCase().includes(q) || (r.warehouse || "").toLowerCase().includes(q)));
    $("#spBody").innerHTML = `<div class="tbl" style="max-height:none"><table id="spTbl"><thead><tr>
      <th class="l">МП</th><th class="l">№ поставки</th><th class="l">Склад</th><th class="l" title="Плановая дата / слот отгрузки">План</th>
      <th class="l" title="Дата приёмки (WB) или дата акта (Ozon)">Принята</th><th title="Сколько штук в поставке">Отправлено</th><th title="Сколько штук принял склад">Принято</th><th title="Принято минус отправлено">±</th>
      <th class="l">Статус</th><th class="c" title="Акт приёма-передачи скачан">Акт</th><th class="c" title="УПД оформлен">УПД</th><th class="l">Комментарий</th></tr></thead><tbody>
      ${rows.map((r, i) => { const diff = r.qty != null && r.accepted != null && r.stage === "done" ? r.accepted - r.qty : null;
        return `<tr class="${r.docs_pending ? "sp-pend" : ""}"><td class="l">${mpN[r.mp]}</td>
        <td class="l nowrap" title="Создана ${d0(r.created)}"><button class="pen" data-i="${i}" title="Открыть поставки в кабинете ${mpN[r.mp]} (номер скопируется)">✎</button>${esc(r.number)}</td>
        <td class="l">${esc(r.warehouse || "—")}</td><td class="l nowrap">${dd(r.planned)}</td>
        <td class="l nowrap">${r.stage === "done" ? d0(r.fact || r.updated) : "—"}</td>
        <td>${n0(r.qty)}</td><td>${r.stage === "done" || r.accepted ? n0(r.accepted) : "—"}</td>
        <td class="${diff ? "cv-red" : ""}">${!diff ? "" : diff > 0 ? "+" + nf0.format(diff) : nf0.format(diff)}</td>
        <td class="l sp-st"><span class="sb sb-${r.stage}">${esc(r.status)}</span>${r.note ? `<div class="muted small">${esc(r.note)}</div>` : ""}</td>
        <td class="c"><input type="checkbox" class="spm" data-i="${i}" data-k="act" ${r.act ? "checked" : ""}></td>
        <td class="c"><input type="checkbox" class="spm" data-i="${i}" data-k="upd" ${r.upd ? "checked" : ""}></td>
        <td class="l"><input class="spc" data-i="${i}" value="${esc(r.comment || "")}" placeholder="—" style="width:120px"></td></tr>`; }).join("")
        || `<tr><td class="l muted" colspan="12">${cfg.f === "docs" ? "Все принятые поставки с документами — делать ничего не нужно." : "Нет поставок"}</td></tr>`}
      </tbody></table></div>`;
    const mark = async (r, body) => { await api("supplies", { method: "POST", body: { mp: r.mp, supply_id: r.supply_id, ...body } });
      Object.assign(r, body); r.docs_pending = r.stage === "done" && !(r.act && r.upd) && (r.fact || r.updated || r.created || "") >= R.marks_from; };
    $$("#spTbl .spm").forEach(c => c.onchange = async () => { const r = rows[+c.dataset.i];
      try { await mark(r, { [c.dataset.k]: c.checked ? 1 : 0 }); toast(c.checked ? "Отмечено" : "Отметка снята"); await loadMeta(); applyAccess();
        C.docs_pending = R.rows.filter(x => x.docs_pending).length; $(".sp-k .v").textContent = C.docs_pending; }
      catch (e) { c.checked = !c.checked; toast("Не сохранилось: " + e.message); } });
    $$("#spTbl .spc").forEach(inp => { const save = async () => { const r = rows[+inp.dataset.i];
      if ((r.comment || "") === inp.value) return; try { await mark(r, { comment: inp.value }); toast("Комментарий сохранён"); } catch (e) { toast("Не сохранилось: " + e.message); } };
      inp.onblur = save; inp.onkeydown = e => { if (e.key === "Enter") inp.blur(); }; });
    $$("#spTbl .pen").forEach(b => b.onclick = () => { const r = rows[+b.dataset.i];
      const ta = document.createElement("textarea"); ta.value = r.number; document.body.appendChild(ta); ta.select();
      let ok = false; try { ok = document.execCommand("copy"); } catch (e) { } ta.remove();
      toast(ok ? `Скопирован номер ${r.number} — вставьте в поиск` : `№ ${r.number}`);
      window.open(SUPPLY_URL[r.mp], "_blank", "noopener"); });
  }
  draw();
}

// ---------- Настройки (config.ini из интерфейса, только администратор) ----------
async function pageConfig(root) {
  filterBar({ period: false, mp: false, articles: false });
  const C = await api("config");
  const groups = [["Магазин", ["shop"]], ["Ключи Wildberries", ["wb"]], ["Ключи Ozon", ["ozon"]], ["Налоги", ["tax"]],
    ["Google Таблица", ["gsheet"]], ["Сервер", ["server"]]];
  const fid = f => `cf_${f.section}_${f.key}`;
  const input = f => {
    if (f.type === "secret") return `<div class="cf-secret"><input id="${fid(f)}" type="password" autocomplete="new-password" placeholder="${f.is_set ? "сохранён " + esc(f.masked) + " · новый — заменит" : "не задан"}">
      ${f.is_set ? `<label class="cf-cb small muted"><input type="checkbox" data-clear="${f.section}.${f.key}"> удалить</label>` : ""}</div>`;
    if (f.type === "bool") return `<label class="cf-cb"><input id="${fid(f)}" type="checkbox" ${f.value === "1" ? "checked" : ""}> включено</label>`;
    if (f.type.startsWith("select:")) return `<select id="${fid(f)}">${f.type.slice(7).split("|").map(o => { const [v, t] = o.split("=");
      return `<option value="${v}" ${v === f.value ? "selected" : ""}>${esc(t)}</option>`; }).join("")}</select>`;
    return `<input id="${fid(f)}" value="${esc(f.value)}" ${f.type === "num" ? 'inputmode="decimal" style="width:120px"' : ""}>`;
  };
  const chk = C.checks;
  const chkHtml = !chk ? `<p class="muted small">Проверки ещё не было.</p>` : `
    <p class="muted small">Проверено ${esc(chk.time)}</p>
    ${chk.wb && chk.wb.length ? `<div class="cf-chk"><b>WB, основной ключ</b>${chk.wb_info && chk.wb_info.expires ? ` <span class="muted small">действует до ${esc(chk.wb_info.expires)}</span>` : ""}
      <div>${chk.wb.map(x => `<span class="pill ${x.ok ? "inc" : "exp"}" title="${x.ok ? "доступ есть" : "нет доступа (код " + x.code + ")"}">${x.ok ? "✓" : "✕"} ${esc(x.name)}</span>`).join(" ")}</div></div>` : ""}
    ${chk.wb_content ? `<div class="cf-chk"><b>WB, ключ для фото</b> <span class="pill ${chk.wb_content.ok ? "inc" : "exp"}">${chk.wb_content.ok ? "✓ Контент" : "✕ нет доступа (код " + chk.wb_content.code + ")"}</span>
      ${chk.wb_content.expires ? `<span class="muted small">действует до ${esc(chk.wb_content.expires)}</span>` : ""}</div>` : ""}
    ${chk.ozon ? `<div class="cf-chk"><b>Ozon</b> <span class="pill ${chk.ozon.ok ? "inc" : "exp"}">${chk.ozon.ok ? "✓ ключ работает" : "✕ ошибка (код " + chk.ozon.code + ")"}</span>
      ${chk.ozon.error ? `<div class="muted small">${esc(chk.ozon.error)}</div>` : ""}</div>` : ""}`;
  root.innerHTML = `<div class="two"><div>
    ${groups.map(([title, secs]) => `<div class="card panel"><h2>${title}</h2><div class="cf-form">
      ${C.fields.filter(f => secs.includes(f.section)).map(f => `<div class="cf-row"><label for="${fid(f)}">${esc(f.label)}</label>${input(f)}
        <div class="muted small">${esc(f.hint)}</div></div>`).join("")}</div></div>`).join("")}
    <div class="cf-save"><button class="btn primary" id="cfSave">Сохранить настройки</button> <span class="muted small" id="cfMsg"></span></div>
  </div><div>
    <div class="card"><h2>Проверка ключей<span class="sp"></span><button class="btn sm" id="cfCheck">Проверить</button></h2>
      <p class="muted small">Программа обращается к WB и Ozon с вашими ключами и показывает, к каким разделам API есть доступ. Красный раздел — у ключа нет этой категории: часть данных не загрузится. Выключите VPN перед проверкой.</p>
      <div id="cfChk">${chkHtml}</div></div>
    <div class="card panel"><h2>Как это хранится</h2>
      <p class="small">Все настройки лежат в файле <code>${esc(C.path)}</code>. Ключи показываются здесь только последними 4 символами и никуда не отправляются, кроме WB и Ozon. Раздел видит только администратор.</p>
      <p class="small muted">Перед каждым сохранением прошлая версия файла копируется в data\\config.ini.bak. Ключи и ставки налогов применяются со следующей загрузки данных; «Доступ из сети» и порт — после перезапуска программы.</p></div>
  </div></div>`;
  $("#cfSave").onclick = async () => {
    const values = {};
    C.fields.forEach(f => { const el = $("#" + fid(f)); if (!el) return;
      values[`${f.section}.${f.key}`] = f.type === "bool" ? (el.checked ? "1" : "0") : el.value; });
    $$("[data-clear]").forEach(c => { if (c.checked) values[c.dataset.clear] = "-"; });
    try { const r = await api("config", { method: "POST", body: { values } });
      if (r.error) { toast(r.error); return; }
      toast(r.changed.length ? `Сохранено: ${r.changed.length}` + (r.restart ? " — перезапустите программу" : "") : "Изменений нет");
      await loadMeta(); render(); } catch (e) { toast("Не сохранилось: " + e.message); }
  };
  $("#cfCheck").onclick = async () => { $("#cfCheck").disabled = true; $("#cfChk").innerHTML = `<p class="muted small">Проверяю… до 30 секунд</p>`;
    try { await api("config/check"); render(); } catch (e) { toast("Ошибка проверки: " + e.message); $("#cfCheck").disabled = false; } };
}

// ---------- Маркетинг → Фотоконтент ----------
const PH_LINK = { wb: nm => `https://www.wildberries.ru/catalog/${nm}/detail.aspx`, ozon: id => `https://www.ozon.ru/product/${id}/` };
const natSort = (a, b) => a.localeCompare(b, "ru", { numeric: true, sensitivity: "base" });
async function pagePhotos(root) {
  const cfg = store.get("phCfg", { mp: "wb", q: "" });
  filterBar({ period: false, mp: false, articles: false, extra: `<div class="ctl">
    <div class="seg" id="phMp"><button data-v="">Все</button><button data-v="wb">WB</button><button data-v="ozon">Ozon</button></div>
    <input id="phQ" type="search" placeholder="Артикул или название" value="${esc(cfg.q)}" style="width:200px">
    <button class="btn" id="phLoad">Обновить фото из кабинетов</button>
    <label class="btn" id="phBulkL" title="Папка с файлами вида АРТИКУЛ_1.jpg, АРТИКУЛ_2.jpg… или папки по артикулам с файлами 1.jpg, 2.jpg…">Загрузить папку…<input type="file" id="phBulk" webkitdirectory multiple hidden></label></div>` });
  let R = await api("media");
  if (!R.checked && !R.rows.length && !pagePhotos.tried) {   // первый вход: загрузить фото сразу (нужен только ключ на чтение)
    pagePhotos.tried = true;
    root.innerHTML = `<div class="notice">Загружаю фото карточек из кабинетов WB и Ozon… это до минуты.</div>`;
    try { const j = await api("media/load", { method: "POST" }); if (j.errors && j.errors.length) toast(j.errors.join("; ")); } catch (e) { toast(e.message); }
    R = await api("media");
  }
  const draw = () => {
    $$("#phMp button").forEach(b => b.classList.toggle("on", b.dataset.v === cfg.mp));
    const q = cfg.q.trim().toLowerCase();
    const rows = R.rows.filter(r => (!cfg.mp || r.mp === cfg.mp) && (!q || r.article.toLowerCase().includes(q) || (r.title || "").toLowerCase().includes(q)));
    root.innerHTML = `
      ${!R.rows.length ? `<div class="notice">Фото ещё не загружались. Нажмите «Обновить фото из кабинетов» (VPN выключен).</div>` : ""}
      ${R.error ? `<div class="notice warn">${esc(R.error)}</div>` : ""}
      ${!R.write_key ? `<div class="notice">Для замены фото на WB нужен ключ с категорией «Контент» <b>без</b> «только чтение». Добавьте его в <a href="#/config">Настройках</a> (поле «WB: ключ для изменения фото»). Без него можно только смотреть.</div>` : ""}
      <p class="muted small">Чтобы заменить одно фото — кнопка «Заменить» под ним (или перетащите файл на фото). Оно встанет на то же место; номера сверху — позиция фото в карточке, 1 — главное. «Добавить» — фото в конец. Нажмите на фото — откроется в полном размере.
        Перед заменой текущие фото карточки сохраняются в копию — кнопка «Откатить» вернёт их. Ozon — пока только просмотр: замена появится после переезда на сервер.
        ${R.checked ? `Фото загружены ${esc(R.checked)}.` : ""}</p>
      <div class="ph-list">${rows.length ? `<div class="ph-head"><div class="ph-info muted small">Артикул</div><div class="ph-tiles">${Array.from({ length: Math.max(...rows.map(r => r.photos.length + (r.mp === "wb" && R.write_key ? 1 : 0)), 1) },
          (_, i) => `<div class="ph-hn">${i + 1}</div>`).join("")}</div></div>` : ""}
        ${rows.map(r => rowHtml(r)).join("") || `<div class="muted">Ничего не найдено</div>`}</div>
      ${R.log.length ? `<div class="card panel"><h2>Журнал изменений</h2><div class="tbl" style="max-height:260px"><table><tr><th class="l">Когда</th><th class="l">Кто</th><th class="l">Артикул</th><th class="l">Действие</th><th class="l">Подробности</th></tr>
        ${R.log.map(l => `<tr class="${l.ok ? "" : "cv-red"}"><td class="l nowrap">${esc(l.ts.slice(0, 16))}</td><td class="l">${esc(l.user || "")}</td><td class="l">${esc(l.article || l.nm_id)}</td><td class="l">${esc(l.action)}</td><td class="l small">${esc(l.detail || "")}</td></tr>`).join("")}</table></div></div>` : ""}`;
    bind(rows);
  };
  const rowHtml = r => {
    const wb = r.mp === "wb", can = wb;   // кнопки видны всегда; без ключа записи подскажем, где его добавить
    return `<div class="ph-row" data-key="${r.mp}|${esc(r.article)}">
      <div class="ph-info"><b>${esc(r.article)}</b><span class="pill ${wb ? "wb" : "oz"}">${wb ? "WB" : "Ozon"}</span>
        <div class="muted small ph-title" title="${esc(r.title || "")}">${esc(r.title || "")}</div>
        <div class="muted small">${r.photos.length} фото · <a href="${PH_LINK[r.mp](r.nm_id)}" target="_blank" rel="noopener">на сайте</a></div>
        ${wb ? `<div class="ph-act"><label class="btn sm">Заменить все…<input type="file" class="ph-all" accept="image/*" multiple hidden></label>
          ${r.backups.length ? `<button class="btn sm ph-undo" title="Вернуть фото из копии от ${esc(fmtTs(r.backups[0].ts))}">Откатить</button>` : ""}</div>` : ""}</div>
      <div class="ph-tiles">${r.photos.map((p, i) => `<div class="ph-cell"><div class="ph-tile ${can ? "can" : ""}" data-n="${i + 1}" title="${can ? "Нажмите или перетащите файл, чтобы заменить фото " + (i + 1) : "Фото " + (i + 1)}">
          <a class="ph-zoom" href="${esc(p.big || p.small)}" target="_blank" rel="noopener" title="Открыть в полном размере" onclick="event.stopPropagation()"><img loading="lazy" src="${esc(p.small)}" alt=""></a><span class="ph-n">${i + 1}</span></div>
          ${can ? `<button class="btn xs ph-one" data-n="${i + 1}" title="Заменить только фото ${i + 1}">Заменить</button>` : ""}</div>`).join("")}
        ${can ? `<div class="ph-cell"><div class="ph-tile add can" data-n="${r.photos.length + 1}" title="Добавить фото в конец"><span>+</span></div>
          <button class="btn xs ph-one" data-n="${r.photos.length + 1}">Добавить</button></div>` : ""}</div></div>`;
  };
  const fmtTs = ts => ts ? `${ts.slice(6, 8)}.${ts.slice(4, 6)} ${ts.slice(9, 11)}:${ts.slice(11, 13)}` : "";
  const find = el => { const [mp, ...a] = el.closest(".ph-row").dataset.key.split("|"); return R.rows.find(x => x.mp === mp && x.article === a.join("|")); };
  const pick = (multiple) => new Promise(res => { const i = document.createElement("input"); i.type = "file"; i.accept = "image/*"; i.multiple = multiple;
    i.onchange = () => res([...i.files]); i.click(); });
  async function upload(r, n, file) {
    const res = await fetch(`/api/media/upload?nm=${encodeURIComponent(r.nm_id)}&n=${n}`, { method: "POST", body: file,
      headers: { "Content-Type": file.type || "image/jpeg", "X-Filename": encodeURIComponent(file.name) } });
    const j = await res.json(); if (j.error) throw new Error(j.error); return j;
  }
  async function refresh(r, waitMs = 4000) {
    await new Promise(z => setTimeout(z, waitMs));
    try { const j = await api(`media/refresh?nm=${encodeURIComponent(r.nm_id)}`, { method: "POST" }); if (j.photos) r.photos = j.photos; } catch (e) { }
    R = await api("media"); draw();
  }
  function confirmReplace(r, n, files) {
    return new Promise(res => {
      const old = r.photos[n - 1];
      openDrawer(`<h3>${esc(r.article)} — ${files.length > 1 ? `заменить все фото (${files.length})` : n > r.photos.length ? "добавить фото" : "заменить фото " + n}<button class="btn ghost" data-close>✕</button></h3>
        <div class="ph-cmp">${files.length === 1 ? `${old ? `<div><div class="muted small">Сейчас</div><img src="${esc(old.small)}"></div><div class="ph-arrow">→</div>` : ""}
          <div><div class="muted small">Будет</div><img id="phNew"></div>` : `<div class="ph-tiles">${files.map((f, i) => `<div class="ph-tile"><img data-i="${i}"><span class="ph-n">${i + 1}</span></div>`).join("")}</div>`}</div>
        ${files.length > 1 && r.photos.length > files.length ? `<label class="small"><input type="checkbox" id="phTrim" checked> удалить старые фото ${files.length + 1}–${r.photos.length} (сейчас их ${r.photos.length})</label>` : ""}
        <p class="muted small">Текущие фото карточки сохранятся в копию — можно будет откатить. Изменение видно на WB через несколько минут.</p>
        <div class="row" style="gap:8px;margin-top:10px"><button class="btn primary" id="phGo">Заменить</button><button class="btn" data-close>Отмена</button></div>`);
      const urls = files.map(f => URL.createObjectURL(f));
      if (files.length === 1) $("#phNew").src = urls[0]; else $$("#drawer img[data-i]").forEach(im => im.src = urls[+im.dataset.i]);
      $("#phGo").onclick = () => { const trim = $("#phTrim") ? $("#phTrim").checked : false; closeDrawer(); res({ ok: true, trim }); };
      $$("#drawer [data-close]").forEach(b => b.addEventListener("click", () => res({ ok: false })));
    });
  }
  async function replaceAll(r, files, trim, quiet) {
    files = files.slice().sort((a, b) => natSort(a.name, b.name));
    for (let i = 0; i < files.length; i++) {
      if (!quiet) toast(`${r.article}: загружаю фото ${i + 1} из ${files.length}…`);
      await upload(r, i + 1, files[i]);
      await new Promise(z => setTimeout(z, 700));
    }
    if (trim && r.photos.length > files.length) {
      await new Promise(z => setTimeout(z, 5000));
      const j = await api(`media/keep?nm=${encodeURIComponent(r.nm_id)}&k=${files.length}`, { method: "POST" });
      if (j.error) throw new Error(j.error);
    }
  }
  function needKey() {
    openDrawer(`<h3>Нужен ключ WB для изменения фото<button class="btn ghost" data-close>✕</button></h3>
      <p>Чтобы менять фото из программы, WB требует отдельный токен с правом записи — ключ «только чтение» фото менять не может.</p>
      <ol class="small"><li>Кабинет WB → Профиль → Настройки → <b>Доступ к API</b> → «Создать токен».</li>
        <li>Тип «Базовый», категория <b>«Контент»</b>, галочку <b>«Только на чтение» не ставить</b>.</li>
        <li>Скопируйте токен (WB показывает его один раз).</li>
        <li>В программе: <b>Прочее → Настройки → «WB: ключ для изменения фото»</b> — вставьте и нажмите «Сохранить настройки», затем «Проверить».</li></ol>
      <div class="row" style="gap:8px;margin-top:10px"><a class="btn primary" href="#/config" data-close>Открыть Настройки</a><button class="btn" data-close>Закрыть</button></div>`);
  }
  function bind(rows) {
    $$(".ph-tile.can").forEach(t => {
      const go = async files => { const r = find(t), n = +t.dataset.n; if (!files.length) return;
        if (!R.write_key) { needKey(); return; }
        const c = await confirmReplace(r, n, [files[0]]); if (!c.ok) return;
        try { toast("Загружаю…"); await upload(r, n, files[0]); toast("Фото отправлено в WB, обновляю карточку…"); await refresh(r); toast("Готово"); }
        catch (e) { toast(e.message); R = await api("media"); draw(); } };
      t.onclick = async () => { if (!R.write_key) return needKey(); go(await pick(false)); };
      const btn = t.parentElement.querySelector(".ph-one"); if (btn) btn.onclick = async () => { if (!R.write_key) return needKey(); go(await pick(false)); };
      t.ondragover = e => { e.preventDefault(); t.classList.add("drop"); };
      t.ondragleave = () => t.classList.remove("drop");
      t.ondrop = e => { e.preventDefault(); t.classList.remove("drop"); go([...e.dataTransfer.files].filter(f => f.type.startsWith("image/"))); };
    });
    $$(".ph-all").forEach(inp => inp.closest("label").addEventListener("click", e => { if (!R.write_key) { e.preventDefault(); needKey(); } }));
    $$(".ph-all").forEach(inp => inp.onchange = async () => { const r = find(inp), files = [...inp.files]; inp.value = ""; if (!files.length) return;
      const c = await confirmReplace(r, 1, files.sort((a, b) => natSort(a.name, b.name))); if (!c.ok) return;
      try { await replaceAll(r, files, c.trim); toast("Готово, обновляю карточку…"); await refresh(r, 3000); }
      catch (e) { toast(e.message); R = await api("media"); draw(); } });
    $$(".ph-undo").forEach(b => b.onclick = async () => { const r = find(b), bk = r.backups[0];
      if (!confirm(`Вернуть фото ${r.article} из копии от ${fmtTs(bk.ts)} (${bk.count} фото)? Текущие фото тоже сохранятся в копию.`)) return;
      try { toast("Возвращаю фото…"); const j = await api(`media/restore?nm=${encodeURIComponent(r.nm_id)}&ts=${encodeURIComponent(bk.ts)}`, { method: "POST" });
        if (j.error) throw new Error(j.error); await refresh(r, 3000); toast("Фото возвращены"); } catch (e) { toast(e.message); } });
  }
  $$("#phMp button").forEach(b => b.onclick = () => { cfg.mp = b.dataset.v; store.set("phCfg", cfg); draw(); });
  $("#phQ").oninput = e => { cfg.q = e.target.value; store.set("phCfg", cfg); draw(); };
  $("#phLoad").onclick = async () => { $("#phLoad").disabled = true; toast("Загружаю фото из кабинетов…");
    try { const j = await api("media/load", { method: "POST" }); if (j.errors && j.errors.length) toast(j.errors.join("; ")); R = await api("media"); draw(); }
    catch (e) { toast(e.message); } $("#phLoad").disabled = false; };
  // массовая загрузка: АРТИКУЛ_1.jpg … или папка АРТИКУЛ/1.jpg …
  $("#phBulk").onchange = async () => {
    const files = [...$("#phBulk").files].filter(f => /\.(jpe?g|png|webp)$/i.test(f.name)); $("#phBulk").value = "";
    const byArt = {};
    files.forEach(f => { const parts = (f.webkitRelativePath || f.name).split("/"); let art = null, n = null;
      const m = parts[parts.length - 1].match(/^(.+?)[_\s-]+(\d{1,2})\.[a-z]+$/i);
      if (m) { art = m[1]; n = +m[2]; } else if (parts.length >= 2 && /^\d{1,2}\.[a-z]+$/i.test(parts[parts.length - 1])) { art = parts[parts.length - 2]; n = parseInt(parts[parts.length - 1]); }
      if (art) (byArt[art.toLowerCase()] = byArt[art.toLowerCase()] || []).push({ f, n }); });
    const plan = Object.entries(byArt).map(([a, list]) => ({ a, list: list.sort((x, y) => x.n - y.n), r: R.rows.find(x => x.mp === "wb" && x.article.toLowerCase() === a) }));
    if (!plan.length) { toast("Не нашёл файлов вида АРТИКУЛ_1.jpg или папок по артикулам"); return; }
    openDrawer(`<h3>Массовая замена фото WB<button class="btn ghost" data-close>✕</button></h3>
      <p class="small">Найдено ${files.length} файлов для ${plan.length} артикулов. Фото каждой карточки заменятся по порядку номеров в именах файлов.</p>
      <div class="tbl" style="max-height:340px"><table><tr><th class="l">Артикул</th><th>Новых фото</th><th>Сейчас</th><th class="l">Статус</th></tr>
      ${plan.map((p, i) => `<tr><td class="l">${esc(p.r ? p.r.article : p.a)}</td><td>${p.list.length}</td><td>${p.r ? p.r.photos.length : "—"}</td>
        <td class="l small" id="bk${i}">${p.r ? "ждёт" : '<span class="cv-red">нет такого артикула на WB — пропущу</span>'}</td></tr>`).join("")}</table></div>
      <label class="small"><input type="checkbox" id="bkTrim" checked> удалять старые лишние фото, если новых меньше</label>
      <div class="row" style="gap:8px;margin-top:10px"><button class="btn primary" id="bkGo">Заменить фото у ${plan.filter(p => p.r).length} карточек</button><button class="btn" data-close>Отмена</button></div>`);
    $("#bkGo").onclick = async () => { $("#bkGo").disabled = true; const trim = $("#bkTrim").checked;
      for (let i = 0; i < plan.length; i++) { const p = plan[i]; if (!p.r) continue; const cell = $("#bk" + i);
        cell.textContent = "загружаю…";
        try { await replaceAll(p.r, p.list.map(x => x.f), trim, true); cell.innerHTML = '<span class="cv-green">готово</span>'; }
        catch (e) { cell.innerHTML = `<span class="cv-red">${esc(e.message)}</span>`; } }
      toast("Массовая замена закончена, обновляю фото…"); await api("media/load", { method: "POST" }); R = await api("media"); draw(); };
  };
  draw();
}

// ---------- Маркетинг → Акции ----------
async function pagePromos(root) {
  const cfg = store.get("pmCfg", { mp: "", f: "", q: "", svc: false });
  filterBar({ period: false, mp: false, articles: false, extra: `<div class="ctl">
    <div class="seg" id="pmMp"><button data-v="">Все</button><button data-v="wb">WB</button><button data-v="ozon">Ozon</button></div>
    <div class="seg" id="pmF"><button data-v="">Все товары</button><button data-v="in">В акциях</button><button data-v="out">Без акций</button></div>
    <input id="pmQ" type="search" placeholder="Артикул или акция" value="${esc(cfg.q)}" style="width:170px">
    <label title="Рассрочка, кредит, баллы, семплинг — программы Ozon, а не скидки для покупателя"><input type="checkbox" id="pmSvc" ${cfg.svc ? "checked" : ""}> служебные Ozon</label>
    <button class="btn primary" id="pmUpd">Обновить акции</button></div>` });
  const R = await api("promos?seen=1");
  if (META.promo_alerts) loadMeta();   // отметили просмотренным — убрать красную точку «новое»
  if (!cfg.sort) cfg.sort = { k: "promo", d: -1 };
  const nowS = new Date(Date.now() + 3 * 3600e3).toISOString().slice(0, 16).replace("T", " ");
  const dshort = d => d ? `${d.slice(8, 10)}.${d.slice(5, 7)}` : "";
  const vis = p => cfg.svc || p.kind !== "service";
  const chip = (p, mp) => { const soon = p.date_from && p.date_from > nowS;
    const tip = [p.name, `${p.date_from ? "с " + p.date_from : ""} ${p.date_to ? "по " + p.date_to : ""}`.trim(),
      mp === "wb" && p.price ? `цена в акции ${nf0.format(p.price)} ₽${p.plan_price ? ", плановая " + nf0.format(p.plan_price) + " ₽" : ""}` : "",
      mp === "wb" && p.discount ? `скидка ${p.discount}%${p.plan_discount ? " (план " + p.plan_discount + "%)" : ""}` : "",
      mp === "ozon" && p.discount ? `значение: ${p.discount}` : ""].filter(Boolean).join("\n");
    return `<span class="pm-chip ${mp} ${soon ? "soon" : ""} ${p.kind === "service" ? "svc" : ""} ${p.new ? "new" : ""}" title="${esc((p.new ? "НОВОЕ: товар попал в акцию " + (p.first_seen || "").slice(0, 16) + "\n" : "") + tip)}">${p.new ? "<b>новое</b>" : ""}${esc(p.name)}<small>${soon ? "с " + dshort(p.date_from) : p.date_to ? "до " + dshort(p.date_to) : ""}</small></span>`; };
  const cnt = mp => R.rows.filter(r => r[mp].some(vis)).length;
  const draw = () => {
    $$("#pmMp button").forEach(b => b.classList.toggle("on", b.dataset.v === cfg.mp));
    $$("#pmF button").forEach(b => b.classList.toggle("on", b.dataset.v === cfg.f));
    const q = cfg.q.trim().toLowerCase();
    const mps = cfg.mp ? [cfg.mp] : ["wb", "ozon"];
    const rows = R.rows.filter(r => mps.some(m => r.has[m] || r[m].length)).filter(r => {
      const any = mps.some(m => r[m].some(vis));
      if (cfg.f === "in" && !any) return false;
      if (cfg.f === "out" && any) return false;
      return !q || r.article.toLowerCase().includes(q) || mps.some(m => r[m].some(p => vis(p) && p.name.toLowerCase().includes(q)));
    });
    const sv = { art: r => r.article.toLowerCase(), wb_st: r => r.stock.wb ?? -1, oz_st: r => r.stock.ozon ?? -1,
      wb_n: r => r.wb.filter(vis).length, oz_n: r => r.ozon.filter(vis).length,
      promo: r => mps.reduce((a, m) => a + r[m].filter(vis).length * 10 + r[m].filter(p => p.new).length * 1000, 0) };
    const S = cfg.sort, f = sv[S.k] || sv.promo;
    rows.sort((a, b) => { const x = f(a), y = f(b); return (x < y ? -1 : x > y ? 1 : 0) * S.d || a.article.localeCompare(b.article, "ru", { numeric: true }); });
    const th = (k, t, cls = "") => `<th class="${cls} pm-sort" data-k="${k}" title="Сортировать">${t}${S.k === k ? (S.d > 0 ? " ▲" : " ▼") : ""}</th>`;
    const wbList = R.promos.filter(p => p.mp === "wb");
    $("#pmBody").innerHTML = `<div class="tbl" style="max-height:none"><table id="pmTbl"><thead><tr>${th("art", "Артикул", "l")}
      ${mps.map(m => th(m === "wb" ? "wb_st" : "oz_st", "Остаток " + (m === "wb" ? "WB" : "Ozon"))).join("")}
      ${mps.map(m => th(m === "wb" ? "wb_n" : "oz_n", m === "wb" ? "Акции WB" : "Акции Ozon", "l")).join("")}</tr></thead><tbody>
      ${rows.map(r => `<tr><td class="l nowrap"><b>${esc(r.article)}</b></td>
        ${mps.map(m => `<td>${r.stock[m] === null || r.stock[m] === undefined ? "—" : nf0.format(r.stock[m])}</td>`).join("")}
        ${mps.map(m => { const ps = r[m].filter(vis); return `<td class="l ${ps.some(p => p.new) ? "pm-new" : ps.some(p => p.kind !== "service") ? "pm-has" : ""}">${ps.length ? ps.map(p => chip(p, m)).join("") : `<span class="muted small">${r.has[m] ? "нет акций" : "—"}</span>`}</td>`; }).join("")}</tr>`).join("")
        || `<tr><td class="l muted" colspan="5">Ничего не найдено</td></tr>`}</tbody></table></div>
      ${(!cfg.mp || cfg.mp === "wb") && wbList.length ? `<div class="card panel"><h2>Акции WB на ближайший месяц</h2>
        <div class="tbl" style="max-height:360px"><table><tr><th class="l">Акция</th><th class="l">Период</th><th>Ваших товаров</th><th class="l">Примечание</th></tr>
        ${wbList.map(p => `<tr><td class="l">${esc(p.name)}${p.kind === "auto" ? ' <span class="pill">авто</span>' : ""}</td><td class="l nowrap">${dshort(p.date_from)} – ${dshort(p.date_to)}</td>
          <td>${p.kind === "auto" ? "—" : nf0.format(p.in_count)}</td><td class="l small muted">${esc(p.note || "")}</td></tr>`).join("")}</table></div></div>` : ""}`;
  };
  root.innerHTML = `
    ${R.wb_error ? `<div class="notice warn">WB акции: ${esc(R.wb_error)}</div>` : ""}
    ${!R.wb_checked && !R.oz_checked ? `<div class="notice">Акции ещё не загружались. Нажмите «Обновить акции» (VPN выключен). Дальше они обновляются сами ночью и в 10:00, 14:00, 18:00.</div>` : ""}
    <div class="grid" style="margin-bottom:10px">
      <div class="kpi"><div class="t">WB: товаров в акциях</div><div class="v">${cnt("wb")}</div><div class="p">проверено ${esc(R.wb_checked || "—")}</div></div>
      <div class="kpi"><div class="t">Ozon: товаров в акциях</div><div class="v">${cnt("ozon")}</div><div class="p">проверено ${esc(R.oz_checked || "—")}</div></div>
      <div class="kpi"><div class="t">Без акций (есть остаток)</div><div class="v">${R.rows.filter(r => ["wb", "ozon"].some(m => (r.stock[m] || 0) > 0 && !r[m].some(vis))).length}</div><div class="p">на WB или Ozon</div></div></div>
    <div id="pmBody"></div>
    <p class="muted small">Ячейка подсвечена — товар в акции; ярко-жёлтая с меткой «новое» — попал в акцию с вашего прошлого просмотра (красная точка у «Акций» в меню). Заголовки столбцов сортируют таблицу. Наведите мышь на акцию — увидите даты, цену и скидку. «с 11.11» — акция начнётся, товар уже добавлен. У автоакций WB состав участников через API не виден.
      Служебные программы Ozon (рассрочка, кредит, баллы, семплинг) скрыты — включите «служебные Ozon», чтобы их показать.</p>`;
  $("#pmBody").addEventListener("click", e => { const h = e.target.closest(".pm-sort"); if (!h) return;
    cfg.sort = cfg.sort.k === h.dataset.k ? { k: h.dataset.k, d: -cfg.sort.d } : { k: h.dataset.k, d: h.dataset.k === "art" ? 1 : -1 };
    store.set("pmCfg", cfg); draw(); });
  $$("#pmMp button").forEach(b => b.onclick = () => { cfg.mp = b.dataset.v; store.set("pmCfg", cfg); draw(); });
  $$("#pmF button").forEach(b => b.onclick = () => { cfg.f = b.dataset.v; store.set("pmCfg", cfg); draw(); });
  $("#pmQ").oninput = e => { cfg.q = e.target.value; store.set("pmCfg", cfg); draw(); };
  $("#pmSvc").onchange = e => { cfg.svc = e.target.checked; store.set("pmCfg", cfg); render(); };
  $("#pmUpd").onclick = async () => { await api("update?mode=promos", { method: "POST" }); poll(); };
  draw();
}

// ---------- Инструкции ----------
async function pageHelp(root) {
  filterBar({ period: false, mp: false, articles: false });
  const r = await fetch("/help.html", { cache: "no-cache" });
  root.innerHTML = await r.text();
  $$(".help-toc a").forEach(a => a.onclick = e => { e.preventDefault(); document.getElementById(a.dataset.to).scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" }); });
}

// ---------- Пользователи ----------
async function pageUsers(root) {
  filterBar({ period: false, mp: false, articles: false });
  const a = AUTH(), users = await api("users");
  const names = a.page_names || {};
  const pg = u => u.role === "admin" ? "все разделы" : (u.pages.map(p => names[p] || p).join(", ") || "—");
  const first = users.length === 0;
  root.innerHTML = `${!first ? "" : `<div class="notice">Пока нет ни одного пользователя, поэтому дашборд открывается без пароля. Сначала создайте себя — с ролью <b>Администратор</b>. После этого при каждом входе будут спрашивать телефон и пароль.</div>`}
    <div class="card"><h2>Пользователи<span class="sp"></span><button class="btn sm primary" id="uAdd">Добавить пользователя</button></h2>
    <div class="tbl" style="max-height:none"><table><tr><th class="l">Имя</th><th class="l">Телефон</th><th class="l">Роль</th><th class="l">Разделы</th><th class="l">Последний вход</th><th></th></tr>
    ${users.map(u => `<tr data-id="${u.id}" class="${u.active ? "" : "muted"}"><td class="l">${esc(u.name || "")}${u.active ? "" : " (отключён)"}</td><td class="l">+${esc(u.phone)}</td>
      <td class="l"><span class="pill ${u.role === "admin" ? "inc" : ""}">${u.role === "admin" ? "администратор" : "сотрудник"}</span></td><td class="l">${esc(pg(u))}</td>
      <td class="l">${u.last_login ? esc(u.last_login) : "—"}</td><td><button class="btn sm" data-u>Изменить</button></td></tr>`).join("") || `<tr><td class="l muted" colspan="6">Пользователей нет</td></tr>`}</table></div></div>
    <div class="card panel"><h2>Как это работает</h2><p class="muted small">Сотрудник входит по своему номеру телефона и паролю и видит только отмеченные разделы — остальные скрыты в меню и закрыты на сервере.
    Администратор видит всё и управляет пользователями. Забытый пароль администратор задаёт заново в карточке пользователя. Отключённый пользователь сразу теряет доступ.</p></div>`;
  $("#uAdd").onclick = () => form();
  $$("[data-u]").forEach(b => b.onclick = () => form(users.find(u => u.id == b.closest("tr").dataset.id)));
  function form(u) {
    const isNew = !u;
    u = u || { name: "", phone: "", role: first ? "admin" : "user", pages: ["wh_ozon", "wh_wb"], active: 1 };
    const pages = Object.keys(names);
    openDrawer(`<h3>${isNew ? "Новый пользователь" : "Пользователь"}<button class="btn ghost" data-close>✕</button></h3><div class="form">
      <label class="full">Имя<input id="uN" value="${esc(u.name || "")}" placeholder="Например, Мария — склад"></label>
      <label>Телефон<input id="uP" type="tel" value="${u.phone ? "+" + esc(u.phone) : ""}" placeholder="+7 900 000-00-00"></label>
      <label>${isNew ? "Пароль" : "Новый пароль"}<input id="uW" type="text" autocomplete="new-password" placeholder="${isNew ? "не короче 6 символов" : "оставьте пустым, чтобы не менять"}"></label>
      <label class="full">Роль<select id="uR"><option value="user" ${u.role !== "admin" ? "selected" : ""}>Сотрудник — только выбранные разделы</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>Администратор — все разделы и пользователи</option></select></label>
      <div class="full" id="uPg"><div class="muted small" style="margin-bottom:6px">Разделы, которые увидит сотрудник</div>
        ${pages.map(p => `<label class="chk"><input type="checkbox" value="${p}" ${u.pages.includes(p) ? "checked" : ""}> ${esc(names[p])}</label>`).join("")}</div>
      ${isNew ? "" : `<label class="chk full"><input type="checkbox" id="uA" ${u.active ? "checked" : ""}> Доступ включён</label>`}</div>
      <div id="uE" class="lg-err"></div>
      <div style="margin-top:16px;display:flex;gap:8px"><button class="btn primary" id="uS">Сохранить</button>
      <button class="btn" id="uG">Придумать пароль</button></div>`);
    function showCreds(b) {
      const addr = a.lan_url || location.origin + "/";
      const ph = "+" + b.phone.replace(/\D/g, "").replace(/^8(?=\d{10}$)/, "7").replace(/^(?=\d{10}$)/, "7");
      const text = `Вход в дашборд ${(META && META.shop_name) || "MP Control"}\nАдрес: ${addr}\nТелефон: ${ph}\nПароль: ${b.password}`;
      $("#drawer .box").innerHTML = `<h3>Данные для входа<button class="btn ghost" data-close>✕</button></h3>
        <p>Передайте сотруднику${b.name ? " <b>" + esc(b.name) + "</b>" : ""}:</p>
        <pre class="creds">${esc(text)}</pre>
        <div style="display:flex;gap:8px;margin-top:12px"><button class="btn primary" id="cCopy">Скопировать</button><button class="btn" data-close>Готово</button></div>
        <p class="muted small" style="margin-top:14px">Пароль виден только сейчас: в базе он хранится в зашифрованном виде, и прочитать его потом нельзя — даже администратору. Если сотрудник забудет пароль, откройте его карточку и задайте новый.${a.lan_url ? "" : "<br>Адрес сейчас работает только на этом компьютере. Чтобы сотрудник зашёл со своего устройства, включите доступ по сети (config.ini → [server] network = 1)."}</p>`;
      $("#cCopy").onclick = async () => { try { await navigator.clipboard.writeText(text); $("#cCopy").textContent = "Скопировано"; } catch { getSelection().selectAllChildren($(".creds")); } };
      $("#drawer").onclick = e => { if (e.target === $("#drawer") || e.target.closest("[data-close]")) { closeDrawer(); loadMeta().then(render); } };
    }
    const sync = () => $("#uPg").classList.toggle("hidden", $("#uR").value === "admin");
    $("#uR").onchange = sync; sync();
    $("#uG").onclick = () => { const c = "abcdefghjkmnpqrstuvwxyz23456789"; let p = ""; const r = crypto.getRandomValues(new Uint32Array(8)); r.forEach(x => p += c[x % c.length]); $("#uW").value = p; };
    $("#uS").onclick = async () => {
      const body = { name: $("#uN").value.trim(), phone: $("#uP").value, password: $("#uW").value, role: $("#uR").value,
        pages: $$("#uPg input:checked").map(i => i.value), active: isNew ? true : $("#uA").checked };
      try {
        await api(isNew ? "users" : "users/" + u.id, { method: "POST", body });
        if (first) { closeDrawer(); alert("Администратор создан. Теперь войдите по телефону и паролю."); location.reload(); return; }
        if (body.password) return showCreds(body);
        closeDrawer(); await loadMeta(); render();
      } catch (e) { $("#uE").textContent = e.message; }
    };
  }
}

// ================= общее =================
function openDrawer(html) {
  const dr = $("#drawer");
  dr.innerHTML = `<div class="box">${html}</div>`;
  dr.classList.remove("hidden");
  dr.onclick = e => { if (e.target === dr || e.target.closest("[data-close]")) closeDrawer(); };
}
function closeDrawer() { $("#drawer").classList.add("hidden"); $("#drawer").innerHTML = ""; }

async function loadMeta() { META = await api("meta"); showUpd(META); applyAccess();
  const sn = META.shop_name || "MP Control"; const bb = $("#nav").parentElement.querySelector(".brand b"); if (bb) bb.textContent = sn;
  const lg = $("#nav").parentElement.querySelector(".brand .logo"); if (lg) lg.textContent = sn.slice(0, 1).toUpperCase(); }
function showUpd(m) {
  $("#updStatus").innerHTML = (m.running ? "Идёт обновление…<br>" : "") + (m.update_status ? esc(m.update_status) + "<br>" : "") +
    (m.last_update ? "Обновлено: " + esc(m.last_update) : "Данные ещё не загружались");
  $("#btnUpdate").disabled = !!m.running;
}
let pollT = null;
async function startUpdate(full = false) {
  await api("update" + (full ? "?full=1" : ""), { method: "POST" });
  poll();
}
async function poll() {
  clearTimeout(pollT);
  const s = await api("update");
  showUpd(s);
  if (s.running) pollT = setTimeout(poll, 3000);
  else { await loadMeta(); render(); }
}
$("#btnUpdate").onclick = () => startUpdate(false);
window.addEventListener("hashchange", render);
if (state.preset && state.preset !== "custom") [state.from, state.to] = presetRange(state.preset);
loadMeta().then(render).then(() => api("update").then(s => s.running && poll())).catch(e => console.warn(e.message));
