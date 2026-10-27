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
      <text x="2" y="10">${label} ${last}%</text>
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
    sheet.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeSheet() {
    $("#sheet").hidden = true;
    document.body.style.overflow = "";
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
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
      const d = dateFromHash();
      if (d && d !== state.date) goto(d, { push: false });
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
