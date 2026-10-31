"use strict";
/* Inventryx - single-page frontend over the slotting JSON API. No dependencies. */

const view = document.getElementById("view");
const cache = {};

// ---------------------------------------------------------------- utilities
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 0) => (v === null || v === undefined || v === "" ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${num(v, d)}%`);
const signed = (v, d = 1) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${num(v, d)}%`);
const dt = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "–");
const qs = (o) => Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
async function cached(key, path) { if (!cache[key]) cache[key] = await api(path); return cache[key]; }

const vc = (c) => (c ? `<span class="vc ${c}" title="Velocity class ${c}">${c}</span>` : `<span class="muted">–</span>`);
const sevBadge = (s) => `<span class="badge ${{ CRITICAL: "bad", WARNING: "warn", INFO: "info" }[s] || ""}">${esc(s)}</span>`;
const statusBadge = (s) => {
  const cls = { ACTIVE: "good", APPROVED: "good", SHIPPED: "good", COMPLETED: "good", PASS: "good", REJECTED: "bad", FAIL: "bad",
    CANCELLED: "bad", SUPERSEDED: "", PROPOSED: "info", ON_HOLD: "warn", EXCEEDED: "bad", OVER_CAPACITY: "warn" }[s] ?? "";
  return `<span class="badge ${cls}">${esc(s)}</span>`;
};
const skuLink = (id) => `<a href="#/skus/${esc(id)}">${esc(id)}</a>`;
const locLink = (id, wh, plan) => `<a href="#/warehouses/${esc(wh)}?${qs({ loc: id, plan })}" class="mono">${esc(id)}</a>`;
const orderLink = (id) => `<a href="#/orders/${esc(id)}" class="mono">${esc(id)}</a>`;

