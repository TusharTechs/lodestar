/* Lodestar web app: vanilla JS, MapLibre GL, Chart.js. All numbers come from the API. */
const API = "";
const C = { ink: "#17252e", accent: "#c4552d", band: "rgba(242,180,143,.45)", band2: "rgba(233,137,95,.45)",
  teal: "#2a7d6e", gold: "#d9a441", blue: "#3c6e91", muted: "#6a7b85", line: "#dfe5e8" };
const SEG = { household: { label: "Households", color: C.blue }, sme: { label: "Businesses", color: C.gold },
  anchors: { label: "Anchors (schools, clinics, mills)", color: C.teal } };
const COUNTRY = { NG: "Nigeria", KE: "Kenya", CD: "DR Congo (metered validation sites)" };
const charts = {};
let map, sites = [], current = null, currentReport = null;

const $ = (s, el = document) => el.querySelector(s);
const fmt = (v, nd = 0) => v == null || isNaN(v) ? "n/a" : Number(v).toLocaleString("en-US", { maximumFractionDigits: nd, minimumFractionDigits: nd });
const mwh = (kwh, nd = 1) => kwh == null ? "n/a" : fmt(kwh / 1000, nd);
const pct = (v, nd = 0) => v == null || isNaN(v) ? "n/a" : (100 * v).toFixed(nd) + "%";
const usd = v => v == null ? "n/a" : Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(2) + "M" : "$" + fmt(v);
const get = async u => { const r = await fetch(API + u); if (!r.ok) throw new Error((await r.text()) || r.status); return r.json(); };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function mk(id, cfg) { if (charts[id]) charts[id].destroy(); const el = document.getElementById(id); if (!el) return; charts[id] = new Chart(el, cfg); }
Chart.defaults.font.family = "Inter, system-ui, sans-serif"; Chart.defaults.font.size = 11; Chart.defaults.color = C.muted;
Chart.defaults.plugins.legend.labels.boxWidth = 12; Chart.defaults.maintainAspectRatio = false; Chart.defaults.animation.duration = 500;

/* ---------------- tabs ---------------- */
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(t) {
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  document.querySelectorAll(".tab").forEach(s => s.classList.toggle("on", s.id === t));
  if (t === "explore" && mapReady) map.resize();
  if (t === "validation") renderValidation();
  if (t === "bureau") renderBureau();
  if (t === "ledger") renderLedger();
  if (t === "method") renderMethod();
  history.replaceState(null, "", "#" + t + (t === "explore" && current ? "/" + current : ""));
}

