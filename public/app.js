/* 连板天梯 —— 数据加载与交互 */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const state = {
    index: null,
    data: null,
    date: null,
    query: "",
    sectors: new Set(),
    showReason: false,
    timeline: false,
    view: "ladder",
    lhb: null,
    lhbDate: null,
    compareIndex: false,
    installPrompt: null,
  };

  const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

  /* ------------------------------------------------------------ 工具函数 */
  const fmtPct = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

  function fmtMoney(v) {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (n >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
    if (n >= 1e4) return `${(n / 1e4).toFixed(0)} 万`;
    return `${n.toFixed(0)}`;
  }

  const fmtHand = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(2)}%`);

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("data-")) node.setAttribute(k, v);
      else node.setAttribute(k, v);
    }
    for (const child of [].concat(children)) {
      if (child) node.appendChild(child);
    }
    return node;
  }

  /* ------------------------------------------------------------ 数据加载 */
  async function loadIndex() {
    const res = await fetch("data/index.json", { cache: "no-cache" });
    if (!res.ok) throw new Error("index.json 读取失败");
    return res.json();
  }

  async function loadDay(date) {
    const res = await fetch(`data/${date}.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${date} 数据缺失`);
    return res.json();
  }

  const dateFromHash = () => {
    const m = /^#(\d{4}-\d{2}-\d{2})$/.exec(location.hash);
    return m ? m[1] : null;
  };

  const stockFromHash = () => {
    const m = /^#stock\/(\w+)$/.exec(location.hash);
    return m ? m[1] : null;
  };

  /* ------------------------------------------------------------ 渲染 */
  function renderHeader(data) {
    $("#dayBadge").textContent = data.weekday || WEEK[new Date(data.date).getDay()];
    $("#dayDate").textContent = data.date.replace(/-/g, ".");
    $("#titleDate").textContent = data.label;

    const idx = data.index;
    if (idx) {
      $("#idxName").textContent = idx.name || "上证指数";
      $("#idxValue").textContent = Number(idx.value).toFixed(2);
      const up = Number(idx.pct) >= 0;
      const chg = `${up ? "+" : ""}${Number(idx.pct).toFixed(2)}%`;
      const abs = `${Number(idx.chg) >= 0 ? "+" : ""}${Number(idx.chg).toFixed(2)}`;
      $("#idxChg").textContent = `${chg} ${abs}`;
      $("#idxValue").classList.toggle("is-down", !up);
      $("#idxChg").classList.toggle("is-down", !up);
    } else {
      $("#idxName").textContent = "上证指数";
      $("#idxValue").textContent = "—";
      $("#idxChg").textContent = "";
    }

    const b = data.breadth;
    const row = $("#breadthRow");
    if (b && Number.isFinite(b.up) && Number.isFinite(b.down)) {
      row.hidden = false;
      $("#upCount").textContent = b.up;
      $("#downCount").textContent = b.down;
      const total = b.up + b.down || 1;
      $("#upBar").style.width = `${(b.up / total) * 100}%`;
    } else {
      row.hidden = true;
    }
  }

  function renderChips(data) {
    const box = $("#chips");
    box.textContent = "";
    const sectors = data.sectors || [];
    if (!sectors.length) return;

    const makeChip = (name, count) => {
      const btn = el("button", {
        class: "chip",
        type: "button",
        "aria-pressed": String(state.sectors.has(name)),
      });
      btn.append(document.createTextNode(name));
      if (count !== undefined) btn.append(el("em", { text: ` ${count}` }));
      btn.addEventListener("click", () => {
        if (state.sectors.has(name)) state.sectors.delete(name);
        else state.sectors.add(name);
        btn.setAttribute("aria-pressed", String(state.sectors.has(name)));
        applyFilter();
      });
      return btn;
    };

    sectors.forEach((s) => box.append(makeChip(s.name, s.count)));

    if (state.sectors.size) {
      const clear = el("button", { class: "chip", type: "button", text: "清除筛选" });
      clear.style.color = "#b03024";
      clear.addEventListener("click", () => {
        state.sectors.clear();
        renderChips(data);
        applyFilter();
      });
      box.append(clear);
    }
  }

  function buildStockCell(stock) {
    const btn = el("button", {
      class: `stk${stock.broken ? " is-broken" : ""}`,
      type: "button",
      "data-code": stock.code,
      "aria-label": `${stock.name} ${stock.sector} ${stock.broken ? "炸板" : "涨停"}`,
    });

    const top = el("span", { class: "stk-top" });
    if (stock.broken) {
      const pct = Number(stock.pct);
      top.append(
        el("span", {
          class: `stk-pct ${pct >= 0 ? "up" : "down"}`,
          text: fmtPct(pct),
        })
      );
    } else if (stock.oneWord) {
      top.append(el("span", { class: "badge", text: "一字板" }));
    } else {
      top.append(el("span", { class: "stk-time", text: stock.lastTime || stock.firstTime || "" }));
    }

    btn.append(top);
    btn.append(el("span", { class: "stk-name", text: stock.name }));
    btn.append(el("span", { class: "stk-sector", text: stock.sector || "其他" }));
    if (stock.reason) {
      btn.append(el("span", { class: "stk-reason", text: stock.reason }));
    }
    btn.addEventListener("click", () => openSheet(stock));
    return btn;
  }

  function renderLadder(data) {
    const root = $("#ladder");
    root.textContent = "";

    data.rows.forEach((rung) => {
      const section = el("section", { class: "rung", "data-height": String(rung.height) });

      const label = el("div", { class: "rung-label" });
      label.append(el("span", { class: "rung-name", text: rung.height === 1 ? "首板" : `${rung.height}板` }));
      label.append(el("span", { class: "rung-count", text: `(${rung.stocks.length})` }));

      const grid = el("div", { class: "rung-stocks" });
      rung.stocks.forEach((s) => grid.append(buildStockCell(s)));

      section.append(label, grid);
      root.append(section);
    });
  }

  function renderMeta(data) {
    const s = data.stats || {};
    const parts = [];
    if (s.sealed !== undefined) parts.push(`涨停 ${s.sealed}`);
    if (s.broken !== undefined) parts.push(`炸板 ${s.broken}`);
    if (s.sealRate !== null && s.sealRate !== undefined) parts.push(`封板率 ${s.sealRate}%`);
    if (s.firstBoard !== undefined) parts.push(`首板 ${s.firstBoard}`);
    if (s.maxBoard !== undefined) parts.push(`最高 ${s.maxBoard} 板`);
    if (data.prevDate) parts.push(`昨收 ${data.prevDate.slice(5).replace("-", "/")}`);
    const text = parts.join(" · ");
    const meta = $("#metaLine");
    meta.dataset.base = text;
    meta.textContent = text;
    $("#disclaimer").textContent = data.disclaimer || "内容来自网络整理，不做任何投资建议";
    $("#updatedAt").textContent = data.updatedAt
      ? `更新于 ${data.updatedAt.replace("T", " ").slice(0, 16)}`
      : "";
  }

  function render(data) {
    renderHeader(data);
    renderChips(data);
    renderInsights(data);
    renderLadder(data);
    markLeaders(data);
    renderTimeline(data);
    renderMeta(data);
    $("#empty").hidden = true;
    document.body.classList.toggle("show-reason", state.showReason);
    applyFilter();
    syncDateControls();
    checkPng(data.date);
    prefetchNeighbours();
    if (state.view === "review") renderReview(data, state.index);
    if (state.view === "lhb") {
      state.lhb = null;
      state.lhbDate = null;
      loadLhb();
    }
  }

  /* ------------------------------------------------------------ 复盘面板 */
  function renderInsights(data) {
    const box = $("#insights");
    const promo = data.promotion || [];
    if (!data.summary && !promo.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    $("#summaryLine").textContent = data.summary || "";

    const ul = $("#promoteList");
    ul.textContent = "";
    promo.slice(0, 5).forEach((p) => {
      const li = el("li", { title: `${p.promoted}/${p.total} 只晋级` });
      li.append(el("span", { text: `${p.base}进${p.base + 1}` }));
      const bar = el("span", { class: "bar" });
      const fill = el("i");
      fill.style.width = `${Math.max(2, Math.min(100, p.rate))}%`;
      bar.append(fill);
      li.append(bar);
      li.append(el("b", { text: `${p.rate}%` }));
      ul.append(li);
    });
    if (!promo.length) ul.append(el("li", { text: "暂无昨日数据" }));

    // 近 10 日首板晋级率迷你折线
    const spark = $("#promoteTrend");
    spark.textContent = "";
    const trend = (data.trend || []).map((t) => ({ date: t.date, v: t.promote2 }));
    if (trend.filter((t) => t.v != null).length >= 2) {
      spark.append(sparkSvg(trend, "首板晋级率"));
    }

    const heat = $("#heatList");
    heat.textContent = "";
    const maxHeat = Math.max(...(data.sectorHeat || []).map((s) => s.heat), 1);
    (data.sectorHeat || []).slice(0, 6).forEach((s) => {
      const li = el("li", { title: `${s.count} 家 · 最高 ${s.maxBoard} 板 · 封单 ${s.sealSum} 亿` });
      const line = el("div", { class: "h-line" });
      line.append(el("span", { text: s.name }), el("b", { text: `${s.count}家·${s.maxBoard}板` }));
      const bar = el("div", { class: "h-bar" });
      const fill = el("i");
      fill.style.width = `${Math.max(4, (s.heat / maxHeat) * 100)}%`;
      bar.append(fill);
      li.append(line, bar);
      li.addEventListener("click", () => {
        state.sectors.clear();
        state.sectors.add(s.name);
        renderChips(state.data);
        applyFilter();
      });
      heat.append(li);
    });

    const chips = $("#themeChips");
    chips.textContent = "";
    (data.themes || []).slice(0, 8).forEach((t) => {
      const btn = el("button", { class: "theme-chip", type: "button", title: t.stocks.join("、") });
      btn.append(document.createTextNode(t.name), el("b", { text: String(t.count) }));
      btn.addEventListener("click", () => {
        const active = btn.getAttribute("aria-pressed") === "true";
        document.querySelectorAll(".theme-chip").forEach((b) => b.setAttribute("aria-pressed", "false"));
        btn.setAttribute("aria-pressed", String(!active));
        state.query = active ? "" : t.name;
        $("#search").value = state.query;
        applyFilter();
      });
      chips.append(btn);
    });
    if (!(data.themes || []).length) chips.append(el("span", { class: "hint", text: "今日没有明显聚集的题材" }));

    renderDiff(data.yesterdayDiff);
  }

  function sparkSvg(points, label) {
    const w = 260;
    const h = 34;
    const pad = 4;
    const vals = points.map((p) => p.v).filter((v) => v != null);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    const step = (w - pad * 2) / Math.max(points.length - 1, 1);
    const coords = points.map((p, i) => {
      const v = p.v == null ? min : p.v;
      return [pad + i * step, h - pad - ((v - min) / span) * (h - pad * 2)];
    });
    const line = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${h} L${coords[0][0].toFixed(1)},${h} Z`;
    const last = vals[vals.length - 1];

    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = `
      <path d="${area}" fill="rgba(56,214,255,0.12)" />
      <path d="${line}" fill="none" stroke="#38d6ff" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
      <circle cx="${coords[coords.length - 1][0].toFixed(1)}" cy="${coords[coords.length - 1][1].toFixed(1)}" r="2.2" fill="#38d6ff" />
    `;
    return svg;
  }

  function renderDiff(diff) {
    const box = $("#diffCols");
    box.textContent = "";
    if (!diff) {
      box.append(el("span", { text: "暂无昨日数据" }));
      return;
    }
    const cols = [
      ["晋级", diff.promoted || [], "up", (x) => `${x.name} ${x.from}→${x.to}`],
      ["掉队", diff.dropped || [], "down", (x) => `${x.name} ${x.pct == null ? "" : fmtPct(x.pct)}`],
      ["新进首板", diff.fresh || [], "", (x) => x.name],
    ];
    cols.forEach(([title, items, cls, label]) => {
      const wrap = el("div");
      wrap.append(el("h4", { text: `${title}（${items.length}）` }));
      const list = el("div", { class: "c" });
      items.slice(0, 40).forEach((item) => {
        const btn = el("button", { class: `pill ${cls}`.trim(), type: "button" });
        btn.textContent = label(item);
        btn.addEventListener("click", () => {
          const stock = findStock(item.code);
          if (stock) openSheet(stock);
        });
        list.append(btn);
      });
      wrap.append(list);
      box.append(wrap);
    });
  }

  function markLeaders(data) {
    const lead = data.leaders || {};
    const codes = new Set();
    if (lead.maxBoard) codes.add(lead.maxBoard.code);
    if (lead.sealKing) codes.add(lead.sealKing.code);
    (lead.oneWord || []).forEach((s) => codes.add(s.code));
    document.querySelectorAll(".stk").forEach((cell) => {
      cell.classList.toggle("is-leader", codes.has(cell.dataset.code));
    });
  }

  function renderTimeline(data) {
    const box = $("#timeline");
    box.textContent = "";
    const items = [];
    data.rows.forEach((r) => r.stocks.forEach((s) => items.push({ ...s, height: r.height })));
    items.sort((a, b) => (a.firstTime || a.lastTime || "99:99").localeCompare(b.firstTime || b.lastTime || "99:99"));
    items.forEach((s) => {
      const row = el("button", { class: "tl-row", type: "button", "data-code": s.code });
      row.append(el("span", { class: "tl-time", text: s.broken ? "炸板" : s.firstTime || s.lastTime || "--" }));
      const name = el("span", { class: "tl-name", text: s.name });
      if (s.broken) name.append(el("small", { text: fmtPct(s.pct) }));
      row.append(name);
      row.append(el("span", { class: "tl-b", text: s.height === 1 ? "首板" : `${s.height}板` }));
      row.append(el("span", { class: "tl-sec", text: s.sector || "" }));
      row.addEventListener("click", () => openSheet(s));
      box.append(row);
    });
  }

  /* ------------------------------------------------------------ 筛选 */
  function applyFilter() {
    const q = state.query.trim().toLowerCase();
    const sectors = state.sectors;
    let visible = 0;
    let total = 0;

    document.querySelectorAll(".rung").forEach((rung) => {
      let shown = 0;
      rung.querySelectorAll(".stk").forEach((cell) => {
        total += 1;
        const stock = findStock(cell.dataset.code);
        const hay = stock
          ? `${stock.name}${stock.code}${stock.sector}${stock.reason || ""}`.toLowerCase()
          : "";
        const okQuery = !q || hay.includes(q);
        const okSector = !sectors.size || (stock && sectors.has(stock.sector));
        const ok = okQuery && okSector;
        cell.hidden = !ok;
        if (ok) {
          shown += 1;
          visible += 1;
        }
      });
      rung.hidden = shown === 0;
      rung.classList.toggle("is-empty", shown === 0);
    });

    document.querySelectorAll(".tl-row").forEach((row) => {
      const stock = findStock(row.dataset.code);
      const hay = stock
        ? `${stock.name}${stock.code}${stock.sector}${stock.reason || ""}`.toLowerCase()
        : "";
      const ok = (!q || hay.includes(q)) && (!sectors.size || (stock && sectors.has(stock.sector)));
      row.hidden = !ok;
    });

    $("#empty").hidden = visible !== 0 || total === 0;
    if (q || sectors.size) {
      const base = $("#metaLine").dataset.base || "";
      $("#metaLine").textContent = `${base} · 筛选出 ${visible} 只 / 共 ${total} 只`;
    } else if ($("#metaLine").dataset.base) {
      $("#metaLine").textContent = $("#metaLine").dataset.base;
    }
  }

  function findStock(code) {
    if (!state.data) return null;
    for (const rung of state.data.rows) {
      const hit = rung.stocks.find((s) => s.code === code);
      if (hit) return hit;
    }
    return null;
  }

  /* ------------------------------------------------------------ 日期切换 */
  function syncDateControls() {
    const days = (state.index && state.index.days) || [];
    const i = days.findIndex((d) => d.date === state.date);
    $("#prevDay").disabled = i < 0 || i >= days.length - 1;
    $("#nextDay").disabled = i <= 0;

    const select = $("#dateSelect");
    select.innerHTML = "";
    days.forEach((d) => {
      const opt = el("option", { value: d.date });
      opt.textContent = `${d.date} ${d.weekday} · ${d.maxBoard}板`;
      select.append(opt);
    });
    select.value = state.date;
  }

  async function goto(date, { push = true } = {}) {
    if (!date) return;
    try {
      const data = await loadDay(date);
      state.date = date;
      state.data = data;
      if (push && location.hash !== `#${date}`) {
        history.pushState({ date }, "", `#${date}`);
      }
      render(data);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      console.error(err);
      $("#empty").hidden = false;
      $("#empty").textContent = `${date} 暂无数据（可能还没到更新时点）。`;
    }
  }

  function step(delta) {
    const days = (state.index && state.index.days) || [];
    const i = days.findIndex((d) => d.date === state.date);
    const target = days[i + delta];
    if (target) goto(target.date);
  }

  function prefetchNeighbours() {
    const days = (state.index && state.index.days) || [];
    const i = days.findIndex((d) => d.date === state.date);
    [days[i - 1], days[i + 1]].forEach((d) => {
      if (!d) return;
      fetch(`data/${d.date}.json`, { cache: "force-cache" }).catch(() => {});
    });
  }

  async function checkPng(date) {
    const link = $("#pngLink");
    try {
      const res = await fetch(`figures/${date}.png`, { method: "HEAD" });
      link.hidden = !res.ok;
      link.href = `figures/${date}.png`;
      link.setAttribute("download", `连板天梯-${date}.png`);
    } catch {
      link.hidden = true;
    }
  }

  /* ------------------------------------------------------------ 详情抽屉 */
  function openSheet(stock) {
    const sheet = $("#sheet");
    $("#sheetName").textContent = stock.name;
    $("#sheetCode").textContent = stock.code;

    const tags = $("#sheetTags");
    tags.textContent = "";
    const height = stock.boards === 1 ? "首板" : `${stock.boards} 板`;
    tags.append(el("span", { class: `tag ${stock.broken ? "is-broken" : "is-red"}`, text: stock.broken ? `${height} · 炸板` : `${height} · 封板` }));
    if (stock.oneWord) tags.append(el("span", { class: "tag is-red", text: "一字板" }));
    if (stock.sector) tags.append(el("span", { class: "tag", text: stock.sector }));

    const grid = $("#sheetGrid");
    grid.textContent = "";
    const rows = [
      ["涨幅", fmtPct(stock.pct)],
      ["最新价", stock.price ? `${Number(stock.price).toFixed(2)} 元` : "—"],
      ["封板时间", stock.lastTime || stock.firstTime || "—"],
      ["开板次数", stock.broken ? "—" : String(stock.brokenTimes ?? 0)],
      ["成交额", fmtMoney(stock.amount)],
      ["换手率", fmtHand(stock.turnover)],
      ["流通市值", fmtMoney(stock.floatCap)],
    ];
    if (stock.stat && stock.stat.days) {
      rows.push(["涨停统计", `${stock.stat.days} 天 ${stock.stat.ct ?? stock.boards} 板`]);
    }
    rows.forEach(([k, v]) => {
      const wrap = el("div");
      wrap.append(el("dt", { text: k }), el("dd", { text: v }));
      grid.append(wrap);
    });

    $("#sheetReason").textContent = stock.reason ? `涨停原因：${stock.reason}` : "";
    state.currentStock = stock;
    renderHistory(stock.code);
    sheet.hidden = false;
    document.body.style.overflow = "hidden";
  }

  /* ------------------------------------------------------------ 个股档案 */
  let stocksIndex = null;

  async function loadStocks() {
    if (stocksIndex) return stocksIndex;
    try {
      const res = await fetch("data/stocks.json");
      stocksIndex = res.ok ? await res.json() : {};
    } catch {
      stocksIndex = {};
    }
    return stocksIndex;
  }

  async function renderHistory(code) {
    const box = $("#sheetHist");
    box.hidden = true;
    box.textContent = "";
    const idx = await loadStocks();
    const item = idx[code];
    if (!item || !item.hits || !item.hits.length) return;
    if (!state.currentStock || state.currentStock.code !== code) return; // 已切到别的票

    const hits = item.hits;
    const sealed = hits.filter((h) => !h[3]).length;
    const best = Math.max(...hits.map((h) => h[1]));
    let promo = 0;
    for (let i = 1; i < hits.length; i += 1) {
      if (!hits[i][3] && !hits[i - 1][3] && hits[i][1] === hits[i - 1][1] + 1) promo += 1;
    }

    box.hidden = false;
    const head = el("div", { class: "hist-head" });
    head.append(el("b", { text: `近 ${hits.length} 次上榜` }));
    head.append(el("em", { text: `封板 ${sealed} 次 · 晋级 ${promo} 次 · 最高 ${best} 板` }));
    const strip = el("div", { class: "hist-strip" });
    hits.slice(-12).forEach(([date, height, , broken]) => {
      const tag = el("span", { class: `hit${broken ? " is-broken" : ""}` });
      tag.append(document.createTextNode(date.slice(5)), el("b", { text: height === 1 ? "首板" : `${height}板` }));
      strip.append(tag);
    });
    box.append(head, strip);
  }

  /* ------------------------------------------------------------ 单股分享图 */
  function wrapText(g, text, maxWidth) {
    const lines = [];
    let line = "";
    for (const ch of text) {
      if (g.measureText(line + ch).width > maxWidth && line) {
        lines.push(line);
        line = ch;
      } else {
        line += ch;
      }
    }
    if (line) lines.push(line);
    return lines;
  }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  async function shareCard(stock) {
    const W = 720;
    const H = 780;
    const DPR = 2;
    const cv = document.createElement("canvas");
    cv.width = W * DPR;
    cv.height = H * DPR;
    const g = cv.getContext("2d");
    g.scale(DPR, DPR);

    const FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif';

    const idx = await loadStocks();
    const hits = (idx[stock.code] && idx[stock.code].hits) || [];

    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#0C1729");
    bg.addColorStop(1, "#050A12");
    g.fillStyle = bg;
    g.fillRect(0, 0, W, H);

    g.strokeStyle = "rgba(56,214,255,0.05)";
    g.lineWidth = 1;
    for (let x = 0; x < W; x += 40) {
      g.beginPath();
      g.moveTo(x, 0);
      g.lineTo(x, H);
      g.stroke();
    }
    for (let y = 0; y < H; y += 40) {
      g.beginPath();
      g.moveTo(0, y);
      g.lineTo(W, y);
      g.stroke();
    }

    const glow = g.createRadialGradient(W / 2, -60, 10, W / 2, -60, 460);
    glow.addColorStop(0, "rgba(47,129,247,0.35)");
    glow.addColorStop(1, "rgba(47,129,247,0)");
    g.fillStyle = glow;
    g.fillRect(0, 0, W, H);

    // 顶部
    g.fillStyle = "#38d6ff";
    g.font = `700 18px ${FONT}`;
    g.fillText("连板天梯", 46, 62);
    g.fillStyle = "#5b7391";
    g.font = `400 16px ${FONT}`;
    g.textAlign = "right";
    g.fillText((state.date || "").replace(/-/g, "."), W - 46, 62);
    g.textAlign = "left";

    g.strokeStyle = "rgba(56,214,255,0.25)";
    g.beginPath();
    g.moveTo(46, 84);
    g.lineTo(W - 46, 84);
    g.stroke();

    // 连板高度
    const heightText = stock.boards === 1 ? "首板" : `${stock.boards} 板`;
    const badgeW = stock.boards === 1 ? 96 : 108;
    const badge = g.createLinearGradient(46, 108, 46, 162);
    badge.addColorStop(0, "#3fdcff");
    badge.addColorStop(1, "#2f81f7");
    g.fillStyle = badge;
    roundRect(g, 46, 108, badgeW, 54, 12);
    g.fill();
    g.fillStyle = "#04121f";
    g.font = `800 26px ${FONT}`;
    g.textAlign = "center";
    g.fillText(heightText, 46 + badgeW / 2, 144);
    g.textAlign = "left";

    // 名称 / 代码
    g.fillStyle = "#f2f8ff";
    g.font = `800 52px ${FONT}`;
    g.fillText(stock.name, 46, 252);
    const nameW = g.measureText(stock.name).width;
    g.fillStyle = "#5b7391";
    g.font = `400 20px ${FONT}`;
    g.fillText(stock.code, 46 + nameW + 12, 252);

    // 板块 · 状态
    g.fillStyle = "#8ba5c3";
    g.font = `400 20px ${FONT}`;
    const stateText = stock.broken
      ? `炸板 ${fmtPct(stock.pct)}`
      : `封板 ${stock.lastTime || stock.firstTime || ""}`;
    g.fillText(`${stock.sector || "其他"} · ${stateText}`, 46, 290);

    // 涨停原因（有才画）
    let cursor = 336;
    if (stock.reason) {
      g.fillStyle = "#9fb6d3";
      g.font = `400 18px ${FONT}`;
      wrapText(g, stock.reason, W - 92)
        .slice(0, 2)
        .forEach((line, i) => g.fillText(line, 46, cursor + i * 26));
      cursor += 58;
    }

    // 数据块
    const stats = [
      ["涨幅", fmtPct(stock.pct)],
      ["封单", stock.sealAmount ? `${(stock.sealAmount / 1e8).toFixed(2)} 亿` : "—"],
      ["成交额", fmtMoney(stock.amount)],
      ["换手率", fmtHand(stock.turnover)],
    ];
    const boxTop = stock.reason ? Math.max(cursor, 340) : 340;
    const boxW = (W - 92) / 2 - 8;
    stats.forEach(([k, v], i) => {
      const x = 46 + (i % 2) * (boxW + 16);
      const y = boxTop + Math.floor(i / 2) * 96;
      g.fillStyle = "rgba(47,129,247,0.08)";
      roundRect(g, x, y, boxW, 80, 12);
      g.fill();
      g.fillStyle = "#5b7391";
      g.font = `400 15px ${FONT}`;
      g.fillText(k, x + 16, y + 28);
      g.fillStyle = "#e7f0fb";
      g.font = `700 28px ${FONT}`;
      g.fillText(v, x + 16, y + 64);
    });

    // 近况
    const histTop = boxTop + 200;
    if (hits.length) {
      const sealed = hits.filter((h) => !h[3]).length;
      const best = Math.max(...hits.map((h) => h[1]));
      g.fillStyle = "#5b7391";
      g.font = `400 15px ${FONT}`;
      g.fillText(`近 ${hits.length} 次上榜 · 封板 ${sealed} 次 · 最高 ${best} 板`, 46, histTop);
      let x = 46;
      hits.slice(-7).forEach(([date, height, , broken]) => {
        const label = `${date.slice(5)} ${height === 1 ? "首" : height + "板"}`;
        g.font = `600 13px ${FONT}`;
        const w = g.measureText(label).width + 18;
        g.fillStyle = broken ? "rgba(100,120,143,0.18)" : "rgba(47,129,247,0.16)";
        roundRect(g, x, histTop + 16, w, 26, 7);
        g.fill();
        g.fillStyle = broken ? "#8fa3ba" : "#a8d4ff";
        g.fillText(label, x + 9, histTop + 34);
        x += w + 6;
      });
    }

    // 页脚
    g.fillStyle = "#3d4f66";
    g.font = `400 15px ${FONT}`;
    g.fillText("数据来源 东方财富 · 同花顺", 46, H - 58);
    g.fillStyle = "#38d6ff";
    g.fillText("lile-asdc.github.io/zt-ladder", 46, H - 32);
    g.fillStyle = "#2f3d4f";
    g.font = `400 14px ${FONT}`;
    g.textAlign = "right";
    g.fillText("不做任何投资建议", W - 46, H - 32);
    g.textAlign = "left";

    cv.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `连板天梯-${stock.name}-${state.date}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    }, "image/png");
  }

  function closeSheet() {
    $("#sheet").hidden = true;
    document.body.style.overflow = "";
  }

  /* ------------------------------------------------------------ 视图切换 */
  function switchView(name) {
    state.view = name;
    document.querySelectorAll(".tab").forEach((t) => {
      t.setAttribute("aria-selected", String(t.dataset.view === name));
    });
    ["ladder", "review", "lhb", "stock"].forEach((v) => {
      const node = document.getElementById(`view-${v}`);
      if (node) node.hidden = v !== name;
    });
    document.body.classList.toggle("view-ladder", name === "ladder");
    if (name === "review" && state.data) renderReview(state.data, state.index);
    if (name === "lhb") loadLhb();
  }

  function switchViewRaw(name) {
    state.view = name;
    document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", "false"));
    ["ladder", "review", "lhb", "stock"].forEach((v) => {
      const node = document.getElementById(`view-${v}`);
      if (node) node.hidden = v !== name;
    });
    document.body.classList.toggle("view-ladder", false);
  }

  /* ------------------------------------------------------------ 复盘看板 */
  const fmtWan = (v) => {
    if (v === null || v === undefined) return "—";
    const n = Number(v);
    if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(2)} 亿`;
    return `${n.toFixed(0)} 万`;
  };

  function renderReview(data, index) {
    if (!data) return;

    // 情绪温度计
    const emo = data.emotion || {};
    $("#emotionScore").textContent = emo.score ?? "—";
    $("#emotionLabel").textContent = emo.label || "";
    const parts = $("#emotionParts");
    parts.textContent = "";
    Object.entries(emo.parts || {}).forEach(([k, v]) => {
      const wrap = el("div", { class: "p" });
      wrap.append(document.createTextNode(`${k} ${v}`));
      const bar = el("i");
      const fill = el("b");
      fill.style.width = `${Math.max(2, Math.min(100, v))}%`;
      bar.append(fill);
      wrap.append(bar);
      parts.append(wrap);
    });
    const chart = $("#emotionChart");
    chart.textContent = "";
    const series = (data.emotionTrend || []).map((t) => ({ date: t.date, v: t.score }));
    if (series.length >= 2) chart.append(sparkSvg(series, "情绪分"));

    // 高度分布
    const hc = $("#heightChart");
    hc.textContent = "";
    const maxTotal = Math.max(...(data.heightDist || []).map((h) => h.sealed + h.broken), 1);
    (data.heightDist || []).forEach((h) => {
      const row = el("div", { class: "hrow" });
      row.append(el("span", { text: h.height === 1 ? "首板" : `${h.height}板` }));
      const track = el("span", { class: "track" });
      const sBar = el("i", { class: "s" });
      sBar.style.width = `${(h.sealed / maxTotal) * 100}%`;
      const bBar = el("i", { class: "b" });
      bBar.style.width = `${(h.broken / maxTotal) * 100}%`;
      track.append(sBar, bBar);
      row.append(track);
      const n = el("span", { class: "n", text: `${h.sealed}` });
      if (h.broken) n.append(el("span", { class: "prev", text: ` +${h.broken}炸` }));
      row.append(n);
      hc.append(row);
    });

    // 龙头梯队
    const tree = $("#ladderTree");
    tree.textContent = "";
    (data.rows || []).slice(0, 7).forEach((row) => {
      const line = el("div", { class: "lt-row" });
      line.append(el("span", { class: "lt-h", text: row.height === 1 ? "首板" : `${row.height}板` }));
      const names = el("div", { class: "lt-names" });
      row.stocks.slice(0, 12).forEach((s) => {
        names.append(el("span", { class: `lt-chip${s.broken ? " is-broken" : ""}`, text: s.name }));
      });
      if (row.stocks.length > 12) names.append(el("span", { class: "lt-chip", text: `+${row.stocks.length - 12}` }));
      line.append(names);
      tree.append(line);
    });

    // 炸板复盘
    const br = data.brokenReview || {};
    const bc = $("#brokenChart");
    bc.textContent = "";
    const maxBucket = Math.max(...(br.buckets || []).map((b) => b.count), 1);
    (br.buckets || []).forEach((b) => {
      const bar = el("div", { class: "bbar" });
      const fill = el("i");
      fill.style.height = `${Math.max(4, (b.count / maxBucket) * 60)}px`;
      const label = b.label.replace("-", "~").replace(":00", "");
      bar.append(el("span", { class: "bnum", text: String(b.count) }), fill, el("span", { class: "btime", text: label }));
      bar.title = `${b.label} 炸板 ${b.count} 家`;
      bc.append(bar);
    });
    const bl = $("#brokenList");
    bl.textContent = "";
    (br.list || []).slice(0, 14).forEach((s) => {
      bl.append(el("li", { text: `${s.name} ${fmtPct(s.pct)}` }));
    });

    // 强首板池
    const sl = $("#strongList");
    sl.textContent = "";
    (data.strongFirst || []).forEach((s) => {
      const li = el("li");
      li.append(el("span", { class: "idx", text: String(sl.children.length + 1) }));
      li.append(el("span", { class: "nm", text: s.name }));
      li.append(el("span", { class: "meta", text: `${s.sector || ""} · ${s.time || ""}` }));
      li.append(el("span", { class: "sc", text: String(s.score) }));
      li.addEventListener("click", () => {
        const stock = findStock(s.code);
        if (stock) openSheet(stock);
      });
      sl.append(li);
    });

    // 板块轮动
    const rot = $("#rotationGrid");
    rot.textContent = "";
    const days = (data.rotation && data.rotation[0] && data.rotation[0].counts.length) || 5;
    rot.append(el("span", { class: "nm", text: "" }));
    const recent = ((index && index.days) || []).slice(0, days).reverse();
    for (let i = 0; i < days; i += 1) {
      const d = recent[i];
      rot.append(el("span", { class: "h", text: d ? d.date.slice(5) : `-${days - i}` }));
    }
    const maxCell = Math.max(...(data.rotation || []).flatMap((r) => r.counts), 1);
    (data.rotation || []).forEach((r) => {
      rot.append(el("span", { class: "nm", text: r.name }));
      r.counts.forEach((c) => {
        const cell = el("span", { class: "cell", text: c ? String(c) : "" });
        const alpha = c ? 0.15 + (c / maxCell) * 0.65 : 0;
        cell.style.background = c ? `rgba(56, 214, 255, ${alpha.toFixed(2)})` : "transparent";
        if (c >= maxCell * 0.8) cell.style.color = "#04121f";
        rot.append(cell);
      });
    });

    // 月度热力
    const cal = $("#calendar");
    cal.textContent = "";
    const daysList = ((index && index.days) || []).slice(0, 35).reverse();
    const maxSealed = Math.max(...daysList.map((d) => d.sealed || 0), 1);
    daysList.forEach((d) => {
      const level = Math.min(4, Math.ceil(((d.sealed || 0) / maxSealed) * 4));
      const cell = el("span", { class: `d l${level}`, title: `${d.date} 涨停 ${d.sealed} 家` });
      if (d.date === (state.data && state.data.date)) cell.classList.add("on");
      cal.append(cell);
    });
  }

  /* ------------------------------------------------------------ 龙虎榜复盘 */
  const TAG_CLASS = { 机构: "tag-inst", 北向: "tag-north", 游资: "tag-hot", 营业部: "tag-branch" };

  async function loadLhb() {
    const date = state.date;
    if (!date) return;
    if (state.lhbDate === date && state.lhb) {
      renderHot();
      return;
    }
    $("#hotList").textContent = "加载中…";
    try {
      const res = await fetch(`data/lhb/${date}.json`, { cache: "no-cache" });
      if (!res.ok) throw new Error("no data");
      state.lhb = await res.json();
      state.lhbChart = { date: state.lhb.date, hot: state.lhb.hot || [], charts: {}, index: [], summary: null, streak: [] };
      state.lhbDate = date;
      state.lhbCode = (state.lhb.hot && state.lhb.hot[0] && state.lhb.hot[0].code) || null;
      renderHot();
      renderAllLhb();

      fetch(`data/lhb/${date}-chart.json`, { cache: "force-cache" })
        .then((r) => (r.ok ? r.json() : null))
        .then((chart) => {
          if (!chart || state.date !== date) return;
          state.lhbChart = chart;
          renderHot();
        })
        .catch(() => {});
    } catch {
      state.lhb = null;
      state.lhbChart = null;
      state.lhbDate = date;
      $("#hotList").textContent = "";
      $("#hdHead").textContent = "";
      $("#hdChart").textContent = "";
      $("#lhbSummary").textContent = "这一天还没有龙虎榜数据（交易所盘后披露，约 18:00 后生成）。";
    }
  }

  function renderHot() {
    const chart = state.lhbChart;
    const box = $("#hotList");
    box.textContent = "";
    if (!chart || !chart.hot || !chart.hot.length) {
      box.textContent = "暂无热度数据";
      return;
    }
    const maxHeat = Math.max(...chart.hot.map((h) => h.heat), 1);
    chart.hot.forEach((h, i) => {
      const item = el("button", { class: "hot-item", type: "button", "data-code": h.code });
      item.setAttribute("aria-selected", String(h.code === state.lhbCode));
      item.append(el("span", { class: "hot-rank", text: String(i + 1) }));
      const main = el("span", { class: "hot-main" });
      const top = el("span", { class: "hot-top" });
      top.append(el("b", { text: h.name }));
      top.append(el("em", { text: h.board ? (h.board === 1 ? "首板" : `${h.board}板`) : fmtPct(h.pct) }));
      if (h.broken) top.classList.add("is-broken");
      main.append(top);
      main.append(el("span", { class: "hot-meta", text: `成交 ${h.amount}亿 · 净买 ${h.net > 0 ? "+" : ""}${h.net}亿` }));
      const bar = el("span", { class: "hot-bar" });
      const fill = el("i");
      fill.style.width = `${Math.max(6, (h.heat / maxHeat) * 100)}%`;
      bar.append(fill);
      main.append(bar);
      item.append(main);
      item.addEventListener("click", () => {
        state.lhbCode = h.code;
        document.querySelectorAll(".hot-item").forEach((n) => n.setAttribute("aria-selected", "false"));
        item.setAttribute("aria-selected", "true");
        renderDetail();
      });
      box.append(item);
    });

    renderSummary(chart);
    renderRankLists(chart);
    renderSectors(chart);
    renderDetail();
  }

  function renderSummary(chart) {
    const box = $("#lhbSummary");
    box.textContent = "";
    if (chart.summary && chart.summary.text) {
      box.textContent = chart.summary.text;
      return;
    }
    if (state.lhb) {
      box.textContent = `${state.lhb.date} 共 ${state.lhb.stocks.length} 家上榜`;
    }
  }

  function renderRankLists(chart) {
    const inst = $("#instList");
    inst.textContent = "";
    const instRank = [...(chart.hot || [])].filter((h) => h.instNet).sort((a, b) => b.instNet - a.instNet).slice(0, 8);
    if (!instRank.length) inst.append(el("li", { text: "今日无机构席位上榜" }));
    instRank.forEach((h, i) => {
      const li = el("li");
      li.append(el("span", { class: "idx", text: String(i + 1) }));
      li.append(el("span", { class: "nm", text: h.name }));
      li.append(el("span", { class: "meta", text: `${h.board ? h.board + "板 · " : ""}${h.concentration ?? "—"}% 首位` }));
      li.append(el("span", { class: "sc", text: `${h.instNet > 0 ? "+" : ""}${h.instNet} 亿` }));
      li.addEventListener("click", () => {
        state.lhbCode = h.code;
        document.querySelectorAll(".hot-item").forEach((n) => n.setAttribute("aria-selected", String(n.dataset.code === h.code)));
        renderDetail();
      });
      inst.append(li);
    });

    const streak = $("#streakList");
    streak.textContent = "";
    const rows = (chart.streak || []).slice(0, 8);
    if (!rows.length) streak.append(el("li", { text: "暂无连续上榜记录" }));
    rows.forEach((s) => {
      const li = el("li");
      li.append(el("span", { class: "idx", text: `${s.days}天` }));
      li.append(el("span", { class: "nm", text: s.name }));
      li.append(el("span", { class: "meta", text: s.code }));
      li.append(el("span", { class: "sc", text: `${s.net > 0 ? "+" : ""}${s.net} 亿` }));
      li.addEventListener("click", () => openStockPage(s.code));
      streak.append(li);
    });
  }

  function renderSectors(chart) {
    const box = $("#sectorTable");
    box.textContent = "";
    const rows = (chart.sectors || []).slice(0, 8);
    if (!rows.length) {
      box.append(el("div", { class: "st-empty", text: "今日暂无板块数据" }));
      return;
    }
    const head = el("div", { class: "st-row st-head" });
    ["板块", "家数", "净买", "机构"].forEach((t) => head.append(el("span", { text: t })));
    box.append(head);
    rows.forEach((row) => {
      const line = el("div", { class: "st-row" });
      line.append(el("span", { class: "st-name", text: row.name }));
      line.append(el("span", { text: String(row.count) }));
      line.append(el("span", { class: `st-num ${row.net >= 0 ? "in" : "out"}`, text: `${row.net > 0 ? "+" : ""}${row.net}` }));
      line.append(el("span", { class: `st-num ${row.instNet >= 0 ? "in" : "out"}`, text: `${row.instNet > 0 ? "+" : ""}${row.instNet}` }));
      line.title = row.stocks.join("、");
      box.append(line);
    });
  }

  function renderDetail() {
    const chart = state.lhbChart;
    const code = state.lhbCode;
    const head = $("#hdHead");
    head.textContent = "";
    if (!chart || !code) return;
    const hot = (chart.hot || []).find((h) => h.code === code);
    if (!hot) return;
    const lhbStock = ((state.lhb && state.lhb.stocks) || []).find((s) => s.code === code) || {};

    const title = el("div", { class: "hd-title" });
    const nameBtn = el("button", { class: "hd-name", type: "button", title: "打开个股独立页" });
    nameBtn.append(document.createTextNode(hot.name));
    nameBtn.addEventListener("click", () => openStockPage(code));
    title.append(nameBtn, el("small", { text: hot.code }));
    title.append(el("span", { class: `hd-pct ${hot.pct >= 0 ? "up" : "down"}`, text: fmtPct(hot.pct) }));
    head.append(title);

    const chips = el("div", { class: "hd-chips" });
    chips.append(
      el("span", {
        class: hot.broken ? "tag is-broken" : "tag is-red",
        text: hot.board ? `${hot.board} 板 · ${hot.broken ? "炸板" : "封板"}` : "未封板",
      })
    );
    if (hot.instNet) chips.append(el("span", { class: "tag", text: `机构 ${hot.instNet > 0 ? "+" : ""}${hot.instNet} 亿` }));
    if (hot.northNet) chips.append(el("span", { class: "tag", text: `北向 ${hot.northNet > 0 ? "+" : ""}${hot.northNet} 亿` }));
    if (hot.reason) chips.append(el("span", { class: "tag", text: hot.reason }));
    head.append(chips);

    const stats = el("div", { class: "hd-stats" });
    [
      ["热度", hot.heat],
      ["成交额", `${hot.amount} 亿`],
      ["龙虎榜净买", `${hot.net > 0 ? "+" : ""}${hot.net} 亿`],
      ["首位席位占比", hot.concentration != null ? `${hot.concentration}%` : "—"],
    ].forEach(([k, v]) => {
      const d = el("div");
      d.append(el("dt", { text: k }), el("dd", { text: String(v) }));
      stats.append(d);
    });
    head.append(stats);

    const chartBox = $("#hdChart");
    chartBox.textContent = "";
    const data = chart.charts && chart.charts[code];
    const hasChart = data && data.points && data.points.length > 2;
    if (hasChart) {
      const toggle = el("button", { class: "chart-toggle", type: "button", "aria-pressed": String(state.compareIndex) });
      toggle.textContent = "对比大盘";
      toggle.addEventListener("click", () => {
        state.compareIndex = !state.compareIndex;
        toggle.setAttribute("aria-pressed", String(state.compareIndex));
        renderDetail();
      });
      chartBox.append(toggle);
      chartBox.append(priceChartSvg(data.points, data.events || [], data.spikes || [], chart.index || [], state.compareIndex));
    } else {
      chartBox.append(el("p", { class: "hd-empty", text: "这一天没有分时数据（可能停牌或数据源缺失）" }));
    }

    const evBox = $("#hdEvents");
    evBox.textContent = "";
    (data && data.events ? data.events.filter((e) => e.i >= 0) : []).forEach((e) => {
      evBox.append(el("span", { class: `ev ev-${e.kind}`, text: e.label }));
    });
    (data && data.events ? data.events.filter((e) => e.i < 0) : []).forEach((e) => {
      evBox.append(el("span", { class: "ev ev-note", text: e.label }));
    });
    if (data && data.spikes && data.spikes.length) {
      evBox.append(el("span", { class: "ev ev-spike", text: `放量 ${data.spikes.length} 次` }));
    }
    if (!evBox.children.length) evBox.append(el("span", { class: "ev ev-note", text: "当日无封板记录" }));

    const seatBox = $("#hdSeats");
    seatBox.textContent = "";
    const seats = lhbStock.seats || {};
    const col = (title, rows, pick, cls) => {
      const box = el("div", { class: "seat-col" });
      box.append(el("h4", { text: title }));
      (rows || []).forEach((row) => {
        const r = el("div", { class: `seat-row ${cls}` });
        const label = el("span", { class: "seat-name" });
        const tag = row[5] || "营业部";
        if (tag !== "营业部") label.append(el("i", { class: `seat-tag ${TAG_CLASS[tag] || ""}`, text: row[6] || tag }));
        label.append(document.createTextNode(row[0]));
        r.append(label);
        const meta = el("span", { class: "seat-prob", text: row[4] != null ? `3日胜率 ${row[4]}%` : "" });
        r.append(meta);
        r.append(el("b", { text: fmtWan(row[pick]) }));
        box.append(r);
      });
      if (!(rows || []).length) box.append(el("div", { class: "seat-row", text: "无席位数据" }));
      return box;
    };
    seatBox.append(col("买入前五（当日合计）", seats.b, 3, "in"), col("卖出前五（当日合计）", seats.s, 2, "out"));
    seatBox.append(el("p", { class: "seat-note", text: "席位为交易所盘后披露的当日合计，不含下单时间；时间轴上的点位来自分时成交，二者不可对应。" }));
  }

  function priceChartSvg(points, events, spikes, indexPoints, compare) {
    const W = 820;
    const H = 300;
    const padL = 8;
    const padR = 58;
    const padT = 34;
    const volH = 56;
    const priceBottom = H - volH - 18;
    const X = (off) => padL + (off / 240) * (W - padL - padR);

    const prices = points.map((p) => p[1]);
    let min = Math.min(...prices);
    let max = Math.max(...prices);

    let idxSeries = [];
    if (compare && indexPoints && indexPoints.length > 2) {
      const base = indexPoints[0][1];
      idxSeries = indexPoints.map(([o, v]) => [o, ((v - base) / base) * 100]);
      const stockBase = points[0][1];
      const stockPct = points.map(([o, v]) => [o, ((v - stockBase) / stockBase) * 100]);
      const lo = Math.min(...idxSeries.map((p) => p[1]), ...stockPct.map((p) => p[1]));
      const hi = Math.max(...idxSeries.map((p) => p[1]), ...stockPct.map((p) => p[1]));
      const spanP = hi - lo || 1;
      const yP = (v) => padT + (1 - (v - lo) / spanP) * (priceBottom - padT);
      const stockLine = stockPct.map(([o, v], k) => `${k ? "L" : "M"}${X(o).toFixed(1)},${yP(v).toFixed(1)}`).join(" ");
      const idxLine = idxSeries.map(([o, v], k) => `${k ? "L" : "M"}${X(o).toFixed(1)},${yP(v).toFixed(1)}`).join(" ");
      const volBars = points
        .map(([o, , v]) => {
          const h = Math.max(1, (v / Math.max(...points.map((p) => p[2]), 1)) * volH);
          return `<rect x="${(X(o) - 1).toFixed(1)}" y="${(H - 18 - h).toFixed(1)}" width="2" height="${h.toFixed(1)}" fill="rgba(47,129,247,0.5)" />`;
        })
        .join("");
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.setAttribute("class", "price-chart");
      svg.innerHTML = `
        <line x1="${padL}" y1="${padT}" x2="${W - padR}" y2="${padT}" stroke="#16283f" />
        <line x1="${padL}" y1="${priceBottom}" x2="${W - padR}" y2="${priceBottom}" stroke="#16283f" />
        <path d="${idxLine}" fill="none" stroke="#6d86a6" stroke-width="1.2" stroke-dasharray="4 3" />
        <path d="${stockLine}" fill="none" stroke="#38d6ff" stroke-width="1.6" />
        ${volBars}
        <text x="${W - padR + 6}" y="${padT + 4}" fill="#5b7391" font-size="9">${hi.toFixed(1)}%</text>
        <text x="${W - padR + 6}" y="${priceBottom}" fill="#5b7391" font-size="9">${lo.toFixed(1)}%</text>
        <text x="${padL + 4}" y="${padT - 16}" fill="#6d86a6" font-size="9">灰色虚线：上证指数</text>
      `;
      return svg;
    }

    const span = max - min || 1;
    const volMax = Math.max(...points.map((p) => p[2]), 1);
    const y = (v) => padT + (1 - (v - min) / span) * (priceBottom - padT);
    const line = points.map(([o, v], k) => `${k ? "L" : "M"}${X(o).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const area = `${line} L${X(points[points.length - 1][0]).toFixed(1)},${priceBottom} L${X(points[0][0]).toFixed(1)},${priceBottom} Z`;
    const volBars = points
      .map(([o, , v]) => {
        const h = Math.max(1, (v / volMax) * volH);
        return `<rect x="${(X(o) - 1).toFixed(1)}" y="${(H - 18 - h).toFixed(1)}" width="2" height="${h.toFixed(1)}" fill="rgba(47,129,247,0.55)" />`;
      })
      .join("");
    const marks = events
      .filter((e) => e.i >= 0 && e.i <= 240)
      .map((e) => {
        const color = e.kind === "first" ? "#ffd166" : e.kind === "last" ? "#38d6ff" : "#ff6b6b";
        return `<line x1="${X(e.i).toFixed(1)}" y1="${padT}" x2="${X(e.i).toFixed(1)}" y2="${priceBottom}" stroke="${color}" stroke-dasharray="3 3" stroke-opacity="0.55" />
                <circle cx="${X(e.i).toFixed(1)}" cy="${padT}" r="2.6" fill="${color}" />
                <text x="${X(e.i).toFixed(1)}" y="${padT - 8}" fill="${color}" font-size="9" text-anchor="middle">${e.label.split(" ")[0]}</text>`;
      })
      .join("");
    const spikeMarks = (spikes || [])
      .map((s) => `<circle cx="${X(s.i).toFixed(1)}" cy="${H - 22}" r="2.2" fill="#ffd166" opacity="0.85" />`)
      .join("");

    const ticks = [0, 60, 120, 180, 240]
      .map((o) => {
        const total = o <= 120 ? 570 + o : 780 + (o - 120);
        const label = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
        const anchor = o === 0 ? "start" : o === 240 ? "end" : "middle";
        return `<text x="${X(o).toFixed(1)}" y="${H - 4}" fill="#4d6f99" font-size="9" text-anchor="${anchor}">${label}</text>`;
      })
      .join("");

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "price-chart");
    svg.innerHTML = `
      <defs>
        <linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(56,214,255,0.28)" />
          <stop offset="100%" stop-color="rgba(56,214,255,0)" />
        </linearGradient>
      </defs>
      <line x1="${padL}" y1="${padT}" x2="${W - padR}" y2="${padT}" stroke="#16283f" />
      <line x1="${padL}" y1="${priceBottom}" x2="${W - padR}" y2="${priceBottom}" stroke="#16283f" />
      <path d="${area}" fill="url(#pg)" />
      <path d="${line}" fill="none" stroke="#38d6ff" stroke-width="1.5" stroke-linejoin="round" />
      ${volBars}
      ${spikeMarks}
      ${marks}
      ${ticks}
      <text x="${W - padR + 6}" y="${padT + 4}" fill="#5b7391" font-size="9">${max.toFixed(2)}</text>
      <text x="${W - padR + 6}" y="${priceBottom}" fill="#5b7391" font-size="9">${min.toFixed(2)}</text>
    `;
    return svg;
  }

  function renderAllLhb() {
    const box = $("#lhbList");
    box.textContent = "";
    const stocks = (state.lhb && state.lhb.stocks) || [];
    if (!stocks.length) return;
    stocks.forEach((s) => {
      const wrap = el("div", { class: "lhb-row" });
      const head = el("button", { class: "lhb-head-row", type: "button" });
      const name = el("span", { class: "lhb-name" });
      name.append(document.createTextNode(s.name), el("small", { text: s.code }));
      head.append(name);
      head.append(el("span", { class: `lhb-pct ${s.pct >= 0 ? "up" : "down"}`, text: fmtPct(s.pct) }));
      head.append(el("span", { class: `lhb-net ${s.net >= 0 ? "in" : "out"}`, text: fmtWan(s.net) }));
      head.append(el("span", { class: "lhb-amt", text: `成交 ${fmtWan(s.amount)}` }));
      head.append(el("span", { class: "lhb-why", text: s.reason || "" }));

      const seats = el("div", { class: "lhb-seats", hidden: true });
      const build = (title, rows, pick) => {
        const col = el("div", { class: "seat-col" });
        col.append(el("h4", { text: title }));
        (rows || []).forEach((seat) => {
          const r = el("div", { class: "seat-row" });
          const label = el("span", { class: "seat-name" });
          const tag = seat[5] || "营业部";
          if (tag !== "营业部") label.append(el("i", { class: `seat-tag ${TAG_CLASS[tag] || ""}`, text: seat[6] || tag }));
          label.append(document.createTextNode(seat[0]));
          r.append(label);
          r.append(el("span", { class: "seat-prob", text: seat[4] != null ? `${seat[4]}%` : "" }));
          r.append(el("b", { text: fmtWan(seat[pick]) }));
          col.append(r);
        });
        if (!(rows || []).length) col.append(el("div", { class: "seat-row", text: "无席位数据" }));
        return col;
      };
      seats.append(build("买入前五", s.seats && s.seats.b, 3), build("卖出前五", s.seats && s.seats.s, 2));
      head.addEventListener("click", () => {
        seats.hidden = !seats.hidden;
      });
      wrap.append(head, seats);
      box.append(wrap);
    });
  }

  /* ------------------------------------------------------------ 个股独立页 */
  async function openStockPage(code) {
    closeSheet();
    const box = $("#stockPage");
    box.textContent = "加载中…";
    switchViewRaw("stock");
    location.hash = `stock/${code}`;
    const idx = await loadStocks();
    const item = idx[code] || { name: code, hits: [] };
    box.textContent = "";

    const back = el("button", { class: "back-btn", type: "button", text: "← 返回龙虎榜" });
    back.addEventListener("click", () => {
      history.back();
    });
    box.append(back);

    const head = el("div", { class: "sp-head" });
    head.append(el("h2", { text: item.name }), el("span", { text: code }));
    const hits = item.hits || [];
    if (hits.length) {
      const best = Math.max(...hits.map((h) => h[1]));
      head.append(el("p", { class: "sp-meta", text: `涨停 ${hits.length} 次 · 最高 ${best} 板 · 最近 ${hits[hits.length - 1][0]}（下方为龙虎榜记录）` }));
    }
    box.append(head);

    if (hits.length) {
      const strip = el("div", { class: "hist-strip" });
      hits.slice(-14).forEach(([d, height, , broken]) => {
        const tag = el("span", { class: `hit${broken ? " is-broken" : ""}` });
        tag.append(document.createTextNode(d.slice(5)), el("b", { text: height === 1 ? "首板" : `${height}板` }));
        strip.append(tag);
      });
      box.append(strip);
    }

    // 最近一次上榜的席位
    const lhb = state.lhb && state.lhb.date === state.date ? state.lhb : await (await fetch(`data/lhb/${state.date}.json`)).json().catch(() => null);
    const record = lhb && (lhb.stocks || []).find((s) => s.code === code);
    if (record) {
      const sec = el("div", { class: "sp-seats" });
      sec.append(el("h3", { text: `${lhb.date} 龙虎榜席位` }));
      const col = (title, rows, pick) => {
        const b = el("div", { class: "seat-col" });
        b.append(el("h4", { text: title }));
        (rows || []).forEach((row) => {
          const r = el("div", { class: "seat-row" });
          const label = el("span", { class: "seat-name" });
          const tag = row[5] || "营业部";
          if (tag !== "营业部") label.append(el("i", { class: `seat-tag ${TAG_CLASS[tag] || ""}`, text: row[6] || tag }));
          label.append(document.createTextNode(row[0]));
          r.append(label);
          r.append(el("span", { class: "seat-prob", text: row[4] != null ? `${row[4]}%` : "" }));
          r.append(el("b", { text: fmtWan(row[pick]) }));
          b.append(r);
        });
        if (!(rows || []).length) b.append(el("div", { class: "seat-row", text: "无席位数据" }));
        return b;
      };
      sec.append(col("买入前五", record.seats && record.seats.b, 3), col("卖出前五", record.seats && record.seats.s, 2));
      box.append(sec);
    } else {
      box.append(el("p", { class: "hd-empty", text: "该股当日未上龙虎榜" }));
    }

    // 多日席位对比
    try {
      const histRes = await fetch("data/lhb/history.json", { cache: "force-cache" });
      if (histRes.ok) {
        const history = await histRes.json();
        const entry = history[code];
        if (entry && entry.days && entry.days.length > 1) {
          box.append(renderSeatHistory(entry));
        }
      }
    } catch {
      /* 忽略 */
    }
  }

  function renderSeatHistory(entry) {
    const wrap = el("div", { class: "sp-history" });
    wrap.append(el("h3", { text: "多日席位对比" }));
    const head = el("div", { class: "sh-row sh-head" });
    ["日期", "涨幅", "净买", "机构", "北向", "主要买方"].forEach((t) => head.append(el("span", { text: t })));
    wrap.append(head);

    const days = entry.days.slice(-8);
    days.forEach((d, i) => {
      const row = el("div", { class: "sh-row" });
      row.append(el("span", { text: d.date.slice(5) }));
      row.append(el("span", { class: `sh-pct ${d.pct >= 0 ? "up" : "down"}`, text: fmtPct(d.pct) }));
      row.append(el("span", { class: `sh-num ${d.net >= 0 ? "in" : "out"}`, text: `${d.net > 0 ? "+" : ""}${d.net}` }));
      row.append(el("span", { class: `sh-num ${d.instNet >= 0 ? "in" : "out"}`, text: `${d.instNet > 0 ? "+" : ""}${d.instNet}` }));
      row.append(el("span", { class: `sh-num ${d.northNet >= 0 ? "in" : "out"}`, text: `${d.northNet > 0 ? "+" : ""}${d.northNet}` }));
      const buyers = el("span", { class: "sh-buyers" });
      (d.topBuy || []).slice(0, 2).forEach((b) => {
        buyers.append(el("i", { class: `seat-tag ${TAG_CLASS[b.tag] || ""}`, text: b.tag === "营业部" ? "游资" : b.tag }));
        buyers.append(document.createTextNode(`${b.name.slice(0, 10)} `));
      });
      row.append(buyers);

      // 机构/游资切换判定
      const prev = days[i - 1];
      let verdict = "";
      if (prev) {
        if (d.instNet > 0 && prev.instNet <= 0) verdict = "机构进场";
        else if (d.instNet < 0 && prev.instNet >= 0) verdict = "机构撤退";
        else if (d.net > 0 && d.instNet <= 0 && prev.instNet <= 0) verdict = "游资接力";
      }
      if (verdict) row.append(el("span", { class: `sh-verdict ${verdict === "机构进场" ? "up" : verdict === "机构撤退" ? "down" : ""}`, text: verdict }));
      wrap.append(row);
    });
    return wrap;
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => switchView(tab.dataset.view));
    });
    $("#prevDay").addEventListener("click", () => step(-1));
    $("#nextDay").addEventListener("click", () => step(1));
    $("#dateSelect").addEventListener("change", (e) => goto(e.target.value));

    let timer = 0;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(timer);
      const value = e.target.value;
      timer = setTimeout(() => {
        state.query = value;
        applyFilter();
      }, 80);
    });

    $("#reasonToggle").addEventListener("click", (e) => {
      state.showReason = !state.showReason;
      e.currentTarget.setAttribute("aria-pressed", String(state.showReason));
      document.body.classList.toggle("show-reason", state.showReason);
    });

    $("#shareBtn").addEventListener("click", () => {
      if (state.currentStock) shareCard(state.currentStock);
    });

    $("#viewToggle").addEventListener("click", (e) => {
      state.timeline = !state.timeline;
      e.currentTarget.setAttribute("aria-pressed", String(state.timeline));
      $("#ladder").hidden = state.timeline;
      $("#timeline").hidden = !state.timeline;
      applyFilter();
    });

    document.addEventListener("keydown", (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (e.key === "Escape") {
        closeSheet();
        if (typing) document.activeElement.blur();
        return;
      }
      if (typing) return;
      if (e.key === "ArrowLeft") step(-1);
      if (e.key === "ArrowRight") step(1);
      if (e.key === "/") {
        e.preventDefault();
        $("#search").focus();
      }
    });

    document.querySelectorAll("[data-close]").forEach((node) => node.addEventListener("click", closeSheet));

    window.addEventListener("popstate", () => {
      const sc = stockFromHash();
      if (sc) {
        openStockPage(sc);
        return;
      }
      const d = dateFromHash();
      if (d && d !== state.date) goto(d, { push: false });
      else if (!d && state.view === "stock") switchView("lhb");
    });

    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      state.installPrompt = e;
      $("#installBtn").hidden = false;
    });

    $("#installBtn").addEventListener("click", async () => {
      if (!state.installPrompt) return;
      state.installPrompt.prompt();
      const choice = await state.installPrompt.userChoice;
      if (choice.outcome === "accepted") $("#installBtn").hidden = true;
      state.installPrompt = null;
    });
  }

  /* ------------------------------------------------------------ 启动 */
  async function boot() {
    bind();
    try {
      state.index = await loadIndex();
      const days = state.index.days || [];
      if (!days.length) throw new Error("还没有任何数据");
      const wanted = dateFromHash();
      const date = days.some((d) => d.date === wanted) ? wanted : state.index.latest;
      await goto(date, { push: false });
      const stockCode = stockFromHash();
      if (stockCode) openStockPage(stockCode);
    } catch (err) {
      console.error(err);
      $("#empty").hidden = false;
      $("#empty").textContent = "数据还没生成，请先运行抓取任务。";
    }

    if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
      navigator.serviceWorker.register("sw.js").catch(() => {});
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