function bars(rows, fmt = (v) => num(v)) {
  const max = Math.max(...rows.map((r) => r.value), 1e-9);
  return `<div class="bars">${rows.map((r) => `<div class="bar-row"><div class="bar-label" title="${esc(r.label)}">${esc(r.label)}</div>
    <div class="bar-track"><div class="bar-fill ${r.hi ? "hi" : ""}" style="width:${(100 * r.value) / max}%"></div></div>
    <div class="bar-val">${fmt(r.value)}</div></div>`).join("")}</div>`;
}
function stacked(rows, keys, classes) {
  const max = Math.max(...rows.map((r) => keys.reduce((s, k) => s + (r[k] || 0), 0)), 1);
  return `<div class="bars">${rows.map((r) => `<div class="bar-row"><div class="bar-label">${esc(r.label)}</div>
    <div class="bar-track">${keys.map((k, i) => `<div class="bar-fill ${classes[i]}" style="width:${(100 * (r[k] || 0)) / max}%" title="${esc(k)}: ${r[k] || 0}"></div>`).join("")}</div>
    <div class="bar-val">${keys.reduce((s, k) => s + (r[k] || 0), 0)}</div></div>`).join("")}</div>`;
}
const table = (head, rows, empty = "No rows") => `<div class="table-wrap"><table><thead><tr>${head.map((h) => `<th class="${h.startsWith("#") ? "num" : ""}">${esc(h.replace(/^#/, ""))}</th>`).join("")}</tr></thead>
  <tbody>${rows.length ? rows.join("") : `<tr><td colspan="${head.length}" class="empty">${empty}</td></tr>`}</tbody></table></div>`;
const kv = (pairs) => `<dl class="kv">${pairs.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;

const SCEN = { BASELINE_LEGACY: "Legacy baseline", OPT_STATIC_V1: "Static (Jul–Sep)", OPT_PEAK_V2: "Peak-aware · deployed" };
const ZONE_COLORS = { FORWARD_PICK: "var(--z1)", SHELF: "var(--z2)", CHILLED: "var(--z3)", FROZEN: "var(--z4)", HAZMAT: "var(--z5)", BULK: "var(--z6)" };
const ZONE_SHORT = { FORWARD_PICK: "Forward pick", SHELF: "Shelf", CHILLED: "Chilled", FROZEN: "Frozen", HAZMAT: "Hazmat", BULK: "Bulk / pallet" };

// ---------------------------------------------------------------- warehouse map
function layoutSvg(L, { mode = "velocity", selected = null, tour = null } = {}) {
  const PX = 11, COL = 7, GAP = 14, SPACE = 12, TOP = 40, LEFT = 34;
  const levels = {};
  for (const l of L.locations) levels[l.aisle] = Math.max(levels[l.aisle] || 1, l.level);
  const geo = {};
  let x = LEFT;
  for (const a of L.aisles) {
    const sideW = (levels[a.aisle_id] || 1) * COL;
    geo[a.aisle_id] = { left: x, sideW, center: x + sideW + GAP / 2, bay_m: a.bay_m, len: a.length_m, zone: a.zone_type, no: a.aisle_no };
    x += 2 * sideW + GAP + SPACE;
  }
  const width = x + 8, cy = TOP - 9;
  const height = TOP + Math.max(...L.aisles.map((a) => a.length_m)) * PX + 16;
  const maxPicks = Math.max(1, ...L.locations.map((l) => l.picks));
  const out = [`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Warehouse layout">`];
  out.push(`<rect class="walk" x="0" y="${cy - 5}" width="${width}" height="10"/>`);
  out.push(`<rect x="4" y="${cy - 8}" width="22" height="16" rx="3" style="fill:var(--accent)"/><text class="stop-t" x="15" y="${cy + 3}">DOCK</text>`);
  let lastZone = null;
  for (const a of L.aisles) {
    const g = geo[a.aisle_id];
    out.push(`<rect class="walk" x="${g.center - GAP / 2 + 2}" y="${TOP}" width="${GAP - 4}" height="${g.len * PX}"/>`);
    out.push(`<text class="lbl" x="${g.center}" y="${TOP + g.len * PX + 12}" text-anchor="middle">A${g.no}</text>`);
    if (g.zone !== lastZone) {
      out.push(`<text class="zlbl" x="${g.left}" y="12">${esc(ZONE_SHORT[g.zone] || g.zone)}</text>`);
      lastZone = g.zone;
    }
  }
  for (const l of L.locations) {
    const g = geo[l.aisle];
    const cx = l.side === "L" ? g.left + (l.level - 1) * COL : g.left + g.sideW + GAP + (l.level - 1) * COL;
    const y0 = TOP + (l.y - g.bay_m / 2) * PX + 1;
    let fill, op = 1;
    if (l.status !== "ACTIVE") fill = "var(--inactive)";
    else if (mode === "zone") { fill = ZONE_COLORS[l.zone]; op = l.sku ? 0.9 : 0.25; }
    else if (mode === "heat") { fill = "var(--path)"; op = l.picks ? 0.12 + 0.88 * Math.sqrt(l.picks / maxPicks) : 0.04; }
    else fill = l.sku ? `var(--v${l.vclass || "D"})` : "var(--panel)";
    const title = `${l.id} · ${ZONE_SHORT[l.zone]} · level ${l.level}${l.golden ? " (golden)" : ""}\n${l.sku ? `${l.sku} · class ${l.vclass || "–"}` : l.status === "ACTIVE" ? "empty" : "INACTIVE"} · ${l.picks} picks`;
    out.push(`<rect class="cell${selected === l.id ? " sel" : ""}" data-id="${l.id}" x="${cx + 0.5}" y="${y0}" width="${COL - 1}" height="${Math.max(2, g.bay_m * PX - 2)}" style="fill:${fill};fill-opacity:${op}"><title>${esc(title)}</title></rect>`);
  }
  if (tour && tour.length) {
    const pts = [[15, cy]];
    let cur = null;
    for (const p of tour) {
      const g = geo[p.aisle_id], gy = TOP + p.y * PX;
      if (p.aisle_id !== cur) { if (cur) pts.push([geo[cur].center, cy]); pts.push([g.center, cy]); cur = p.aisle_id; }
      pts.push([g.center, gy]);
    }
    pts.push([geo[cur].center, cy], [15, cy]);
    out.push(`<polyline class="route" points="${pts.map((p) => p.join(",")).join(" ")}"/>`);
    tour.forEach((p) => {
      const g = geo[p.aisle_id], gy = TOP + p.y * PX;
      out.push(`<circle class="stop" cx="${g.center}" cy="${gy}" r="7"/><text class="stop-t" x="${g.center}" y="${gy + 3}">${p.pick_seq}</text>`);
    });
  }
  out.push("</svg>");
  return out.join("");
}

function legend(mode) {
  if (mode === "zone") return `<div class="legend">${Object.entries(ZONE_SHORT).map(([k, v]) => `<span><i style="background:${ZONE_COLORS[k]}"></i>${v}</span>`).join("")}<span><i style="background:var(--inactive)"></i>Inactive</span></div>`;
  if (mode === "heat") return `<div class="legend"><span><i style="background:var(--path);opacity:.15"></i>few picks</span><span><i style="background:var(--path)"></i>many picks (Jul–Oct history)</span><span><i style="background:var(--inactive)"></i>Inactive</span></div>`;
  return `<div class="legend">${["A", "B", "C", "D"].map((c) => `<span><i style="background:var(--v${c})"></i>Class ${c}</span>`).join("")}<span><i style="background:var(--panel);border:1px solid var(--line)"></i>Empty</span><span><i style="background:var(--inactive)"></i>Inactive</span></div>`;
}

// ---------------------------------------------------------------- pages
async function overview() {
  const [s, whs] = await Promise.all([cached("summary", "/api/summary"), cached("whs", "/api/warehouses")]);
  const sc = s.scenarios, b = sc.BASELINE_LEGACY, o = sc.OPT_PEAK_V2;
  const keys = ["BASELINE_LEGACY", "OPT_STATIC_V1", "OPT_PEAK_V2"];
  const scen = (metric, fmt) => bars(keys.map((k) => ({ label: SCEN[k], value: Number(sc[k][metric]), hi: k === "OPT_PEAK_V2" })), fmt);
  const pl = s.slotting.plans;
  const months = Object.entries(s.operations.labor_days_exceeded_by_month).map(([m, v]) => ({ label: m, "Peak demand (rule)": v.RULE_DERIVED || 0, "Absenteeism (injected)": v.INJECTED || 0 }));
  const exc = Object.entries(s.exceptions.by_type).sort((a, c) => c[1] - a[1]).map(([k, v]) => ({ label: k.replaceAll("_", " ").toLowerCase(), value: v }));
  view.innerHTML = `
  <h1>Slotting performance</h1>
  <p class="sub">${num(s.row_counts.warehouse)} warehouses · ${num(s.row_counts.location)} locations · ${num(s.row_counts.sku)} SKUs · ${num(s.row_counts.order_line)} order lines.
   Optimized plan went live ${s.calendar.cutover}; all plans replayed on the same ${num(b.orders)} held-out orders (${s.calendar.holdout[0]} → ${s.calendar.holdout[1]}).</p>
  <div class="grid g4">
    <div class="card kpi"><div class="k">Pick distance per order</div><div class="v">${num(o.distance_per_order_m, 1)} m</div><div class="d"><span class="up">${signed(-o.distance_reduction_pct)}</span> vs ${num(b.distance_per_order_m, 1)} m baseline</div></div>
    <div class="card kpi"><div class="k">Lines per picker-hour</div><div class="v">${num(o.lines_per_picker_hour, 1)}</div><div class="d"><span class="up">${signed(o.throughput_gain_pct)}</span> throughput</div></div>
    <div class="card kpi"><div class="k">Replenishment labor (holdout)</div><div class="v">${num(o.replen_minutes)} min</div><div class="d"><span class="up">${signed(o.replen_minutes_change_pct)}</span> · ${o.labor_days_exceeded} days over capacity (was ${b.labor_days_exceeded})</div></div>
    <div class="card kpi"><div class="k">Data validation</div><div class="v">${s.validation.passed}/${s.validation.total}</div><div class="d">${s.validation.failed ? `<span class="down">${s.validation.failed} failed</span>` : "all checks passing"} · <a href="#/quality">details</a></div></div>
  </div>
  <div class="grid g2">
    <div class="card"><h2>Distance per order (m)</h2>${scen("distance_per_order_m", (v) => num(v, 2))}</div>
    <div class="card"><h2>Lines per picker-hour</h2>${scen("lines_per_picker_hour", (v) => num(v, 1))}</div>
    <div class="card"><h2>Replenishment labor minutes</h2>${scen("replen_minutes", (v) => num(v))}</div>
    <div class="card"><h2>Picks from golden-zone levels</h2>${scen("golden_zone_pick_share", (v) => pct(v * 100))}</div>
  </div>
  <div class="grid g2">
    <div class="card"><div class="card-head"><h2>Slotting decisions</h2><a href="#/warehouses">Open map →</a></div>
      <div class="chips">
        <span class="chip">SKUs re-slotted <b>${num(pl.moves_at_cutover)}</b></span>
        <span class="chip">Location utilisation <b>${pct(pl.location_utilisation_pct)}</b></span>
        <span class="chip">A-class in golden zone <b>${pct(pl.LEGACY_2026H2.a_class_in_golden_zone_pct)} → ${pct(pl.OPT_PEAK_2026W42.a_class_in_golden_zone_pct)}</b></span>
        <span class="chip">Planner overrides <b>${s.slotting.planner_overrides.APPROVED || 0} approved · ${s.slotting.planner_overrides.REJECTED || 0} rejected</b></span>
        <span class="chip">Orders held for blocked aisle <b>${num(s.operations.orders_held_for_blocked_aisle)}</b></span>
      </div>
      <p class="small muted" style="margin:12px 0 0">The optimizer minimises pick-travel + replenishment seconds per day. Fast movers land on golden-level shelf slots near the dock rather than tiny flow-rack faces, which is why replenishment labor drops as well as travel.</p>
    </div>
    <div class="card"><div class="card-head"><h2>Exceptions raised</h2><a href="#/exceptions">Review queue →</a></div>${bars(exc)}</div>
  </div>
  <div class="card"><div class="card-head"><h2>Days replenishment exceeded labor capacity</h2>
    <div class="legend"><span><i style="background:var(--accent-2)"></i>Peak demand (rule-derived)</span><span><i style="background:var(--warn)"></i>Absenteeism (injected)</span></div></div>
    ${stacked(months, ["Peak demand (rule)", "Absenteeism (injected)"], ["", "alt"])}</div>
  <div class="card"><div class="card-head"><h2>Warehouses</h2><span class="muted small">holdout replay, per warehouse</span></div>
  ${table(["Warehouse", "Region", "#Locations", "#SKUs", "#Baseline m/order", "#Optimized m/order", "#Change", "#Exceptions"],
    whs.map((w) => `<tr class="click" data-href="#/warehouses/${w.warehouse_id}"><td><b>${w.warehouse_id}</b> <span class="muted">${esc(w.warehouse_name)}</span></td><td>${w.region}</td>
    <td class="num">${num(w.location_count)}</td><td class="num">${num(w.skus)}</td><td class="num">${num(w.baseline_m_per_order, 1)}</td><td class="num">${num(w.optimized_m_per_order, 1)}</td>
    <td class="num up">${signed(-w.distance_reduction_pct)}</td><td class="num">${num(w.exceptions)}</td></tr>`))}</div>`;
}

async function warehousePage([id], q) {
  const whs = await cached("whs", "/api/warehouses");
  id = id || whs[0].warehouse_id;
  const plan = q.plan || "OPT", mode = q.mode || "velocity";
  const L = await api(`/api/warehouses/${id}/layout?plan=${plan}`);
  const active = L.locations.filter((l) => l.status === "ACTIVE");
  const occ = active.filter((l) => l.sku);
  const aCls = occ.filter((l) => l.vclass === "A");
  const go = (p) => { location.hash = `#/warehouses/${p.id || id}?${qs({ plan: p.plan || plan, mode: p.mode || mode, loc: p.loc })}`; };
  view.innerHTML = `
  <div class="crumbs"><a href="#/">Overview</a> / Warehouse map</div>
  <h1>${esc(L.warehouse.warehouse_name)} <span class="muted">${id}</span></h1>
  <p class="sub">Top-down view from the dock. Each aisle shows both rack faces; each column inside a face is one rack level. Click a location for its slot history.</p>
  <div class="toolbar">
    <select id="wh">${whs.map((w) => `<option value="${w.warehouse_id}" ${w.warehouse_id === id ? "selected" : ""}>${w.warehouse_id} · ${esc(w.warehouse_name)}</option>`).join("")}</select>
    <div class="seg" id="plan"><button data-v="LEGACY" class="${plan === "LEGACY" ? "on" : ""}">Legacy plan</button><button data-v="OPT" class="${plan === "OPT" ? "on" : ""}">Optimized plan</button></div>
    <div class="seg" id="mode"><button data-v="velocity" class="${mode === "velocity" ? "on" : ""}">Velocity</button><button data-v="zone" class="${mode === "zone" ? "on" : ""}">Zones</button><button data-v="heat" class="${mode === "heat" ? "on" : ""}">Pick heat</button></div>
  </div>
  <div class="chips" style="margin-bottom:14px">
    <span class="chip">Locations <b>${num(L.locations.length)}</b></span><span class="chip">Occupied <b>${num(occ.length)}</b> (${pct((100 * occ.length) / active.length)})</span>
    <span class="chip">Inactive <b>${L.locations.length - active.length}</b></span>
    <span class="chip">A-class SKUs on golden levels <b>${pct((100 * aCls.filter((l) => l.golden).length) / Math.max(1, aCls.length))}</b></span>
    <span class="chip">Aisle blocks logged <b>${L.blocks}</b></span>
  </div>
  <div class="map-wrap">
    <div><div class="map-scroll" id="map">${layoutSvg(L, { mode, selected: q.loc })}</div><div style="margin-top:10px">${legend(mode)}</div></div>
    <div class="card side-panel" id="panel"><h3>Location details</h3><p class="muted small">Select a location on the map.</p></div>
  </div>`;
  document.getElementById("wh").onchange = (e) => go({ id: e.target.value, loc: "" });
  document.querySelectorAll("#plan button").forEach((b) => (b.onclick = () => go({ plan: b.dataset.v, loc: q.loc })));
  document.querySelectorAll("#mode button").forEach((b) => (b.onclick = () => go({ mode: b.dataset.v, loc: q.loc })));
  const select = async (lid) => {
    document.querySelectorAll("#map .cell.sel").forEach((c) => c.classList.remove("sel"));
    document.querySelector(`#map .cell[data-id="${lid}"]`)?.classList.add("sel");
    history.replaceState(null, "", `#/warehouses/${id}?${qs({ plan, mode, loc: lid })}`);
    const panel = document.getElementById("panel");
    panel.innerHTML = `<p class="muted">Loading…</p>`;
    const d = await api(`/api/locations/${lid}`);
    const x = d.location;
    panel.innerHTML = `<h3 class="mono">${esc(x.location_id)}</h3>
      ${kv([["Zone", `${esc(d.zone.zone_type)} (${d.storage_classes.join(", ")})`], ["Position", `${esc(x.aisle_id)} · side ${x.side} · bay ${x.bay} · level ${x.level}`],
        ["Golden zone", x.is_golden_zone ? "yes" : "no"], ["Size", `${num(x.width_cm)}×${num(x.depth_cm)}×${num(x.height_cm)} cm · ${num(x.max_weight_kg)} kg`],
        ["Status", statusBadge(x.status)], ["Picks (history)", num(d.picks)]])}
      <h3 style="margin-top:14px">Slot history</h3>
      ${d.slots.length ? `<ul class="timeline">${d.slots.map((s) => `<li>${statusBadge(s.status)} ${skuLink(s.sku_id)}<br><span class="muted small">${esc(s.plan_code)} · ${s.effective_from} → ${s.effective_to || "open"}${s.units_capacity ? ` · cap ${s.units_capacity}` : ""}${s.decision_reason ? `<br>${esc(s.decision_reason)}` : ""}</span></li>`).join("")}</ul>` : `<p class="muted small">Never assigned.</p>`}
      <a href="#/proposals?${qs({ wh: id, loc: lid })}">Propose a SKU for this location →</a>`;
  };
  document.getElementById("map").addEventListener("click", (e) => { const id_ = e.target.closest(".cell")?.dataset.id; if (id_) select(id_); });
  if (q.loc) { select(q.loc); document.querySelector(`#map .cell[data-id="${q.loc}"]`)?.scrollIntoView({ block: "center", inline: "center" }); }
}

async function skusPage(_, q) {
  const whs = await cached("whs", "/api/warehouses");
  view.innerHTML = `<h1>SKUs</h1><p class="sub">Search the item master. Velocity class and trend come from the peak-aware v2 profile per warehouse.</p>
  <div class="toolbar"><input type="search" id="q" placeholder="SKU id, name or category…" value="${esc(q.q || "")}" style="min-width:260px">
   <select id="wh"><option value="">All warehouses</option>${whs.map((w) => `<option ${q.warehouse === w.warehouse_id ? "selected" : ""}>${w.warehouse_id}</option>`).join("")}</select>
   <select id="vc"><option value="">Any class</option>${["A", "B", "C", "D"].map((c) => `<option ${q.vclass === c ? "selected" : ""}>${c}</option>`).join("")}</select>
   <span class="muted small" id="count"></span></div><div class="card" id="results"></div>`;
  const run = async () => {
    const p = { q: document.getElementById("q").value, warehouse: document.getElementById("wh").value, vclass: document.getElementById("vc").value };
    history.replaceState(null, "", `#/skus?${qs(p)}`);
    const r = await api(`/api/skus?${qs(p)}`);
    document.getElementById("count").textContent = `${num(r.total)} matches${r.total > r.rows.length ? `, showing fastest ${r.rows.length}` : ""}`;
    document.getElementById("results").innerHTML = table(["SKU", "Name", "Warehouse", "Storage", "Class", "#Lines/day", "Trend"],
      r.rows.map((s) => `<tr class="click" data-href="#/skus/${s.sku_id}"><td class="mono">${s.sku_id}</td><td>${esc(s.sku_name)}</td><td>${s.warehouse_id}</td>
      <td>${s.storage}${s.hazard !== "NONE" ? ` <span class="badge warn">UN ${s.hazard}</span>` : ""}</td><td>${vc(s.vclass)}</td><td class="num">${num(s.lines_per_day, 2)}</td><td>${esc(s.trend || "")}</td></tr>`), "No SKUs match");
  };
  document.getElementById("q").oninput = debounce(run);
  document.getElementById("wh").onchange = run;
  document.getElementById("vc").onchange = run;
  await run();
}

async function skuDetail([id]) {
  const d = await api(`/api/skus/${id}`);
  const s = d.sku;
  view.innerHTML = `<div class="crumbs"><a href="#/skus">SKUs</a> / ${esc(id)}</div><h1>${esc(s.sku_name)} <span class="muted mono">${esc(id)}</span></h1>
  <p class="sub">${esc(s.category)} · requires <b>${esc(s.required_storage_class)}</b> storage · compatibility key <b>${esc(d.compat_key)}</b></p>
  <div class="grid g3"><div class="card"><h2>Physical</h2>${kv([["Dimensions", `${num(s.length_cm, 1)} × ${num(s.width_cm, 1)} × ${num(s.height_cm, 1)} cm`],
    ["Unit volume", `${num(s.unit_volume_l, 2)} L`], ["Unit weight", `${num(s.unit_weight_kg, 2)} kg`], ["Oversized", s.is_oversized ? "yes" : "no"], ["Max order qty", num(s.max_order_qty)]])}</div>
   <div class="card"><h2>Compatibility</h2>${kv([["Temperature", esc(s.temp_class)], ["Hazard class", s.hazard_class === "NONE" ? "none" : `UN ${esc(s.hazard_class)}`], ["Group", esc(s.compat_group)], ["Supplier", esc(s.supplier_id)]])}</div>
   <div class="card"><h2>Stocked at</h2>${kv(d.sites.map((x) => [x.stocking.warehouse_id, `${esc(x.stocking.stocking_role)} · ${num(x.picks)} picks`]))}</div></div>
  ${d.sites.map((x) => {
    const wh = x.stocking.warehouse_id;
    return `<div class="card"><div class="card-head"><h2>${wh}</h2><span class="muted small">${num(x.picks)} picks Jul–Oct</span></div>
    <h3>Velocity profiles</h3>${table(["Version", "Window", "#Lines", "#Lines/day", "#Forecast/day", "Class", "#Rank", "Trend"], x.profiles.map((p) => `<tr><td>v${p.version}</td><td>${p.window_start} → ${p.window_end}</td>
      <td class="num">${num(p.order_lines)}</td><td class="num">${num(p.lines_per_day, 3)}</td><td class="num">${num(p.forecast_lines_per_day, 3)}</td><td>${vc(p.velocity_class)}</td><td class="num">${num(p.velocity_rank)}</td><td>${esc(p.demand_trend)}${p.velocity_shift_ratio ? ` <span class="muted">×${num(p.velocity_shift_ratio, 2)}</span>` : ""}</td></tr>`))}
    <h3 style="margin-top:16px">Slot history</h3>${table(["Slot", "Location", "Plan", "Status", "Effective", "#Capacity", "#Replens"], x.slots.map((sl) => `<tr><td class="mono">${sl.slot_id}</td>
      <td>${locLink(sl.location_id, wh, sl.plan_code === "LEGACY_2026H2" ? "LEGACY" : "OPT")}<br><span class="muted small">${esc(sl.location.location_type)} · L${sl.location.level}${sl.location.is_golden_zone ? " · golden" : ""}</span></td>
      <td>${esc(sl.plan_code)}</td><td>${statusBadge(sl.status)}${sl.decision_reason ? `<div class="small muted">${esc(sl.decision_reason)}</div>` : ""}</td><td>${sl.effective_from} → ${sl.effective_to || "open"}</td>
      <td class="num">${num(sl.units_capacity)}</td><td class="num">${num(sl.replenishments)}</td></tr>`))}
    <h3 style="margin-top:16px">Optimizer candidates (peak plan)</h3>${table(["#Rank", "Location", "#Capacity", "#Pick s/day", "#Replen s/day", "#Total s/day", "Chosen"], x.candidates.map((c) => `<tr><td class="num">${c.candidate_rank}</td>
      <td>${locLink(c.location_id, wh, "OPT")}</td><td class="num">${num(c.units_capacity)}</td><td class="num">${num(c.pick_cost_s_per_day, 1)}</td><td class="num">${num(c.replen_cost_s_per_day, 1)}</td>
      <td class="num"><b>${num(c.total_cost_s_per_day, 1)}</b></td><td>${c.selected ? statusBadge("ACTIVE") : ""}</td></tr>`), "No candidates")}</div>`;
  }).join("")}`;
}

async function ordersPage(_, q) {
  const [s, whs] = await Promise.all([cached("summary", "/api/summary"), cached("whs", "/api/warehouses")]);
  const wh = q.warehouse || whs[0].warehouse_id, day = q.date || s.calendar.holdout[0];
  view.innerHTML = `<h1>Orders &amp; pick tours</h1><p class="sub">Pick one day's orders; open an order to see its routed tour on the warehouse map and its full event history.</p>
  <div class="toolbar"><select id="wh">${whs.map((w) => `<option ${w.warehouse_id === wh ? "selected" : ""}>${w.warehouse_id}</option>`).join("")}</select>
  <input type="date" id="day" value="${day}" min="${s.calendar.history[0]}" max="${s.calendar.history[1]}"><span class="muted small" id="count"></span></div><div class="card" id="list"></div>`;
  const go = () => (location.hash = `#/orders?${qs({ warehouse: document.getElementById("wh").value, date: document.getElementById("day").value })}`);
  document.getElementById("wh").onchange = go;
  document.getElementById("day").onchange = go;
  const rows = await api(`/api/orders?${qs({ warehouse: wh, date: day })}`);
  document.getElementById("count").textContent = `${rows.length} orders`;
  document.getElementById("list").innerHTML = table(["Order", "Received", "Channel", "Priority", "Status", "#Lines", "#Units", "#Distance (m)"],
    rows.map((o) => `<tr class="click" data-href="#/orders/${o.order_id}"><td class="mono">${o.order_id}</td><td>${dt(o.order_ts)}</td><td>${o.channel}</td><td>${o.priority}</td>
    <td>${statusBadge(o.status)}${o.held ? ` <span class="badge warn">held</span>` : ""}</td><td class="num">${o.lines}</td><td class="num">${o.units}</td><td class="num">${num(o.distance, 1)}</td></tr>`), "No orders that day");
}

async function orderDetail([id]) {
  const d = await api(`/api/orders/${id}`);
  const o = d.order;
  const L = o.status === "CANCELLED" ? null : await api(`/api/warehouses/${o.warehouse_id}/layout?plan=${d.plan}`);
  const pickBy = Object.fromEntries(d.picks.map((p) => [p.order_line_id, p]));
  view.innerHTML = `<div class="crumbs"><a href="#/orders?${qs({ warehouse: o.warehouse_id, date: o.order_ts.slice(0, 10) })}">Orders</a> / ${esc(id)}</div>
  <h1 class="mono">${esc(id)}</h1><p class="sub">${o.warehouse_id} · ${o.channel} · ${o.priority} · ${o.carrier_service} · picked under the ${d.plan === "OPT" ? "optimized" : "legacy"} plan</p>
  <div class="chips" style="margin-bottom:16px"><span class="chip">Status ${statusBadge(o.status)}</span><span class="chip">Lines <b>${o.line_count}</b></span><span class="chip">Units <b>${o.total_units}</b></span>
   <span class="chip">Walk <b>${num(o.pick_distance_m, 1)} m</b></span><span class="chip">Received <b>${dt(o.order_ts)}</b></span><span class="chip">Picked <b>${dt(o.picked_ts)}</b></span>
   ${o.hold_block_id ? `<span class="chip">Held for <b>${esc(o.hold_block_id)}</b> until ${dt(o.hold_release_ts)}</span>` : ""}</div>
  ${L ? `<div class="card"><div class="card-head"><h2>Pick tour</h2><span class="muted small">return routing · numbers = pick sequence</span></div><div class="map-scroll">${layoutSvg(L, { tour: d.picks })}</div></div>` : ""}
  <div class="grid g2"><div class="card"><h2>Lines</h2>${table(["Line", "SKU", "#Qty", "#Seq", "Location", "Picked", "#Leg (m)"], d.lines.map((ln) => {
    const p = pickBy[ln.order_line_id];
    return `<tr><td>${ln.line_no}</td><td>${skuLink(ln.sku_id)}</td><td class="num">${ln.qty_ordered}</td><td class="num">${p ? p.pick_seq : "–"}</td>
      <td>${p ? locLink(p.location_id, o.warehouse_id, d.plan) : `<span class="muted">${esc(ln.status)}</span>`}</td><td>${p ? dt(p.pick_ts).slice(11) : "–"}</td><td class="num">${p ? num(p.travel_from_prev_m, 1) : "–"}</td></tr>`;
  }))}<p class="small muted">Return leg to dock: ${num(o.return_to_depot_m, 1)} m.</p></div>
  <div class="card"><h2>Event history</h2><ul class="timeline">${d.events.map((e) => `<li>${statusBadge(e.to_status)} <span class="muted small">${dt(e.event_ts)} · ${esc(e.actor)}${e.reason ? ` · ${esc(e.reason)}` : ""}</span></li>`).join("")}</ul>
  ${d.exceptions.length ? `<h3>Exceptions</h3>${d.exceptions.map((e) => `<p class="small">${sevBadge(e.severity)} ${esc(e.exception_type)} – ${esc(e.details)}</p>`).join("")}` : ""}</div></div>`;
}

function entityLink(e) {
  if (e.entity_type === "ORDER") return orderLink(e.entity_id);
  if (e.entity_type === "PICK_EVENT") return `<a href="#/orders/${e.entity_id.replace(/^PICK-/, "").replace(/-\d{3}$/, "")}" class="mono">${esc(e.entity_id)}</a>`;
  if (e.entity_type === "SKU") return skuLink(e.entity_id);
  return `<span class="mono">${esc(e.entity_id)}</span>`;
}

async function exceptionsPage(_, q) {
  const whs = await cached("whs", "/api/warehouses");
  const r = await api(`/api/exceptions?${qs(q)}`);
  const sel = (id, label, opts) => `<select id="${id}"><option value="">${label}</option>${opts.map((o) => `<option ${q[id] === o ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  view.innerHTML = `<h1>Exception queue</h1><p class="sub">Every decision and violation raised by the slotting engine, with the rule that fired and its evidence. The ground-truth column shows the evaluation label for injected cases.</p>
  <div class="toolbar">${sel("exception_type", "All types", r.types)}${sel("severity", "All severities", ["CRITICAL", "WARNING", "INFO"])}${sel("warehouse_id", "All warehouses", whs.map((w) => w.warehouse_id))}
   <input type="search" id="q" placeholder="Search entity or details…" value="${esc(q.q || "")}"></div>
  <div class="card">${table(["Detected", "Type", "Severity", "Entity", "Warehouse", "Action", "Ground truth"], r.rows.map((e, i) => `<tr class="click" data-toggle="${i}">
    <td class="small">${dt(e.detected_ts)}</td><td>${esc(e.exception_type)} <span class="muted small">${e.rule_id}</span></td><td>${sevBadge(e.severity)}</td><td>${entityLink(e)}</td><td>${e.warehouse_id}</td>
    <td class="small">${esc(e.action)}</td><td>${e.ground_truth.length ? e.ground_truth.map((g) => `<span class="badge ${g === e.exception_type ? "good" : ""}">${g === e.exception_type ? "labelled ✓" : esc(g)}</span>`).join(" ") : `<span class="muted small">–</span>`}</td></tr>
    <tr hidden id="x${i}"><td colspan="7" class="small"><b>${esc(e.exception_id)}</b> · ${esc(e.details)}${proposalHint(e)}</td></tr>`), "No exceptions match")}
  <div class="pager"><span>${num(r.total ? r.offset + 1 : 0)}–${num(Math.min(r.offset + 50, r.total))} of ${num(r.total)}</span>
   <button id="prev" ${r.offset === 0 ? "disabled" : ""}>Previous</button><button id="next" ${r.offset + 50 >= r.total ? "disabled" : ""}>Next</button></div></div>`;
  const go = (extra = {}) => (location.hash = `#/exceptions?${qs({ exception_type: val("exception_type"), severity: val("severity"), warehouse_id: val("warehouse_id"), q: val("q"), ...extra })}`);
  ["exception_type", "severity", "warehouse_id"].forEach((k) => (document.getElementById(k).onchange = () => go()));
  document.getElementById("q").oninput = debounce(() => go(), 400);
  document.getElementById("prev").onclick = () => go({ offset: Math.max(0, r.offset - 50) });
  document.getElementById("next").onclick = () => go({ offset: r.offset + 50 });
  view.querySelectorAll("[data-toggle]").forEach((tr) => (tr.onclick = (ev) => { if (!ev.target.closest("a")) { const x = document.getElementById(`x${tr.dataset.toggle}`); x.hidden = !x.hidden; } }));
  const q0 = document.getElementById("q");
  if (q.q) { q0.focus(); q0.setSelectionRange(q0.value.length, q0.value.length); }
}
const val = (id) => document.getElementById(id)?.value || "";
function proposalHint(e) {
  const m = /(SKU-\d{6}) -> (LOC-[\w-]+?):/.exec(e.details);
  return m ? ` · <a href="#/proposals?${qs({ wh: e.warehouse_id, sku: m[1], loc: m[2] })}">Re-check in proposal tool →</a>` : "";
}

async function proposalsPage(_, q) {
  const [s, whs] = await Promise.all([cached("summary", "/api/summary"), cached("whs", "/api/warehouses")]);
  const examples = await Promise.all(["LOCATION_CAPACITY_EXCEEDED", "INCOMPATIBLE_CO_LOCATION", "STORAGE_CLASS_MISMATCH", "DUPLICATE_ACTIVE_LOCATION"]
    .map((t) => api(`/api/exceptions?exception_type=${t}`).then((r) => ({ t, e: r.rows[0] }))));
  view.innerHTML = `<h1>Slot proposals</h1><p class="sub">Ask the engine whether a SKU may be placed in a location. It applies the same rules as the batch pipeline (capacity, storage class, bay compatibility, duplicate occupancy) against all assignments committed on the effective date, and suggests the cheapest valid alternatives.</p>
  <div class="grid g2"><div class="card"><h2>Proposal</h2>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:12px">
      <label class="field">Warehouse<select id="p-wh">${whs.map((w) => `<option ${w.warehouse_id === (q.wh || whs[0].warehouse_id) ? "selected" : ""}>${w.warehouse_id}</option>`).join("")}</select></label>
      <label class="field">Effective from<input type="date" id="p-eff" value="${q.eff || "2026-11-02"}"></label>
      <label class="field">Effective to (optional, exclusive)<input type="date" id="p-end" value="${esc(q.end || "")}"></label>
      <div class="field small muted" style="align-self:end">Leave “to” empty for an open-ended assignment. It then conflicts with anything holding the location from its start date onwards.</div>
      <label class="field">SKU<input type="text" id="p-sku" list="sku-list" placeholder="SKU-000001" value="${esc(q.sku || "")}" autocomplete="off"></label>
      <label class="field">Location<input type="text" id="p-loc" placeholder="LOC-WH-001-Z02-000010" value="${esc(q.loc || "")}" autocomplete="off"></label>
      <label class="field">Planner<select id="p-planner">${Array.from({ length: 8 }, (_, i) => `PLN-${String(i + 1).padStart(2, "0")}`).map((p) => `<option ${p === readPlanner() ? "selected" : ""}>${p}</option>`).join("")}</select></label>
      <label class="field">Note (optional)<input type="text" id="p-note" maxlength="200" placeholder="reason for the move"></label>
    </div><datalist id="sku-list"></datalist>
    <div class="toolbar" style="margin:14px 0 0"><button class="primary" id="check">Check</button><button id="submit">Submit proposal</button></div>
    <p class="small muted" style="margin-bottom:6px">Try a known case:</p>
    <div class="chips">${examples.filter((x) => x.e).map((x, i) => `<button class="chip" data-ex="${i}">${x.t.replaceAll("_", " ").toLowerCase()}</button>`).join("")}</div>
  </div><div class="card" id="result"><h2>Decision</h2><p class="muted">Enter a SKU and location, then press Check.</p></div></div>
  <div class="card"><div class="card-head"><h2>Proposal register</h2><span class="muted small" id="log-meta"></span></div><div id="log"></div></div>`;
  const f = (id) => document.getElementById(id);
  const body = () => ({ warehouse_id: f("p-wh").value, sku_id: f("p-sku").value.trim().toUpperCase(), location_id: f("p-loc").value.trim().toUpperCase(),
    effective_from: f("p-eff").value, effective_to: f("p-end").value, requested_by: f("p-planner").value, note: f("p-note").value.trim() });
  f("p-planner").onchange = () => { try { localStorage.setItem("inventryx.planner", f("p-planner").value); } catch { /* storage unavailable */ } };
  const render = (r) => {
    if (r.error) { f("result").innerHTML = `<h2>Decision</h2><p class="err">${esc(r.error)}</p>`; return; }
    const ok = r.decision === "APPROVED";
    f("result").innerHTML = `<h2>Decision</h2><div class="decision">${statusBadge(r.decision)} <span>${ok ? "All placement rules pass" : `${r.reasons.length} rule${r.reasons.length > 1 ? "s" : ""} violated`}</span></div>
      ${r.reasons.length ? `<ul class="reasons">${r.reasons.map((x) => `<li><b>${esc(x.code)}</b><br><span class="small muted">${esc(x.detail)}</span></li>`).join("")}</ul>` : ""}
      ${kv([["SKU", `${skuLink(r.sku.sku_id)} · ${esc(r.sku.required_storage_class)} · max order ${r.sku.max_order_qty}`], ["Location", `${locLink(r.location.location_id, r.location.warehouse_id, "OPT")} · ${esc(r.location.location_type)} L${r.location.level}`],
        ["Period", `${esc(r.effective_from)} → ${r.effective_to ? esc(r.effective_to) : "open-ended"}`],
        ["Units that fit", `${num(r.units_capacity)}${r.reorder_point !== null ? ` (reorder at ${r.reorder_point})` : ""}`], ["Travel cost", `${r.travel_seconds} s per line`],
        ["Current slot", r.current_slot ? `${locLink(r.current_slot.location_id, r.current_slot.warehouse_id, "OPT")}` : "none"]])}
      ${r.recorded ? `<p class="note">Recorded as <b>${esc(r.recorded.slot_id)}</b> by ${esc(r.recorded.requested_by)} in the durable proposal log${ok ? ". It now occupies this location in every later check, including after a server restart, until it is withdrawn." : "."}</p>` : ""}
      <h3 style="margin-top:14px">Best valid alternatives</h3>${table(["Location", "Zone", "#Capacity", "#Cost s/day", ""], r.alternatives.map((a) => `<tr><td class="mono">${a.location_id}</td><td>${esc(a.zone)}${a.golden ? " · golden" : ""}</td>
        <td class="num">${a.units_capacity}</td><td class="num">${num(a.total_cost, 1)}</td><td><button data-use="${a.location_id}">Use</button></td></tr>`), "No free valid location")}`;
    f("result").querySelectorAll("[data-use]").forEach((b) => (b.onclick = () => { f("p-loc").value = b.dataset.use; check(); }));
  };
  const check = async (submit = false) => {
    f("result").innerHTML = `<h2>Decision</h2><p class="muted">Evaluating…</p>`;
    try { render(await api(`/api/proposals/${submit ? "submit" : "check"}`, body())); } catch (e) { render({ error: e.message }); }
    history.replaceState(null, "", `#/proposals?${qs({ wh: body().warehouse_id, sku: body().sku_id, loc: body().location_id, eff: body().effective_from, end: body().effective_to })}`);
    if (submit) loadLog();
  };
  const loadLog = async () => {
    const d = await api("/api/proposals");
    f("log-meta").textContent = `${d.proposals.length} proposals · ${d.events} events · append-only log ${d.log_path}`;
    f("log").innerHTML = (d.skipped.length ? `<p class="err small">${d.skipped.length} unreadable log line(s) were skipped: ${esc(d.skipped.join("; "))}</p>` : "") +
      table(["ID", "Planner", "Warehouse", "SKU", "Location", "Effective", "Status", "Reasons", ""], d.proposals.map((p) => `<tr class="click" data-hist="${p.slot_id}">
      <td class="mono">${p.slot_id}</td><td>${esc(p.requested_by)}</td><td>${p.warehouse_id}</td><td>${skuLink(p.sku_id)}</td><td>${locLink(p.location_id, p.warehouse_id, "OPT")}</td>
      <td class="small">${p.effective_from} → ${p.effective_to || "open"}</td><td>${statusBadge(p.status)}</td><td class="small">${p.reasons.length ? p.reasons.map((x) => esc(x.code)).join("<br>") : "all rules passed"}</td>
      <td>${p.status === "APPROVED" ? `<button data-withdraw="${p.slot_id}">Withdraw</button>` : ""}</td></tr>
      <tr hidden id="h-${p.slot_id}"><td colspan="9"></td></tr>`), "No proposals yet. Submitted proposals are written to an append-only log and survive restarts.");
    f("log").querySelectorAll("[data-withdraw]").forEach((b) => (b.onclick = async (e) => {
      e.stopPropagation();
      const reason = prompt(`Withdraw ${b.dataset.withdraw}? Optional reason:`, "");
      if (reason === null) return;
      try { await api(`/api/proposals/${b.dataset.withdraw}/withdraw`, { requested_by: f("p-planner").value, reason }); } catch (err) { alert(err.message); }
      loadLog();
    }));
    f("log").querySelectorAll("[data-hist]").forEach((tr) => (tr.onclick = async (e) => {
      if (e.target.closest("a,button")) return;
      const row = document.getElementById(`h-${tr.dataset.hist}`);
      row.hidden = !row.hidden;
      if (row.hidden) return;
      const h = await api(`/api/proposals/${tr.dataset.hist}`);
      row.firstElementChild.innerHTML = `<ul class="timeline">${h.events.map((ev) => `<li><b>${esc(ev.event)}</b> <span class="muted small">${dt(ev.ts)}${ev.requested_by ? ` · ${esc(ev.requested_by)}` : ""}${ev.actor ? ` · ${esc(ev.actor)}` : ""}${ev.decision ? ` · ${esc(ev.decision)}` : ""}${ev.reason ? ` · ${esc(ev.reason)}` : ""}${ev.note ? ` · “${esc(ev.note)}”` : ""}</span></li>`).join("")}</ul>`;
    }));
  };
  f("check").onclick = () => check(false);
  f("submit").onclick = () => check(true);
  view.querySelectorAll("[data-ex]").forEach((b) => (b.onclick = () => {
    const e = examples.filter((x) => x.e)[b.dataset.ex].e;
    const m = /(SKU-\d{6}) -> (LOC-[\w-]+?):/.exec(e.details);
    f("p-wh").value = e.warehouse_id; f("p-sku").value = m[1]; f("p-loc").value = m[2]; f("p-eff").value = "2026-11-02"; check();
  }));
  f("p-sku").oninput = debounce(async () => {
    const r = await api(`/api/skus?${qs({ q: f("p-sku").value, warehouse: f("p-wh").value })}`);
    f("sku-list").innerHTML = r.rows.slice(0, 20).map((x) => `<option value="${x.sku_id}">${esc(x.sku_name)} · class ${x.vclass || "–"}</option>`).join("");
  });
  ["p-sku", "p-loc"].forEach((id) => f(id).addEventListener("keydown", (e) => { if (e.key === "Enter") check(); }));
  loadLog();
  if (q.sku && q.loc) check();
}

async function qualityPage(_, q) {
  const d = await cached("quality", "/api/quality");
  const v = d.validation, filter = q.filter || "all";
  const cats = Object.entries(v.by_category);
  const checks = v.checks.filter((c) => filter === "all" || (filter === "fail" ? c.status === "FAIL" : c.category === filter));
  const groups = {};
  for (const f of d.files) (groups[f.path.split("/")[0]] ||= []).push(f);
  const r = d.reproducibility;
  view.innerHTML = `<h1>Data quality &amp; downloads</h1><p class="sub">Validation runs against the exported files, not in-memory state. Every derived value is re-computed from source records.</p>
  <div class="grid g4">
    <div class="card kpi"><div class="k">Checks passed</div><div class="v">${v.passed}/${v.total}</div><div class="d">${v.failed ? `<span class="down">${v.failed} failing</span>` : "no failures"}</div></div>
    <div class="card kpi"><div class="k">Seed</div><div class="v">${d.manifest.seed}</div><div class="d mono">${esc(d.manifest.command)}</div></div>
    <div class="card kpi"><div class="k">Reproducibility</div><div class="v">${r ? (r.identical ? "Identical" : "Differs") : "Not run"}</div><div class="d">${r ? `${r.files_compared} files, 2 regenerations${r.matches_published_dataset ? ", matches this dataset" : ""}` : "python -m inventryx reproduce"}</div></div>
    <div class="card kpi"><div class="k">Generator</div><div class="v">v${esc(d.manifest.generator_version)}</div><div class="d">${esc(d.manifest.provenance)}</div></div>
  </div>
  <div class="grid g2"><div class="card"><h2>Checks by category</h2>${table(["Category", "#Passed", "#Failed"], cats.map(([k, c]) => `<tr class="click" data-href="#/quality?filter=${k}"><td>${k.replaceAll("_", " ")}</td><td class="num">${c.PASS || 0}</td><td class="num ${c.FAIL ? "down" : ""}">${c.FAIL || 0}</td></tr>`))}</div>
  <div class="card"><h2>Downloads</h2>${Object.entries(groups).map(([g, fs]) => `<h3 style="margin-top:8px">${esc(g)}/</h3><div class="chips">${fs.map((f) => `<a class="chip" href="/files/${f.path}" download>${esc(f.path.split("/").slice(1).join("/") || f.path)} <span class="muted">${num(f.bytes / 1024, 0)} KB</span></a>`).join("")}</div>`).join("")}</div></div>
  <div class="card"><div class="card-head"><h2>All checks</h2><select id="filter"><option value="all">All</option><option value="fail" ${filter === "fail" ? "selected" : ""}>Failed only</option>${cats.map(([k]) => `<option value="${k}" ${filter === k ? "selected" : ""}>${k}</option>`).join("")}</select></div>
  ${table(["Status", "Category", "Check", "#Violations"], checks.map((c) => `<tr><td>${statusBadge(c.status)}</td><td>${esc(c.category)}</td><td>${esc(c.check)}${c.sample.length ? `<div class="small muted">${esc(c.sample.join("; "))}</div>` : ""}</td><td class="num">${c.violations}</td></tr>`))}</div>`;
  document.getElementById("filter").onchange = (e) => (location.hash = `#/quality?filter=${e.target.value}`);
}

// ---------------------------------------------------------------- actor pages
function whSelect(whs, current, allowAll = false) {
  return `<select id="wh">${allowAll ? `<option value="">All warehouses</option>` : ""}${whs.map((w) => `<option value="${w.warehouse_id}" ${w.warehouse_id === current ? "selected" : ""}>${w.warehouse_id} · ${esc(w.warehouse_name)}</option>`).join("")}</select>`;
}

function laborChart(days, cutover) {
  const W = 960, H = 230, PL = 40, PB = 22, PT = 8, n = days.length;
  const max = Math.max(1, ...days.map((d) => Math.max(d.workload, d.capacity))) * 1.08;
  const bw = (W - PL) / n, y = (v) => PT + (H - PT - PB) * (1 - v / max);
  const out = [`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily replenishment workload versus capacity">`];
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    out.push(`<line class="grid-l" x1="${PL}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${PL - 6}" y="${y(v) + 3}" text-anchor="end">${num(v)}</text>`);
  }
  days.forEach((d, i) => {
    const cls = d.status === "EXCEEDED" ? "over" : d.date >= cutover ? "post" : "ok";
    out.push(`<rect class="bar ${cls}" data-date="${d.date}" x="${PL + i * bw + 0.5}" y="${y(d.workload)}" width="${Math.max(1, bw - 1)}" height="${H - PB - y(d.workload)}">
      <title>${d.date}: ${num(d.workload, 1)} of ${num(d.capacity, 1)} min · ${d.tasks} tasks (${d.emergency} emergency)${d.reason === "ABSENTEEISM" ? " · absenteeism" : ""}</title></rect>`);
    if (d.date.endsWith("-01")) out.push(`<text class="axis" x="${PL + i * bw}" y="${H - 6}">${d.date.slice(0, 7)}</text>`);
  });
  out.push(`<polyline class="cap" points="${days.map((d, i) => `${PL + i * bw},${y(d.capacity)} ${PL + (i + 1) * bw},${y(d.capacity)}`).join(" ")}"/>`);
  const ci = days.findIndex((d) => d.date >= cutover);
  if (ci >= 0) out.push(`<line class="cut" x1="${PL + ci * bw}" x2="${PL + ci * bw}" y1="${PT}" y2="${H - PB}"/><text class="axis" x="${PL + ci * bw + 4}" y="${PT + 10}">optimized plan live</text>`);
  out.push("</svg>");
  return out.join("");
}

async function laborPage(_, q) {
  const whs = await cached("whs", "/api/warehouses");
  const wh = q.warehouse || whs[0].warehouse_id;
  const d = await api(`/api/labor/${wh}`);
  const a = d.peak_before_cutover, b = d.after_cutover;
  view.innerHTML = `<h1>Replenishment &amp; labor</h1><p class="sub">Daily pick-face replenishment workload against the planned labor minutes. Red days broke capacity; the dashed line is the staffing plan (dips are absenteeism).</p>
  <div class="toolbar">${whSelect(whs, wh)}</div>
  <div class="grid g4">
    <div class="card kpi"><div class="k">Peak, legacy plan (Oct 1–14)</div><div class="v">${num(a.avg_workload, 1)} min/day</div><div class="d">${num(a.avg_tasks, 1)} tasks/day · ${pct(a.emergency_share * 100)} emergency · ${a.exceeded} days over</div></div>
    <div class="card kpi"><div class="k">Peak, optimized plan (from ${d.cutover})</div><div class="v">${num(b.avg_workload, 1)} min/day</div><div class="d">${num(b.avg_tasks, 1)} tasks/day · ${pct(b.emergency_share * 100)} emergency · ${b.exceeded} days over</div></div>
    <div class="card kpi"><div class="k">Change after re-slotting</div><div class="v ${b.avg_workload <= a.avg_workload ? "up" : "down"}">${signed(a.avg_workload ? (b.avg_workload / a.avg_workload - 1) * 100 : 0)}</div><div class="d">daily replenishment minutes, same peak season</div></div>
    <div class="card kpi"><div class="k">Days over capacity (Jul–Oct)</div><div class="v">${d.all.exceeded}</div><div class="d">of ${d.all.days} working days</div></div>
  </div>
  <div class="card chart"><div class="card-head"><h2>Daily workload vs capacity (minutes)</h2>
   <div class="legend"><span><i style="background:var(--accent-2)"></i>Legacy plan</span><span><i style="background:var(--accent)"></i>Optimized plan</span><span><i style="background:var(--bad)"></i>Over capacity</span><span><i style="background:var(--warn)"></i>Capacity</span></div></div>
   ${laborChart(d.days, d.cutover)}<p class="small muted">Click a day to see its replenishment tasks.</p></div>
  <div class="card" id="day"><h2>Day detail</h2><p class="muted">Select a bar above, or an exceeded day below.</p></div>
  <div class="card"><h2>Days over capacity</h2>${table(["Date", "Plan", "#Tasks", "#Workload (min)", "#Capacity (min)", "#Over (min)", "Capacity basis"],
    d.days.filter((x) => x.status === "EXCEEDED").map((x) => `<tr class="click" data-day="${x.date}"><td>${x.date}</td><td>${x.plan === "OPT" ? "Optimized" : "Legacy"}</td><td class="num">${x.tasks}</td>
    <td class="num">${num(x.workload, 1)}</td><td class="num">${num(x.capacity, 1)}</td><td class="num down">${num(x.over, 1)}</td><td>${x.reason === "ABSENTEEISM" ? statusBadge("ABSENTEEISM") : "Standard plan"}</td></tr>`), "No day exceeded capacity")}</div>`;
  document.getElementById("wh").onchange = (e) => (location.hash = `#/labor?warehouse=${e.target.value}`);
  const showDay = async (day) => {
    history.replaceState(null, "", `#/labor?${qs({ warehouse: wh, date: day })}`);
    const r = await api(`/api/labor/${wh}?date=${day}`);
    const cap = r.capacity ? r.capacity.replen_capacity_min : 0;
    document.getElementById("day").innerHTML = `<div class="card-head"><h2>${day} · ${r.tasks.length} tasks</h2><span class="muted small">capacity ${num(cap, 1)} min${r.capacity && r.capacity.capacity_reason === "ABSENTEEISM" ? " (absenteeism)" : ""}</span></div>
      ${table(["Created", "Type", "SKU", "Location", "Zone", "#Units", "#Minutes", "Labor"], r.tasks.map((t) => `<tr><td>${dt(t.created_ts).slice(11)}</td><td>${statusBadge(t.replen_type)}</td>
      <td>${skuLink(t.sku_id)}</td><td>${locLink(t.location_id, wh, day >= d.cutover ? "OPT" : "LEGACY")}</td><td>${esc(t.zone)}</td><td class="num">${t.units}</td><td class="num">${num(t.task_minutes, 2)}</td>
      <td>${statusBadge(t.labor_status)}</td></tr>`), "No replenishment that day")}`;
    document.getElementById("day").scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  view.querySelectorAll(".chart .bar").forEach((r) => (r.onclick = () => showDay(r.dataset.date)));
  view.querySelectorAll("tr[data-day]").forEach((r) => (r.onclick = () => showDay(r.dataset.day)));
  if (q.date) showDay(q.date);
}

async function aislesPage(_, q) {
  const whs = await cached("whs", "/api/warehouses");
  const d = await api(`/api/aisle-blocks?${qs({ warehouse: q.warehouse })}`);
  const filter = q.show || "all";
  const rows = d.rows.filter((r) => filter === "all" || (filter === "late" ? r.late_reported : r.orders_held.length));
  view.innerHTML = `<h1>Aisle blocks</h1><p class="sub">Aisle closures from maintenance, inspections, cleaning and spills. Blocks reported in advance make the WMS hold affected orders; blocks reported late mean picks already went through a closed aisle, which escalates as a safety violation.</p>
  <div class="toolbar">${whSelect(whs, q.warehouse, true)}
   <div class="seg" id="show"><button data-v="all" class="${filter === "all" ? "on" : ""}">All</button><button data-v="held" class="${filter === "held" ? "on" : ""}">Held orders</button><button data-v="late" class="${filter === "late" ? "on" : ""}">Late-reported</button></div></div>
  <div class="grid g4">
    <div class="card kpi"><div class="k">Blocks logged</div><div class="v">${num(d.total)}</div><div class="d">Jul–Oct history</div></div>
    <div class="card kpi"><div class="k">Orders held and re-released</div><div class="v">${num(d.held)}</div><div class="d">handled exception path (R-07)</div></div>
    <div class="card kpi"><div class="k">Late-reported blocks</div><div class="v">${num(d.late_reported)}</div><div class="d">reported after the closure started</div></div>
    <div class="card kpi"><div class="k">Picks inside a closed aisle</div><div class="v ${d.violations ? "down" : ""}">${num(d.violations)}</div><div class="d">escalated for safety audit (R-05)</div></div>
  </div>
  <div class="card">${table(["Block", "Warehouse", "Aisle", "Type", "Window", "#Minutes", "Reported", "Orders held", "Violations"], rows.map((b) => `<tr>
    <td class="mono">${b.block_id}</td><td>${b.warehouse_id}</td><td><a href="#/warehouses/${b.warehouse_id}?mode=heat">${esc(b.aisle_id)}</a><div class="small muted">${esc(b.zone)}</div></td><td>${esc(b.block_type)}</td>
    <td class="small">${dt(b.start_ts)} → ${dt(b.end_ts).slice(11)}</td><td class="num">${b.duration_min}</td>
    <td class="small">${dt(b.reported_ts)}${b.late_reported ? ` <span class="badge bad">late</span>` : ""}</td>
    <td>${b.orders_held.slice(0, 3).map(orderLink).join("<br>")}${b.orders_held.length > 3 ? `<div class="small muted">+${b.orders_held.length - 3} more</div>` : b.orders_held.length ? "" : `<span class="muted">–</span>`}</td>
    <td>${b.violations.length ? b.violations.map((p) => `<a class="mono" href="#/orders/${p.replace(/^PICK-/, "").replace(/-\d{3}$/, "")}">${esc(p)}</a>`).join("<br>") : `<span class="muted">–</span>`}</td></tr>`), "No blocks match")}</div>`;
  const go = (extra) => (location.hash = `#/aisles?${qs({ warehouse: val("wh"), show: filter, ...extra })}`);
  document.getElementById("wh").onchange = () => go({});
  document.querySelectorAll("#show button").forEach((b) => (b.onclick = () => go({ show: b.dataset.v })));
}

async function shippingPage(_, q) {
  const whs = await cached("whs", "/api/warehouses");
  const d = await api(`/api/shipping?${qs({ warehouse: q.warehouse })}`);
  const carriers = d.carriers.map((c) => c.carrier_service);
  const tot = d.carriers.reduce((s, c) => ({ shipped: s.shipped + c.shipped, late: s.late + c.late }), { shipped: 0, late: 0 });
  view.innerHTML = `<h1>Shipping &amp; carriers</h1><p class="sub">Outbound service level per carrier service: whether orders were handed over before the promised ship time, how much slack remained, and order-to-ship lead time.</p>
  <div class="toolbar">${whSelect(whs, q.warehouse, true)}</div>
  <div class="grid g4">
    <div class="card kpi"><div class="k">Orders shipped</div><div class="v">${num(tot.shipped)}</div><div class="d">${carriers.length} carrier services</div></div>
    <div class="card kpi"><div class="k">On-time handover</div><div class="v">${pct(tot.shipped ? (100 * (tot.shipped - tot.late)) / tot.shipped : 0, 2)}</div><div class="d">${tot.late ? `<span class="down">${num(tot.late)} late</span>` : "none late"} · shipped vs promised ship time</div></div>
    ${d.carriers.filter((c) => c.carrier_service === "PARCEL_EXPRESS").map((c) => `<div class="card kpi"><div class="k">Tightest express slack</div><div class="v">${num(c.min_slack_h, 2)} h</div><div class="d">10% of express orders had under ${num(c.p10_slack_h, 2)} h to spare</div></div>`).join("")}
    <div class="card kpi"><div class="k">Cancelled before release</div><div class="v">${num(d.carriers.reduce((s, c) => s + c.cancelled, 0))}</div><div class="d">never reached picking</div></div>
  </div>
  <div class="card">${table(["Carrier service", "#Orders", "#Shipped", "#Units", "#On time", "#Late", "#Min slack (h)", "#P10 slack (h)", "#Median slack (h)", "#Median lead (h)", "#P90 lead (h)"],
    d.carriers.map((c) => `<tr><td><b>${esc(c.carrier_service)}</b></td><td class="num">${num(c.orders)}</td><td class="num">${num(c.shipped)}</td><td class="num">${num(c.units)}</td>
    <td class="num">${pct(c.on_time_rate * 100, 2)}</td><td class="num ${c.late ? "down" : ""}">${num(c.late)}</td><td class="num">${num(c.min_slack_h, 2)}</td><td class="num">${num(c.p10_slack_h, 2)}</td><td class="num">${num(c.median_slack_h, 2)}</td><td class="num">${num(c.median_lead_h, 2)}</td><td class="num">${num(c.p90_lead_h, 2)}</td></tr>`))}</div>
  <div class="card"><div class="card-head"><h2>Shipments per day (last 4 weeks)</h2><div class="legend">${carriers.map((c, i) => `<span><i style="background:${["var(--accent-2)", "var(--warn)", "var(--accent)", "var(--info)"][i % 4]}"></i>${esc(c)}</span>`).join("")}</div></div>
  ${stacked(d.daily.map((x) => ({ label: x.date, ...x })), carriers, carriers.map((_, i) => ["", "alt", "hi", "info"][i % 4]))}</div>`;
  document.getElementById("wh").onchange = (e) => (location.hash = `#/shipping?${qs({ warehouse: e.target.value })}`);
}

async function suppliersPage(_, q) {
  const rows = await cached("suppliers", "/api/suppliers");
  const text = (q.q || "").toLowerCase();
  const shown = rows.filter((r) => !text || r.supplier_id.toLowerCase().includes(text) || r.supplier_name.toLowerCase().includes(text) || r.country_code.toLowerCase() === text);
  view.innerHTML = `<h1>Suppliers</h1><p class="sub">Each supplier's assortment: how many SKUs they ship, how much demand those SKUs drive, and how many need special handling.</p>
  <div class="toolbar"><input type="search" id="q" placeholder="Supplier, name or country code…" value="${esc(q.q || "")}" style="min-width:260px"><span class="muted small">${shown.length} suppliers</span></div>
  <div class="card">${table(["Supplier", "Country", "#Lead time (d)", "#SKUs", "#Picks Jul–Oct", "#Hazmat", "#Cold chain", "#Oversized"], shown.map((s) => `<tr class="click" data-href="#/suppliers/${s.supplier_id}">
    <td><b class="mono">${s.supplier_id}</b> <span class="muted">${esc(s.supplier_name)}</span></td><td>${s.country_code}</td><td class="num">${s.lead_time_days}</td><td class="num">${s.skus}</td>
    <td class="num">${num(s.picks)}</td><td class="num">${s.hazmat || "–"}</td><td class="num">${s.cold || "–"}</td><td class="num">${s.oversized || "–"}</td></tr>`), "No suppliers match")}</div>`;
  const input = document.getElementById("q");
  input.oninput = debounce(() => (location.hash = `#/suppliers?${qs({ q: input.value })}`), 400);
  if (q.q) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
}

async function supplierDetail([id]) {
  const d = await api(`/api/suppliers/${id}`);
  const s = d.supplier;
  view.innerHTML = `<div class="crumbs"><a href="#/suppliers">Suppliers</a> / ${esc(id)}</div><h1>${esc(s.supplier_name)} <span class="muted mono">${esc(id)}</span></h1>
  <p class="sub">${esc(s.country_code)} · replenishment lead time ${s.lead_time_days} days · ${d.items.length} warehouse stocking points</p>
  <div class="card">${table(["SKU", "Name", "Warehouse", "Storage", "Class", "Trend", "#Lines/day", "#Picks", "Current location"], d.items.map((x) => `<tr>
    <td>${skuLink(x.sku_id)}</td><td>${esc(x.sku_name)}</td><td>${x.warehouse_id}</td><td>${esc(x.storage)}</td><td>${vc(x.vclass)}</td><td>${esc(x.trend || "")}</td>
    <td class="num">${num(x.lines_per_day, 3)}</td><td class="num">${num(x.picks)}</td><td>${x.location_id ? locLink(x.location_id, x.warehouse_id, "OPT") : "–"}</td></tr>`), "No SKUs")}</div>`;
}

// ---------------------------------------------------------------- roles
const ROLES = {
  all: null,
  planner: ["overview", "warehouses", "proposals", "skus", "exceptions"],
  operator: ["warehouses", "orders", "aisles", "labor", "exceptions"],
  manager: ["overview", "labor", "shipping", "exceptions", "quality"],
  analyst: ["overview", "skus", "shipping", "suppliers", "exceptions", "quality"],
  carrier: ["shipping", "orders"],
  supplier: ["suppliers", "skus"],
};
const HOME = { planner: "#/", operator: "#/aisles", manager: "#/labor", analyst: "#/", carrier: "#/shipping", supplier: "#/suppliers" };
function readPlanner() { try { return localStorage.getItem("inventryx.planner") || "PLN-01"; } catch { return "PLN-01"; } }
function readRole() { try { return localStorage.getItem("inventryx.role") || "all"; } catch { return "all"; } }
function applyRole(role, navigate) {
  const allowed = ROLES[role] || null;
  document.querySelectorAll("#menu a").forEach((a) => (a.hidden = Boolean(allowed && !allowed.includes(a.dataset.route))));
  try { localStorage.setItem("inventryx.role", role); } catch { /* storage unavailable */ }
  if (navigate && allowed) {
    const current = document.querySelector("#menu a.active")?.dataset.route;
    if (!allowed.includes(current)) location.hash = HOME[role];
  }
}
const roleSelect = document.getElementById("role");
roleSelect.value = ROLES[readRole()] !== undefined ? readRole() : "all";
roleSelect.onchange = () => applyRole(roleSelect.value, true);
applyRole(roleSelect.value, false);

// ---------------------------------------------------------------- router
const ROUTES = [
  [/^\/?(?:overview)?$/, "overview", overview],
  [/^\/warehouses(?:\/([^/]+))?$/, "warehouses", warehousePage],
  [/^\/skus\/([^/]+)$/, "skus", skuDetail],
  [/^\/skus$/, "skus", skusPage],
  [/^\/orders\/([^/]+)$/, "orders", orderDetail],
  [/^\/orders$/, "orders", ordersPage],
  [/^\/exceptions$/, "exceptions", exceptionsPage],
  [/^\/labor$/, "labor", laborPage],
  [/^\/aisles$/, "aisles", aislesPage],
  [/^\/shipping$/, "shipping", shippingPage],
  [/^\/suppliers\/([^/]+)$/, "suppliers", supplierDetail],
  [/^\/suppliers$/, "suppliers", suppliersPage],
  [/^\/proposals$/, "proposals", proposalsPage],
  [/^\/quality$/, "quality", qualityPage],
];

async function route() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  const q = Object.fromEntries(new URLSearchParams(query));
  const hit = ROUTES.map(([re, name, fn]) => [path.match(re), name, fn]).find(([m]) => m);
  document.querySelectorAll("#menu a").forEach((a) => a.classList.toggle("active", Boolean(hit && a.dataset.route === hit[1])));
  if (!hit) { view.innerHTML = `<h1>Not found</h1><p><a href="#/">Back to overview</a></p>`; return; }
  try {
    await hit[2](hit[0].slice(1).map((x) => x && decodeURIComponent(x)), q);
  } catch (e) {
    view.innerHTML = `<h1>Something went wrong</h1><p class="err">${esc(e.message)}</p><p><a href="#/">Back to overview</a></p>`;
  }
}

view.addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-href]");
  if (tr && !e.target.closest("a,button")) location.hash = tr.dataset.href;
});
window.addEventListener("hashchange", () => { route(); view.focus({ preventScroll: true }); window.scrollTo(0, 0); });
cached("summary", "/api/summary").then((s) => {
  document.getElementById("dataset-tag").innerHTML = `Dataset <b>${esc(s.dataset.profile)}</b> · seed ${s.dataset.seed}<br>As of ${dt(s.calendar.as_of)}`;
}).catch(() => {});
route();