/* ---------------- map ---------------- */
let mapReady = false;
function initMap() {
  const webgl = (() => { try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; } })();
  try { if (!window.maplibregl || !webgl) throw new Error("WebGL unavailable"); }
  catch (e) { $("#map").innerHTML = '<div style="position:absolute;left:280px;right:16px;top:40%;color:#cfd8dc">The map needs WebGL, which this browser does not provide. Everything else works: pick a village from the list.</div>'; $("#map").style.background = "#17252e"; return; }
  map = new maplibregl.Map({
    container: "map",
    style: { version: 8, sources: {
        sat: { type: "raster", tileSize: 256, maxzoom: 18, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
          tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"] },
        lbl: { type: "raster", tileSize: 256, tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"] } },
      layers: [{ id: "sat", type: "raster", source: "sat" }, { id: "lbl", type: "raster", source: "lbl", paint: { "raster-opacity": .8 } }] },
    center: [20, 3], zoom: 3.1, attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.on("load", () => {
    map.addSource("sites", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "sites", type: "circle", source: "sites", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 5, 10, 9], "circle-color": ["match", ["get", "country"], "CD", C.teal, C.accent],
      "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
    map.addSource("geo", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "bld", type: "fill", source: "geo", filter: ["==", ["geometry-type"], "Polygon"], paint: {
      "fill-color": ["match", ["get", "cls"], "large", "#ffb703", "residential", "#48cae4", "#ade8f4"], "fill-opacity": .9, "fill-outline-color": "#023e8a" } });
    map.addLayer({ id: "poi", type: "circle", source: "geo", filter: ["==", ["geometry-type"], "Point"], paint: {
      "circle-radius": 6, "circle-color": ["match", ["get", "poi_type"], "mill", "#e63946", "market", C.gold, "school", "#8e7cc3", "health", "#2a9d8f", "#ffffff"],
      "circle-stroke-color": C.ink, "circle-stroke-width": 1.5 } });
    map.on("click", "sites", e => { e.preventDefault(); openSite(e.features[0].properties.site_id); });
    map.on("click", "poi", e => { e.preventDefault(); const p = e.features[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<b>${esc(p.poi_type)}</b><br>${esc(p.name || "")}`).addTo(map); });
    map.on("click", e => { if (e.defaultPrevented) return; askForecast(e.lngLat); });
    ["sites", "poi"].forEach(l => { map.on("mouseenter", l, () => map.getCanvas().style.cursor = "pointer"); map.on("mouseleave", l, () => map.getCanvas().style.cursor = ""); });
    mapReady = true; drawSites();
    if (currentReport) showOnMap(currentReport);
  });
}

function drawSites() {
  if (!mapReady) return;
  map.getSource("sites").setData({ type: "FeatureCollection", features: sites.map(s => ({ type: "Feature", properties: s, geometry: { type: "Point", coordinates: [s.lon, s.lat] } })) });
}

function showOnMap(rep) {
  if (!mapReady) return;
  const cam = { center: [rep.site.lon, rep.site.lat], zoom: 15.6 };
  if (location.search.includes("shot")) map.jumpTo(cam); else map.flyTo({ ...cam, speed: 1.8 });
  get(`/api/sites/${rep.site.site_id}/geo`).then(g => map.getSource("geo").setData(g)).catch(() => {});
}

async function loadSites() {
  sites = await get("/api/sites");
  drawSites();
  const by = {}; sites.forEach(s => (by[s.country] ||= []).push(s));
  const order = ["NG", "KE", "CD"].filter(k => by[k]).concat(Object.keys(by).filter(k => !["NG", "KE", "CD"].includes(k)));
  $("#sitelist").innerHTML = order.map(cc => `<h4>${COUNTRY[cc] || cc}</h4>` + by[cc].map(s =>
    `<div class="it" data-id="${s.site_id}"><span>${esc(s.name)} <small>${esc(s.admin1 || "")}</small></span>${s.country === "CD" ? '<span class="badge">metered</span>' : s.has_mill ? '<span class="badge warn">mill</span>' : s.has_market ? '<span class="badge warn">market</span>' : ""}</div>`).join("")).join("");
  document.querySelectorAll("#sitelist .it").forEach(el => el.onclick = () => openSite(el.dataset.id));
  const m = location.hash.match(/^#explore\/(.+)$/); if (m) openSite(m[1]);
}

function askForecast(ll) {
  const pop = new maplibregl.Popup({ closeOnClick: true }).setLngLat(ll)
    .setHTML(`<div style="max-width:220px"><b>Forecast this location?</b><br><span class="muted">${ll.lat.toFixed(4)}, ${ll.lng.toFixed(4)} · 1.5 km radius</span><br><button class="btn primary" id="goPt" style="margin-top:6px">Run forecast</button></div>`).addTo(map);
  setTimeout(() => { const b = document.getElementById("goPt"); if (b) b.onclick = () => { pop.remove(); runPoint(ll); }; }, 0);
}

async function runPoint(ll) {
  const r = await fetch("/api/forecast", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lat: ll.lat, lon: ll.lng, radius_m: 1500 }) });
  if (!r.ok) { alert(await r.text()); return; }
  const { job } = await r.json();
  $("#report").innerHTML = `<div class="empty"><h2><span class="spinner"></span>Forecasting ${ll.lat.toFixed(4)}, ${ll.lng.toFixed(4)}</h2><p id="jobstage" class="muted">Starting…</p></div>`;
  const poll = async () => {
    const j = await get("/api/jobs/" + job);
    if (j.status === "running") { const el = $("#jobstage"); if (el) el.textContent = `${j.stage} · ${j.elapsed_s}s`; setTimeout(poll, 2500); return; }
    if (j.status === "error") { $("#report").innerHTML = `<div class="empty"><h2>Could not forecast here</h2><div class="flag">${esc(j.error)}</div><p class="muted">Lodestar never fills a gap with made-up data. Try a location with mapped buildings.</p></div>`; return; }
    sites.push({ site_id: j.site_id, name: j.report.site.name, country: j.report.site.country, lat: ll.lat, lon: ll.lng });
    openSite(j.site_id, j.report);
  };
  poll();
}

async function openSite(id, rep) {
  current = id; showTab("explore");
  document.querySelectorAll("#sitelist .it").forEach(el => el.classList.toggle("on", el.dataset.id === id));
  $("#report").innerHTML = `<div class="empty"><h2><span class="spinner"></span>Loading forecast…</h2></div>`;
  try { rep = rep || await get(`/api/sites/${id}/report`); } catch (e) { $("#report").innerHTML = `<div class="flag">${esc(e.message)}</div>`; return; }
  currentReport = rep;
  showOnMap(rep);
  renderReport(rep);
}

/* ---------------- report ---------------- */
function renderReport(r, prior) {
  const h = r.headline, f = r.finance, isDrc = !!r.actuals;
  const b = r.features.buildings, p = r.features.pois || {};
  const flags = (r.warnings || []).filter(w => !/geojson capped|centre moved/.test(w));
  $("#report").innerHTML = `
  <div class="rhead"><div><h2>${esc(r.site.name)}</h2>
    <div class="sub">${esc(r.site.admin1 || "")} · ${esc(COUNTRY[r.site.country] || r.site.country || "")} · ${r.site.lat.toFixed(4)}, ${r.site.lon.toFixed(4)} · ${esc(r.region_label)} benchmarks</div></div>
    <div class="actions">
      <a class="btn primary" href="/api/sites/${r.site.site_id}/memo" target="_blank">Lender memo (PDF)</a>
      <a class="btn" href="/api/sites/${r.site.site_id}/load-8760.csv">8760 load for HOMER</a>
    </div></div>
  ${flags.map(w => `<div class="flag">${esc(w)}</div>`).join("")}
  <div class="headline">
    <div class="kpi main"><div class="l">Year-3 demand · P50</div><div class="v">${mwh(h.p50)} <small style="font-size:15px">MWh/mo</small></div><div class="s">Confidence: <b>${h.confidence}</b> · P10/P90 = ${h.p10_over_p90.toFixed(1)}×</div></div>
    <div class="kpi"><div class="l">P90 · conservative</div><div class="v">${mwh(h.p90)}</div><div class="s">exceeded with 90% probability</div></div>
    <div class="kpi"><div class="l">P10 · optimistic</div><div class="v">${mwh(h.p10)}</div><div class="s">exceeded with 10% probability</div></div>
    <div class="kpi"><div class="l">Peak load · P50</div><div class="v">${fmt(r.load_profile.peak_kw)} kW</div><div class="s">load factor ${pct(r.load_profile.load_factor)}</div></div>
  </div>
  ${r.update ? `<div class="narrow"><b>Updated with ${r.update.months_used} metered months.</b> Year-3 band P90–P10: ${mwh(prior.p90)}–${mwh(prior.p10)} → <b>${mwh(h.p90)}–${mwh(h.p10)} MWh/month</b> (width ${pct(1 - (h.p10 - h.p90) / (prior.p10 - prior.p90))} narrower).</div>` : ""}
  <div class="card"><h3>Demand growth, months 0–60 after commissioning</h3>
    <p class="lede">Monthly site energy (MWh). Dark band P75–P25, light band P90–P10.${isDrc ? ' <b>Black line: actual metered demand</b>, which this forecast did not see.' : ""}</p>
    <div class="chart"><canvas id="fan"></canvas></div>
    ${isDrc && !r.update ? `<div style="margin-top:8px"><button class="btn primary" id="bureauBtn">Demand Bureau: share the first 6 metered months →</button> <span class="src">re-weights the forecast with the operator's own meters</span></div>` : ""}
    ${r.update && isDrc ? `<div style="margin-top:8px"><button class="btn" id="resetBtn">← Back to the day-0 forecast</button></div>` : ""}
  </div>
  <div class="row2">
    <div class="card"><h3>Connections ramp</h3><p class="lede">Connected customers, P50. Potential: ${fmt(r.potential_customers.household)} households, ${fmt(r.potential_customers.sme)} businesses (from ${fmt(b.count)} footprints).</p><div class="chart small"><canvas id="conn"></canvas></div></div>
    <div class="card"><h3>Consumption per connection</h3><p class="lede">kWh/month per connection, P50. Appliance acquisition raises use over time.</p><div class="chart small"><canvas id="q"></canvas></div></div>
  </div>
  <div class="card"><h3>What drives this forecast</h3><p class="lede">Contribution of each driver to year-3 P50 demand, added one at a time. <span class="pill calibrated">calibrated</span> <span class="pill benchmark">benchmark</span> <span class="pill assumption">assumption</span> mark where each effect comes from.</p>
    <div id="wf"></div>
    <p class="src" style="margin-top:8px">Mapped in OpenStreetMap within ${fmt(r.site.radius_m)} m: ${["school", "health", "market", "mill", "shop", "worship"].map(k => `${p[k] ?? "?"} ${k}`).join(" · ")}. ${esc(r.benchmark_note)}.</p></div>
  <div class="row2">
    <div class="card"><h3>Who uses the power (year 3)</h3><div class="chart small"><canvas id="seg"></canvas></div></div>
    <div class="card"><h3>Daily load profile (year 3, P50)</h3><p class="lede">Households alone: load factor ${pct(r.load_profile.load_factor_households_only)}. With businesses and anchors: ${pct(r.load_profile.load_factor)}.</p><div class="chart small"><canvas id="lp"></canvas></div></div>
  </div>
  ${f ? renderFinance(f) : '<div class="flag">Solar resource unavailable, so no sizing or finance view.</div>'}
  <p class="src">Forecast ID <code>${r.ledger ? r.ledger.forecast_id : "n/a"}</code> pre-registered ${r.ledger ? r.ledger.issued_at : ""} · ${r.method.draws.toLocaleString()} Monte Carlo draws · model ${r.method.model_version}</p>`;

  drawFan(r);
  const mo = r.fan.months, sg = r.fan.segments;
  mk("conn", { type: "line", data: { labels: mo, datasets: ["household", "sme"].filter(s => sg[s]).map(s => ({ label: SEG[s].label, data: sg[s].connections_p50, borderColor: SEG[s].color, pointRadius: 0, borderWidth: 2 })) },
    options: { scales: { x: { title: { display: true, text: "month" }, ticks: { maxTicksLimit: 7 } } } } });
  mk("q", { type: "line", data: { labels: mo, datasets: ["household", "sme"].filter(s => sg[s]).map(s => ({ label: SEG[s].label, data: sg[s].kwh_per_conn_p50, borderColor: SEG[s].color, pointRadius: 0, borderWidth: 2 })) },
    options: { scales: { x: { title: { display: true, text: "month" }, ticks: { maxTicksLimit: 7 } }, y: { type: "logarithmic", title: { display: true, text: "kWh/month" } } } } });
  const segs = Object.entries(r.segments_y3_kwh_month);
  mk("seg", { type: "doughnut", data: { labels: segs.map(([k]) => SEG[k]?.label || k), datasets: [{ data: segs.map(([, v]) => Math.round(v)), backgroundColor: segs.map(([k]) => SEG[k]?.color || "#999") }] },
    options: { plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: c => `${c.label}: ${fmt(c.raw / 1000, 1)} MWh/mo` } } } } });
  const lp = r.load_profile;
  mk("lp", { type: "bar", data: { labels: lp.hours.map(x => x + ":00"), datasets: Object.entries(lp.kw).map(([k, v]) => ({ label: SEG[k]?.label || k, data: v, backgroundColor: SEG[k]?.color })) },
    options: { scales: { x: { stacked: true, ticks: { maxTicksLimit: 8 } }, y: { stacked: true, title: { display: true, text: "kW" } } } } });
  renderWaterfall(r.waterfall);
  if (f) drawFinance(f);
  const bb = $("#bureauBtn"); if (bb) bb.onclick = () => runBureauDemo(r);
  const rb = $("#resetBtn"); if (rb) rb.onclick = () => openSite(r.site.site_id);
}

function drawFan(r) {
  const fan = r.fan, mo = fan.months, k = v => v.map(x => x / 1000);
  const ds = [
    { label: "P10", data: k(fan.p10), borderWidth: 0, pointRadius: 0, backgroundColor: C.band, fill: "+1" },
    { label: "P90", data: k(fan.p90), borderWidth: 0, pointRadius: 0, fill: false },
    { label: "P25", data: k(fan.p25), borderWidth: 0, pointRadius: 0, backgroundColor: C.band2, fill: "+1" },
    { label: "P75", data: k(fan.p75), borderWidth: 0, pointRadius: 0, fill: false },
    { label: "P50 forecast", data: k(fan.p50), borderColor: C.accent, borderWidth: 2.5, pointRadius: 0, fill: false },
  ];
  if (r.actuals) {
    const a = new Array(mo.length).fill(null);
    r.actuals.months.forEach((m, i) => { if (m <= mo[mo.length - 1] && r.actuals.total_kwh[i] > 0) a[m] = r.actuals.total_kwh[i] / 1000; });
    ds.push({ label: "Actual metered", data: a, borderColor: C.ink, borderWidth: 2, pointRadius: 0, spanGaps: true, fill: false });
  }
  if (r.update) {
    const u = r.update.months_used; ds.push({ label: "Months shared", data: mo.map(m => m <= u ? 0 : null), borderColor: C.teal, borderWidth: 6, pointRadius: 0, fill: false });
  }
  mk("fan", { type: "line", data: { labels: mo, datasets: ds },
    options: { interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { filter: i => !["P10", "P90", "P25", "P75"].includes(i.text) } }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmt(c.raw, 1)} MWh` } } },
      scales: { x: { title: { display: true, text: "months since commissioning" }, ticks: { maxTicksLimit: 11 } }, y: { title: { display: true, text: "MWh / month" }, beginAtZero: true } } } });
}

function renderWaterfall(wf) {
  if (!wf) { $("#wf").innerHTML = '<p class="muted">Driver breakdown is shown on the day-0 forecast.</p>'; return; }
  const maxv = Math.max(...wf.map(w => w.p50_kwh_month));
  let prev = 0;
  $("#wf").innerHTML = `<div class="wf">` + wf.map(w => {
    const from = w.key === "base" ? 0 : prev, to = w.p50_kwh_month; prev = to;
    const l = Math.min(from, to) / maxv * 100, wd = Math.abs(to - from) / maxv * 100;
    const col = w.key === "base" ? C.blue : to >= from ? C.teal : C.accent;
    const lab = w.key === "base" ? `${mwh(to)} MWh/mo` : `${w.delta_pct >= 0 ? "+" : ""}${(100 * w.delta_pct).toFixed(0)}%`;
    const tag = /assumption/.test(w.source) ? "assumption" : /benchmark/.test(w.source) ? "benchmark" : "calibrated";
    return `<div>${esc(w.text)} <span class="pill ${tag}">${esc(w.source)}</span></div><div class="bar"><i style="left:${l}%;width:${Math.max(wd, .6)}%;background:${col}"></i></div><div class="n" style="text-align:right;font-weight:600">${lab}</div>`;
  }).join("") + `<div><b>Year-3 P50 demand</b></div><div></div><div style="text-align:right;font-weight:700">${mwh(prev)} MWh/mo</div></div>`;
}

function renderFinance(f) {
  const o = f.options, a = f.assumptions;
  return `<div class="card"><h3>Bankability: how wrong can it be, and what does it cost?</h3>
  <p class="lede">The system and the finance plan are tested against every one of the Monte Carlo demand draws, not one point estimate.</p>
  <div class="grid4">
    <div class="kpi"><div class="l">Grant needed for ${pct(a.hurdle_irr)} IRR</div><div class="v">${pct(f.grant_needed.p50_demand)}</div><div class="s">of CAPEX (${usd(f.grant_per_connection_usd)}/connection) at P50 · ${pct(f.grant_needed.p90_demand)} at P90</div></div>
    <div class="kpi"><div class="l">Debt safe on P90 demand</div><div class="v">${usd(f.safe_debt_p90_usd)}</div><div class="s">${f.safe_debt_p90_usd > 0 ? `DSCR ≥ ${a.dscr_covenant}, ${a.debt_tenor} yrs at ${pct(a.debt_rate)}, ${a.debt_grace_years}-yr grace` : f.first_year_p90_covers_opex ? `P90 cash flow covers OPEX only from year ${f.first_year_p90_covers_opex}` : "P90 cash flow does not cover OPEX"}</div></div>
    <div class="kpi"><div class="l">If debt is sized on P50 instead</div><div class="v">${pct(f.prob_dscr_breach_if_p50_debt)}</div><div class="s">breach risk on ${usd(f.debt_p50_usd)}${f.breach_below_kwh_month ? `; breaks below ${mwh(f.breach_below_kwh_month)} MWh/mo (${f.breach_percentile_label})` : ""}</div></div>
    <div class="kpi"><div class="l">Unsubsidised tariff needed</div><div class="v">$${f.required_tariff_usd_kwh.toFixed(2)}</div><div class="s">per kWh vs $${f.region_tariff_usd_kwh.toFixed(2)} regional average</div></div>
  </div>
  <h4 style="margin:14px 0 4px">Sizing options</h4>
  <table class="t"><tr><th>Size the system on</th><th class="n">PV kWp</th><th class="n">Battery kWh</th><th class="n">CAPEX</th><th class="n">IRR at P50</th><th class="n">Unserved energy, median</th><th class="n">Unserved if P10</th><th class="n">Breach risk, P50 debt</th></tr>
  ${[["p90", "P90 demand (undersize risk)"], ["p50", "P50 demand (recommended, modular)"], ["p10", "P10 demand (oversize risk)"]].map(([k, lab]) =>
    `<tr class="${k === f.recommended ? "rec" : ""}"><td>${lab}</td><td class="n">${fmt(o[k].pv_kwp)}</td><td class="n">${fmt(o[k].battery_kwh)}</td><td class="n">${usd(o[k].capex_usd)}</td><td class="n">${pct(o[k].irr_p50, 1)}</td><td class="n">${pct(o[k].unserved_share_median)}</td><td class="n">${pct(o[k].unserved_share_p10_demand)}</td><td class="n">${pct(o[k].prob_dscr_breach_if_p50_debt)}</td></tr>`).join("")}</table>
  <div class="row2" style="margin-top:10px">
    <div><h4 style="margin:4px 0">Project IRR across demand draws</h4><div class="chart small"><canvas id="irr"></canvas></div></div>
    <div><h4 style="margin:4px 0">Cash available for debt service, by year</h4><div class="chart small"><canvas id="dscr"></canvas></div></div>
  </div>
  <p class="src">Grant fixed at ${pct(f.grant_share_used)} of CAPEX (${usd(f.grant_usd)}) for all three options. Debt: ${a.debt_tenor}-yr annuity at ${pct(a.debt_rate)} with ${a.debt_grace_years}-yr grace, covenant DSCR ${a.dscr_covenant}. Benchmarks from AMDA 2024: CAPEX $${fmt(f.capex_per_kwp_usd)}/kWp, OPEX $${f.opex_per_customer_usd_yr}/customer/yr, tariff $${f.region_tariff_usd_kwh}/kWh. Team assumptions: performance ratio ${a.performance_ratio}, battery DoD ${a.battery_dod}, collection ${pct(a.collection_rate)}, ${a.life_years}-yr life. Household bill at P50: $${(f.affordability.hh_bill_usd_month || 0).toFixed(2)}/month vs AMDA residential ARPU $${f.affordability.amda_residential_arpu_usd_month}.</p>
  </div>`;
}

function drawFinance(f) {
  const edges = Array.from({ length: 28 }, (_, i) => -20 + i * 2.5);
  mk("irr", { type: "bar", data: { labels: edges.map(e => e.toFixed(0) + "%"), datasets: [{ label: "share of draws", data: f.irr_histogram, backgroundColor: edges.map(e => e + 1.25 < 100 * f.assumptions.hurdle_irr ? C.accent : C.teal) }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 8 }, title: { display: true, text: "project IRR (orange: below hurdle)" } }, y: { display: false } } } });
  const cf = f.cfads_by_year, yrs = cf.p50.map((_, i) => "Y" + (i + 1));
  mk("dscr", { type: "bar", data: { labels: yrs, datasets: [
    { label: "P90 demand", data: cf.p90, backgroundColor: C.ink },
    { label: "P50 demand", data: cf.p50, backgroundColor: C.accent },
    { label: "P10 demand", data: cf.p10, backgroundColor: C.band }] },
    options: { plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${usd(c.raw)}` } } }, scales: { y: { ticks: { callback: v => usd(v) } } } } });
}

async function runBureauDemo(r) {
  const btn = $("#bureauBtn"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Updating with metered months…';
  try { const u = await get(`/api/sites/${r.site.site_id}/bureau-demo?months=6`); renderReport(u, r.headline); }
  catch (e) { btn.textContent = "Update failed: " + e.message; }
}

/* ---------------- validation ---------------- */
async function renderValidation() {
  const el = $("#valpage"); if (el.dataset.done) return;
  let v; try { v = await get("/api/validation"); } catch (e) { el.innerHTML = `<div class="flag">Validation results unavailable: ${esc(e.message)}</div>`; return; }
  const R = v.results, s = R.summary.village_sites, a = R.summary.all_sites, E = R.summary.end_to_end_village || {};
  const siteRows = Object.entries(R.sites).map(([n, x]) => {
    const yrs = x.day0.years || [];
    return `<tr><td><b>${n}</b><br><span class="src">${esc(R.notes[n] || "")}</span></td><td class="n">${x.months_observed}</td><td class="n">${pct(x.day0.wape)}</td><td class="n">${pct(x.day0.coverage_p90_p10)}</td>
      <td>${yrs.map(y => `Y${y.year}: ${y.error >= 0 ? "+" : ""}${pct(y.error)} ${y.inside_band ? "✓ in band" : "✗ outside"}`).join("<br>")}</td>
      <td class="n">${pct(x.learning["6"].wape)} / ${pct(x.learning["6"].baseline_persistence_wape)}</td><td class="n">${pct(x.learning["12"].wape)} / ${pct(x.learning["12"].baseline_persistence_wape)}</td></tr>`;
  }).join("");
  el.innerHTML = `<h1>Validation against real metered mini-grids</h1>
  <p>The organisers confirmed that no partner meter data is available for this brief, so we found a public one: monthly metered connections and consumption from three mini-grids in North Kivu, DRC, 2019–2024 (<a href="https://doi.org/10.7910/DVN/KPDREF" target="_blank">Lunanga, Stoop, Verpoorten & Desbureaux 2026, CC0</a>). Each site is forecast <b>leave-one-site-out</b>: growth shapes come from the other sites, consumption levels from pan-African AMDA benchmarks, and none of the held-out site's meter data is used.</p>
  <div class="card" style="border-color:var(--accent)"><h3>Headline test: open data only, held-out sites</h3>
    <p class="lede">The full pipeline a developer would use: building footprints and OpenStreetMap for the two village-scale sites, no census, no site meters. Footprint-to-customer ratios and growth shapes are taken from the <i>other</i> sites only.</p>
    <div class="grid4">
      <div class="kpi main"><div class="l">Site-years inside P90–P10</div><div class="v">${pct(E.annual_coverage)}</div><div class="s">${E.n_site_years} village site-years, target 80%</div></div>
      <div class="kpi"><div class="l">Months inside P90–P10</div><div class="v">${pct(E.monthly_coverage)}</div><div class="s">individual metered months</div></div>
      <div class="kpi"><div class="l">Year-3 error (sizing year)</div><div class="v">${R.end_to_end ? Object.values(R.end_to_end).map(e => pct(e.years.find(y => y.year === 3)?.error)).join(" / ") : "n/a"}</div><div class="s">${Object.keys(R.end_to_end || {}).join(" / ")}, P50 vs metered</div></div>
      <div class="kpi"><div class="l">Annual error, years 1–3</div><div class="v">${pct(E.annual_abs_error)}</div><div class="s">mean absolute, P50 vs metered</div></div>
    </div>
    <img src="/docs-static/validation/drc_end_to_end.png" alt="Open-data-only forecasts vs metered actuals for Lubero and Mutwanga" style="width:100%;margin-top:10px;border:1px solid var(--line);border-radius:4px">
    <p class="src">Reference points, measured differently: survey-based estimates miss individual customers by 65% (CrossBoundary Innovation Lab); site-level machine learning trained on many metered sites reached 37% per site (Allee et al., Tanzania). Two sites is method validation, not proof.</p></div>
  <div class="card"><h3>Ablation: census customer counts instead of footprints, without anchors and drivers</h3>
    <div class="grid4">
      <div class="kpi"><div class="l">Village site-years inside band</div><div class="v">${pct(s.day0_annual_coverage)}</div><div class="s">${s.n_site_years} site-years</div></div>
      <div class="kpi"><div class="l">Months inside band</div><div class="v">${pct(s.day0_coverage)}</div><div class="s">village sites</div></div>
      <div class="kpi"><div class="l">Annual error</div><div class="v">${pct(s.day0_annual_abs_error)}</div><div class="s">years 1–3</div></div>
      <div class="kpi"><div class="l">Flat desk estimate</div><div class="v">${pct(s.baseline_flat_annual_abs_error)}</div><div class="s">census × benchmark kWh, no range</div></div>
    </div>
    <p class="lede" style="margin-top:10px">Left: day 0, no site data. Middle and right: after the operator shares 6 or 12 metered months (Demand Bureau update).</p>
    <img src="/docs-static/validation/drc_backtest.png" alt="Backtest charts for Goma, Lubero and Mutwanga" style="width:100%;border:1px solid var(--line);border-radius:4px"></div>
  <div class="card"><h3>Per site</h3><table class="t"><tr><th>Site</th><th class="n">Months</th><th class="n">Day-0 monthly error</th><th class="n">Day-0 monthly coverage</th><th>Day-0 annual energy error</th><th class="n">After 6 mo: model / persistence</th><th class="n">After 12 mo: model / persistence</th></tr>${siteRows}</table></div>
  <div class="card"><h3>What this does and does not show</h3>
    <ul>
      <li><b>The range is calibrated:</b> before a site is built, Lodestar's P90–P10 band contained the metered annual energy in ${pct(E.annual_coverage)} of village site-years using open data alone. This is the property a lender needs from a P90.</li>
      <li><b>The point forecast is close to, not clearly better than, a simple benchmark.</b> A flat desk estimate that needs a census (which a developer rarely has) had ${pct(s.baseline_flat_annual_abs_error)} annual error on these sites against ${pct(E.annual_abs_error)} for open-data Lodestar. It gives no range and missed urban Goma by ${pct(R.sites.Goma.baseline_flat_wape)}. We report it rather than hide it.</li>
      <li><b>Learning from meters is limited by shocks.</b> After 6 months of data, error on the village sites changes from ${pct(s.day0_wape)} to ${pct(s.after_6m_wape)} (persistence ${pct(s.persistence_after_6m_wape)}). After 12 months, regime shifts (Mutwanga's conflict collapse, Lubero's late uptake surge) make simple persistence the better predictor (${pct(s.persistence_after_12m_wape)} vs ${pct(s.after_12m_wape)}). The fix is more sites, which is what the Demand Bureau is for.</li>
      <li><b>Three sites is method validation, not proof.</b> Every forecast Lodestar issues is pre-registered in the <a href="#ledger" onclick="showTab('ledger')">forecast ledger</a> and scored when meters report.</li>
    </ul>
    <p class="src">All sites (including urban Goma): day-0 annual error ${pct(a.day0_annual_abs_error)}, coverage ${pct(a.day0_annual_coverage)}. Full numbers: <a href="/api/validation" target="_blank">/api/validation</a>. Reproduce: <code>python scripts/validate_drc.py</code>.</p></div>`;
  el.dataset.done = 1;
}

/* ---------------- bureau ---------------- */
function renderBureau() {
  const el = $("#bureaupage"); if (el.dataset.done) return;
  const opts = sites.map(s => `<option value="${s.site_id}">${esc(s.name)} (${s.country})</option>`).join("");
  el.innerHTML = `<h1>The Demand Bureau: safe meter-data sharing between operators</h1>
  <p>Credit bureaus solved a similar problem for lenders: no one shares data alone, but everyone gains when everyone does. The Demand Bureau applies that <b>give-to-get</b> model to mini-grid meters. Operators contribute site-month aggregates. In return they get regional benchmarks and sharper forecasts for their own pipeline, and lenders get calibrated P90s.</p>
  <div class="row2">
    <div class="card"><h3>What is shared</h3><p class="lede">Site-month aggregates only. No customer-level data, no names, no meter IDs.</p>
<pre>site_hash, country, admin1, months_since_cod,
conn_household, conn_sme,
kwh_per_household, kwh_per_sme,
tariff_usd_kwh, outage_hours        (optional)</pre>
    <ul><li><b>k-anonymous release:</b> a regional benchmark is published only when it pools at least 3 sites from at least 2 operators.</li>
    <li><b>Federated option:</b> the model is parametric, so an operator can share only fitted growth parameters and their uncertainty, never the series. The bureau pools them hierarchically.</li>
    <li><b>Steward:</b> a neutral sector body (for example AMDA, which already runs member benchmarking), with a data-pooling clause in results-based-financing grant agreements to seed it.</li></ul></div>
    <div class="card"><h3>Try it</h3><p class="lede">Upload metered site-months in the schema on the left. The forecast is re-weighted (Bayesian importance sampling) and the band narrows.</p>
      <label>Site <select id="bsite">${opts}</select></label>
      <p><input type="file" id="bfile" accept=".csv"> <button class="btn primary" id="bgo">Update forecast</button></p>
      <p class="src">Sample files with <b>real</b> metered months (DRC validation sites): <a href="/api/sites/cd-nk-mutwanga/bureau-sample.csv?months=6">Mutwanga, first 6 months</a> · <a href="/api/sites/cd-nk-lubero/bureau-sample.csv?months=6">Lubero, first 6 months</a></p>
      <div id="bout"></div></div>
  </div>
  <div class="card"><h3>Why operators join</h3><table class="t">
    <tr><th>Operator gives</th><th>Operator gets</th></tr>
    <tr><td>Monthly aggregates for their sites</td><td>Benchmarks against peers in their region; forecast bands for new sites that are narrower than the pan-African default</td></tr>
    <tr><td>Nothing customer-identifiable</td><td>A lender-readable P90 for each new site, which lowers their cost of capital</td></tr></table>
    <p class="src">Results-based-financing programmes already verify metered connections before they pay out, so pooling anonymised aggregates adds one clause, not a new data system. (To be confirmed with each programme.)</p></div>`;
  $("#bgo").onclick = async () => {
    const f = $("#bfile").files[0], sid = $("#bsite").value; if (!f) { alert("Choose a CSV file first"); return; }
    const fd = new FormData(); fd.append("file", f);
    $("#bout").innerHTML = '<span class="spinner"></span>Updating…';
    const r = await fetch(`/api/sites/${sid}/bureau`, { method: "POST", body: fd });
    if (!r.ok) { $("#bout").innerHTML = `<div class="flag">${esc(await r.text())}</div>`; return; }
    const u = await r.json(); const p = u.prior_headline, h = u.headline;
    $("#bout").innerHTML = `<div class="narrow">Year-3 P90–P10: ${mwh(p.p90)}–${mwh(p.p10)} → <b>${mwh(h.p90)}–${mwh(h.p10)} MWh/month</b>. P50 ${mwh(p.p50)} → <b>${mwh(h.p50)}</b>. <a href="#" id="bview">Open the updated report →</a></div>`;
    $("#bview").onclick = e => { e.preventDefault(); current = sid; showTab("explore"); currentReport = u; renderReport(u, p); };
  };
  el.dataset.done = 1;
}

/* ---------------- ledger ---------------- */
async function renderLedger() {
  const el = $("#ledgerpage"); const L = await get("/api/ledger");
  el.innerHTML = `<h1>Forecast ledger</h1>
  <p>Weather forecasters and clinical-trial registries earn trust the same way: commit to the prediction <i>before</i> the outcome is known, then score it in public. Every forecast Lodestar issues is hashed and timestamped here. When the site's meters report, the forecast is scored against them automatically (the DRC backtest shows the scoring).</p>
  <div class="card"><table class="t"><tr><th>Forecast ID</th><th>Issued (UTC)</th><th>Site</th><th class="n">Year-3 P90</th><th class="n">P50</th><th class="n">P10</th><th>Status</th></tr>
  ${L.map(x => `<tr><td><code>${x.forecast_id}</code></td><td>${esc(x.issued_at)}</td><td><a href="#explore/${x.site_id}" onclick="openSite('${x.site_id}');return false">${esc(x.name)}</a></td><td class="n">${mwh(x.y3_p90)}</td><td class="n">${mwh(x.y3_p50)}</td><td class="n">${mwh(x.y3_p10)}</td><td>${esc(x.status)}</td></tr>`).join("")}</table>
  <p class="src">MWh/month. The ID is the first 16 hex characters of the SHA-256 of the site and its forecast numbers.</p></div>`;
}

/* ---------------- method ---------------- */
function renderMethod() {
  const el = $("#methodpage"); if (el.dataset.done) return;
  el.innerHTML = `<h1>Method</h1>
  <div class="card"><h3>1 · Demand is connections × consumption, and both grow</h3>
  <p>Site energy in month <i>t</i> after commissioning is the sum over segments (households, businesses) of connected customers × kWh per connection, plus anchor loads:</p>
<pre>E(t) = Σ_s  N_s · R_s / (1 + e^(−k_s (t − t0_s)))  ×  Q_s · (1 − a_s · e^(−t / τ_s))  +  anchors</pre>
  <p>N comes from building footprints. The uptake ceiling R, ramp k, t0 and appliance-acquisition shape a, τ are fitted on metered mini-grids. The mature consumption level Q comes from AMDA 2024 regional benchmarks. Splitting growth into connections × consumption matters: in the DRC data, one site went from 49 to 10,007 household connections while use per household rose from 6.5 to 50 kWh/month. Another connected fast but stayed flat.</p></div>
  <div class="card"><h3>2 · Uncertainty is Monte Carlo, calibrated on held-out sites</h3>
  <p>20,000 parameter draws per site. The prior spreads are floored so that leave-one-site-out coverage of the P90–P10 band is about 80%. P90/P50/P10 follow the project-finance convention used in solar energy-yield reports.</p></div>
  <div class="card"><h3>3 · Learning from meters (Demand Bureau)</h3>
  <p>Shared metered months re-weight the draws. For each connection or consumption block, the level is integrated out analytically (Gaussian conjugate in log space) and the shape draws are importance-weighted and resampled, with tempering if the effective sample size collapses.</p></div>
  <div class="card"><h3>4 · From demand to a bankable system</h3>
  <p>Hourly shapes come from the RAMP SSA archetypes (households, schools, health facilities). The PV is sized on the worst-month irradiance from NASA POWER, the battery on night-time energy, and CAPEX, OPEX and tariff on AMDA 2024 benchmarks. Every draw runs through a 20-year cash flow, giving the IRR distribution, DSCR by year, the grant needed, and the debt that stays safe on P90 demand.</p></div>
  <div class="card"><h3>Open data used</h3><table class="t">
  <tr><td>Building footprints</td><td>VIDA merge of Google, Microsoft and OSM Open Buildings (source.coop), CC-BY-4.0 / ODbL</td></tr>
  <tr><td>Schools, clinics, markets, mills, roads</td><td>OpenStreetMap contributors, ODbL</td></tr>
  <tr><td>Grid lines</td><td>GridFinder (Arderne et al. 2020), CC-BY-4.0</td></tr>
  <tr><td>Solar resource</td><td>NASA POWER climatology</td></tr>
  <tr><td>Load shapes</td><td>RAMP SSA archetypes (Stevanato 2026, doi:10.5281/zenodo.22832973), CC-BY-4.0</td></tr>
  <tr><td>Benchmarks</td><td>AMDA, Benchmarking Africa's Minigrids 2024</td></tr>
  <tr><td>Metered validation data</td><td>Lunanga, Stoop, Verpoorten & Desbureaux (2026), doi:10.7910/DVN/KPDREF, CC0</td></tr></table>
  <p class="src">No language model generates any number or text in the reports. The lender memo is a deterministic template filled from the model output. Runs on a laptop; the whole stack is open source and can be self-hosted.</p></div>`;
  el.dataset.done = 1;
}

initMap();
loadSites();
const t0 = location.hash.replace("#", "").split("/")[0];
if (["validation", "bureau", "ledger", "method"].includes(t0)) showTab(t0);
