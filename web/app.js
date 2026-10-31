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
  if (t === "impact") renderImpact();
  if (t === "portfolio") renderPortfolio();
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
      <a class="btn" href="/api/sites/${r.site.site_id}/pack.zip" title="Memo, report, load file and SMS summary for use without internet">Offline pack</a>
    </div></div>
  ${flags.map(w => `<div class="flag">${esc(w)}</div>`).join("")}
  <div class="headline">
    <div class="kpi main"><div class="l">Year-3 demand · P50</div><div class="v">${mwh(h.p50)} <small style="font-size:15px">MWh/mo</small></div><div class="s">Confidence: <b>${h.confidence}</b> · P10/P90 = ${h.p10_over_p90.toFixed(1)}×</div></div>
    <div class="kpi"><div class="l">P90 · conservative</div><div class="v">${mwh(h.p90)}</div><div class="s">exceeded with 90% probability</div></div>
    <div class="kpi"><div class="l">P10 · optimistic</div><div class="v">${mwh(h.p10)}</div><div class="s">exceeded with 10% probability</div></div>
    <div class="kpi"><div class="l">Peak load · P50</div><div class="v">${fmt(r.load_profile.peak_kw)} kW</div><div class="s">load factor ${pct(r.load_profile.load_factor)}</div></div>
  </div>
  ${r.update ? (() => { const ch = 1 - (h.p10 / h.p90) / (prior.p10 / prior.p90); return `<div class="narrow"><b>Updated with ${r.update.months_used} metered months.</b> Year-3 band P90–P10: ${mwh(prior.p90)}–${mwh(prior.p10)} → <b>${mwh(h.p90)}–${mwh(h.p10)} MWh/month</b>; P50 ${mwh(prior.p50)} → <b>${mwh(h.p50)}</b>. ${ch > 0 ? `Relative band width ${pct(ch)} narrower.` : `The band stays wide: early months alone cannot yet tell a slow ramp from a low ceiling.`}</div>`; })() : ""}
  ${r.basis ? `<div class="card"><h3>How this forecast was made</h3>
    <ol class="small" style="margin:6px 0 4px;padding-left:20px">${r.basis.steps.map(s => `<li><b>${esc(s.title)}.</b> ${esc(s.text)}</li>`).join("")}</ol>
    <details class="small"><summary style="cursor:pointer">Inputs, sources and how current they are</summary>
      <table class="t" style="margin-top:6px"><tr><th>Input</th><th>This site</th><th>Source</th><th>As of</th></tr>
      ${r.basis.inputs.map(i => `<tr><td>${esc(i.label)}</td><td>${esc(i.value)}</td><td>${esc(i.source)}</td><td>${esc(i.as_of || "")}</td></tr>`).join("")}</table>
      <p class="src">Site data fetched ${esc((r.basis.site_data_fetched_at || "").slice(0, 10))}${r.basis.site_data_age_days != null ? ` (${r.basis.site_data_age_days} days ago)` : ""}. Service-wide accuracy and freshness: <a href="#ledger" onclick="showTab('ledger');return false">Track record</a>.</p></details></div>` : ""}
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
    <div class="kpi"><div class="l">Tariff needed with RBF grant</div><div class="v">$${f.tariff_with_rbf_usd_kwh.toFixed(2)}</div><div class="s">per kWh with $${f.rbf_benchmark_per_connection_usd[1]}/connection (Nigeria NEP), vs $${f.region_tariff_usd_kwh.toFixed(2)} regional average; $${f.required_tariff_usd_kwh.toFixed(2)} with no grant</div></div>
  </div>
  <h4 style="margin:14px 0 4px">Sizing options</h4>
  <table class="t"><tr><th>Size the system on</th><th class="n">PV kWp</th><th class="n">Battery kWh</th><th class="n">CAPEX</th><th class="n">Cost of power</th><th class="n">IRR at P50</th><th class="n">Unserved energy, median</th><th class="n">Unserved if P10</th><th class="n">Breach risk, P50 debt</th></tr>
  ${[["p90", "P90 demand (undersize risk)"], ["p50", "P50 demand (recommended, modular)"], ["p10", "P10 demand (oversize risk)"]].map(([k, lab]) =>
    `<tr class="${k === f.recommended ? "rec" : ""}"><td>${lab}</td><td class="n">${fmt(o[k].pv_kwp)}</td><td class="n">${fmt(o[k].battery_kwh)}</td><td class="n">${usd(o[k].capex_usd)}</td><td class="n">$${o[k].cost_of_power_usd_kwh.toFixed(2)}/kWh</td><td class="n">${pct(o[k].irr_p50, 1)}</td><td class="n">${pct(o[k].unserved_share_median)}</td><td class="n">${pct(o[k].unserved_share_p10_demand)}</td><td class="n">${pct(o[k].prob_dscr_breach_if_p50_debt)}</td></tr>`).join("")}</table>
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
  <div class="card"><h3>Learning from shared meters, and an ablation with census counts</h3>
    <div class="grid4">
      <div class="kpi"><div class="l">Village site-years inside band</div><div class="v">${pct(s.day0_annual_coverage)}</div><div class="s">${s.n_site_years} site-years</div></div>
      <div class="kpi"><div class="l">Months inside band</div><div class="v">${pct(s.day0_coverage)}</div><div class="s">village sites</div></div>
      <div class="kpi"><div class="l">Annual error</div><div class="v">${pct(s.day0_annual_abs_error)}</div><div class="s">years 1–3</div></div>
      <div class="kpi"><div class="l">Flat desk estimate</div><div class="v">${pct(s.baseline_flat_annual_abs_error)}</div><div class="s">census × benchmark kWh, no range</div></div>
    </div>
    <p class="lede" style="margin-top:10px">All three sites. Left: day 0, no site meter data (villages: open data only; Goma: census). Middle and right: after the operator shares 6 or 12 metered months (Demand Bureau update).</p>
    <img src="/docs-static/validation/drc_backtest.png" alt="Backtest charts for Goma, Lubero and Mutwanga" style="width:100%;border:1px solid var(--line);border-radius:4px"></div>
  <div class="card"><h3>Per site (census-count variant, all three sites)</h3><table class="t"><tr><th>Site</th><th class="n">Months</th><th class="n">Day-0 monthly error</th><th class="n">Day-0 monthly coverage</th><th>Day-0 annual energy error</th><th class="n">After 6 mo: model / persistence</th><th class="n">After 12 mo: model / persistence</th></tr>${siteRows}</table></div>
  <div class="card"><h3>What this does and does not show</h3>
    <ul>
      <li><b>The range is calibrated:</b> before a site is built, Lodestar's P90–P10 band contained the metered annual energy in ${pct(E.annual_coverage)} of village site-years using open data alone. This is the property a lender needs from a P90.</li>
      <li><b>The point forecast is close to, not clearly better than, a simple benchmark.</b> A flat desk estimate that needs a census (which a developer rarely has) had ${pct(s.baseline_flat_annual_abs_error)} annual error on these sites against ${pct(E.annual_abs_error)} for open-data Lodestar. It gives no range and missed urban Goma by ${pct(R.sites.Goma.baseline_flat_wape)}. We report it rather than hide it.</li>
      <li><b>Learning from meters helps early, and shocks still win.</b> When an operator shares its first 6 metered months, error on the following months falls from ${pct(E.wape)} to ${pct(E.after_6m_wape)} with ${pct(E.after_6m_coverage)} band coverage, beating "carry the last month forward" (${pct(E.persistence_after_6m_wape)}). After 12 months, Mutwanga's conflict-driven collapse makes persistence better (${pct(E.persistence_after_12m_wape)} vs ${pct(E.after_12m_wape)}). Consecutive metered months are strongly autocorrelated, so the update discounts them by the measured effective sample size instead of treating each month as independent evidence.</li>
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

/* ---------------- impact ---------------- */
async function renderImpact() {
  const el = $("#impactpage"); if (el.dataset.done) return;
  const [v, ec, pf] = await Promise.all([get("/api/validation"), get("/api/economics"), get("/api/portfolio")]);
  const R = v.results, D = R.decision_backtest || {}, S = (R.summary || {}).decision_backtest || {}, E = R.summary.end_to_end_village || {};
  const plan = { desk: "Desk estimate, single build", lodestar: "Lodestar: build at P50, expand on metered demand", hindsight: "Hindsight (perfect knowledge)" };
  const rows = Object.entries(D).map(([site, r]) => Object.entries(plan).map(([k, lab]) => { const x = r[k]; return `<tr class="${k === "lodestar" ? "rec" : ""}"><td>${site}</td><td>${lab}</td><td class="n">${fmt(x.final_kwp)}</td><td class="n">${k === "hindsight" ? "—" : (x.kwp_vs_hindsight_y3 >= 0 ? "+" : "") + pct(x.kwp_vs_hindsight_y3)}</td><td class="n">${usd(x.capex_usd)}</td><td class="n">${pct(x.idle_capacity_share_y3)}</td><td class="n">${pct(x.unserved_share)}</td><td class="n">${fmt(x.diesel_litres)}</td></tr>`; }).join("")).join("");
  const cats = {}; pf.forEach(r => (cats[r.category] ||= []).push(r));
  const a = S.desk || {}, b = S.lodestar || {};
  const cop = pf.reduce((t, r) => t + (1 - r.cost_of_power_usd_kwh / r.cost_of_power_if_p10_usd_kwh), 0) / pf.length;
  el.innerHTML = `<h1>Impact: what better forecasts are worth</h1>
  <p>The brief's metric is forecast error against metered demand (see <a href="#validation" onclick="showTab('validation');return false">Validation</a>: real demand inside our range in ${pct(E.annual_coverage)} of site-years, from open data alone). Here we turn that into decisions, money and people, using the same real meters.</p>
  <div class="grid4">
    <div class="kpi main"><div class="l">Capacity mismatch at year 3</div><div class="v">${pct(1 - b.abs_capacity_gap_kwp / a.abs_capacity_gap_kwp)} less</div><div class="s">${fmt(a.abs_capacity_gap_kwp)} → ${fmt(b.abs_capacity_gap_kwp)} kWp vs hindsight, two metered sites</div></div>
    <div class="kpi"><div class="l">Oversizing caught</div><div class="v">+37% → +6%</div><div class="s">Mutwanga: desk estimate vs Lodestar plan, year-3 capacity vs hindsight</div></div>
    <div class="kpi"><div class="l">Cost of power: right-size vs oversize</div><div class="v">−${pct(cop)}</div><div class="s">building for P50 instead of the optimistic P10, average of the ${pf.length} villages</div></div>
    <div class="kpi"><div class="l">Villages screened</div><div class="v">${pf.length}</div><div class="s">${(cats.shs || []).length} better served by solar home systems; ${(cats.grid || []).length} near the grid</div></div>
  </div>
  <div class="card"><h3>Decision backtest on real metered demand</h3>
    <p class="lede">We replay each site's actual monthly demand (first 36 months) against three plans. <b>Desk:</b> one build sized on a survey-style estimate (households counted × typical uptake × AMDA benchmark use), the status quo the brief describes. <b>Lodestar:</b> build at the open-data P50, then add a 25% module when 6 months of metered demand average over 90% of capacity (max one per year, 3-month lead time). <b>Hindsight:</b> sized on actual year-3 demand.</p>
    <table class="t"><tr><th>Site</th><th>Plan</th><th class="n">PV kWp by year 3</th><th class="n">vs hindsight</th><th class="n">CAPEX</th><th class="n">Idle capacity, year 3</th><th class="n">Unserved energy</th><th class="n">Backup diesel, litres</th></tr>${rows}</table>
    <p class="src">Both sites together: Lodestar's plan cuts the capacity mismatch from ${fmt(a.abs_capacity_gap_kwp)} to ${fmt(b.abs_capacity_gap_kwp)} kWp, idle capital at year 3 from ${usd(a.idle_capital_y3_usd)} to ${usd(b.idle_capital_y3_usd)}, unserved energy from ${fmt(a.unserved_mwh)} to ${fmt(b.unserved_mwh)} MWh; it invests ${usd(b.capex_usd - a.capex_usd)} more in total because it serves Lubero's real demand that the desk estimate missed. Honest trade-off: at Mutwanga, starting at P50 left more demand unserved in year 1 than the oversized desk build. Unserved energy is valued as small-genset diesel (assumption: 3 kWh/litre; 2.68 kg CO₂/litre). Two sites; method illustration, not proof.</p></div>
  <div class="row2">
    <div class="card"><h3>Who gains</h3><ul class="small">
      <li><b>Households and businesses</b> get a system sized to them: oversizing to the optimistic case roughly doubles the cost of power that ends up in tariffs (each site's sizing table), and undersizing means evening brownouts and diesel.</li>
      <li><b>Developers and lenders</b> get a range they can lend against: debt sized on P50 breaks its covenant about half the time; on P90 it doesn't.</li>
      <li><b>RBF programmes</b> screen settlements before money moves: of ${pf.length} villages here, ${(cats.shs || []).length} are solar-home-system territory, ${(cats.grid || []).length} are near the grid, ${(cats.anchor || []).length} need an anchor load and ${(cats.rbf || []).length} ${(cats.rbf || []).length === 1 ? "is" : "are"} bankable with a Nigeria-style $600/connection grant (<a href="#portfolio" onclick="showTab('portfolio');return false">Portfolio</a>).</li></ul></div>
    <div class="card"><h3>Environment</h3><ul class="small">
      <li><b>No stranded hardware:</b> at Mutwanga the desk plan would have installed ${fmt(D.Mutwanga ? D.Mutwanga.desk.final_kwp - D.Mutwanga.hindsight.final_kwp : 0)} kWp of PV (plus batteries) that year-3 demand did not need; Lodestar's plan ${fmt(D.Mutwanga ? D.Mutwanga.lodestar.final_kwp - D.Mutwanga.hindsight.final_kwp : 0)} kWp.</li>
      <li><b>Less backup diesel when undersized:</b> at Lubero the desk build left ${fmt(D.Lubero ? D.Lubero.desk.unserved_mwh : 0)} MWh unserved (~${fmt(D.Lubero ? D.Lubero.desk.co2_t : 0)} t CO₂ if met by gensets) vs ${fmt(D.Lubero ? D.Lubero.lodestar.unserved_mwh : 0)} MWh (~${fmt(D.Lubero ? D.Lubero.lodestar.co2_t : 0)} t) with Lodestar's plan.</li>
      <li>Every right-sized solar mini-grid replaces kerosene and diesel; getting more of them financed is the largest effect, and the hardest to measure in 48 hours.</li></ul></div>
  </div>
  <div class="card"><h3>Lodestar's own economics: it pays for itself</h3>
    <div class="grid4">
      <div class="kpi"><div class="l">Compute per forecast</div><div class="v">${ec.measured.seconds_per_report.toFixed(2)} s</div><div class="s">measured; ≈ $${ec.measured.compute_usd_per_report.toFixed(5)} of cloud CPU · ${ec.measured.report_kb_gzip.toFixed(1)} KB per report</div></div>
      <div class="kpi"><div class="l">Break-even</div><div class="v">${fmt(ec.break_even_reports_yr)} reports/yr</div><div class="s">or ${ec.break_even_mix.portfolio_subscriptions} RBF subscriptions + ${fmt(ec.break_even_mix.reports)} reports · ${pct(ec.break_even_share_of_amda_pipeline, 1)} of AMDA members' planned sites</div></div>
      <div class="kpi"><div class="l">Price of a report</div><div class="v">${pct(ec.report_price_share_of_minigrid_cost, 2)}</div><div class="s">of an average mini-grid's cost (${usd(ec.avg_minigrid_cost_usd)}, ESMAP $127B / 217k)</div></div>
      <div class="kpi"><div class="l">Data and licences</div><div class="v">$0</div><div class="s">open data, open source, no API keys; runs on a laptop</div></div>
    </div>
    <p class="src">Proposed prices: $${ec.proposed_prices.report_usd} per Bankable Demand Report (developers, lenders), $${fmt(ec.proposed_prices.portfolio_usd_yr)}/yr portfolio screening (RBF programmes, DFIs); single-site forecasts stay free. Assumed costs: two analyst-engineers in Nairobi or Lagos ($${fmt(ec.assumed_costs.team_usd_yr)}/yr) plus hosting ($${fmt(ec.assumed_costs.hosting_usd_yr)}/yr). Pipeline: AMDA members plan ${fmt(ec.pipeline.amda_planned_sites)} sites; Nigeria's DARES targets ${fmt(ec.pipeline.dares_target_sites)}+; ESMAP estimates ${fmt(ec.pipeline.esmap_needed_minigrids)} needed. Maintained locally: Python on a laptop, quarterly re-fit as Demand Bureau data arrives, no GPU.</p></div>`;
  el.dataset.done = 1;
}

/* ---------------- portfolio + SMS ---------------- */
async function renderPortfolio() {
  const el = $("#portfoliopage"); if (el.dataset.done) return;
  const pf = await get("/api/portfolio");
  const order = { rbf: 0, anchor: 1, grid: 2, shs: 3 };
  pf.sort((a, b) => order[a.category] - order[b.category] || b.y3_p50 - a.y3_p50);
  const cnt = c => pf.filter(r => r.category === c).length;
  el.innerHTML = `<h1>Portfolio screener</h1>
  <p>For a results-based-financing programme or DFI: every settlement forecast the same way, ranked by what it should get. ${pf.length} villages, ${(pf.length * 0.76).toFixed(0)} CPU-seconds in total; the 1,000-site Nigerian DARES pipeline would take minutes.</p>
  <div class="grid4">
    <div class="kpi"><div class="l"><span class="cat rbf">Mini-grid, bankable with RBF</span></div><div class="v">${cnt("rbf")}</div><div class="s">tariff with a $600/connection grant ≤ regional average</div></div>
    <div class="kpi"><div class="l"><span class="cat anchor">Mini-grid, needs anchor load</span></div><div class="v">${cnt("anchor")}</div><div class="s">add a mill, clinic or appliance financing first</div></div>
    <div class="kpi"><div class="l"><span class="cat shs">Solar home systems</span></div><div class="v">${cnt("shs")}</div><div class="s">&lt;100 connections or below MTF Tier 2 (6 kWh/month)</div></div>
    <div class="kpi"><div class="l"><span class="cat grid">Check grid extension</span></div><div class="v">${cnt("grid")}</div><div class="s">within 5 km of a mapped line (GridFinder)</div></div>
  </div>
  <div class="card"><table class="t"><tr><th>Village</th><th>Recommendation</th><th class="n">Y3 P50 MWh/mo</th><th class="n">P90–P10</th><th class="n">Connections</th><th class="n">kWh per conn.</th><th class="n">CAPEX at P50</th><th class="n">Tariff with RBF</th><th></th></tr>
  ${pf.map(r => `<tr><td><a href="#explore/${r.site_id}" onclick="openSite('${r.site_id}');return false">${esc(r.name)}</a> <span class="src">${esc(r.admin1 || "")}, ${r.country}${r.metered ? " · metered" : ""}</span></td><td><span class="cat ${r.category}">${esc(r.category_label)}</span></td><td class="n">${mwh(r.y3_p50)}</td><td class="n">${mwh(r.y3_p90)}–${mwh(r.y3_p10)}</td><td class="n">${fmt(r.connections_y3)}</td><td class="n">${fmt(r.kwh_per_connection, 1)}</td><td class="n">${usd(r.capex_usd)}</td><td class="n">$${r.tariff_with_rbf_usd_kwh.toFixed(2)}</td><td><a class="src" href="/api/sms?site=${r.site_id}" target="_blank">SMS</a></td></tr>`).join("")}</table>
  <p class="src">Download: <a href="/api/portfolio" target="_blank">portfolio JSON</a>. Regional average tariffs from AMDA 2024 ($0.25 West & Central, $0.40 East & Southern).</p></div>
  <div class="row2">
    <div class="card"><h3>In the field, on any phone</h3>
      <p class="lede">Field officers and community energy committees rarely have laptops or steady data. Lodestar answers over <b>USSD</b> and <b>SMS</b>: a forecast fits in one 160-character text. Try the USSD menu: the phone on the right calls the real <code>/ussd</code> endpoint, which follows the Africa's Talking callback format (not yet connected to a live short code).</p>
      <p class="lede"><b>Offline:</b> every site has an <i>Offline pack</i> (memo that opens without internet, report, 8760 load file, SMS summary; about 12 KB zipped). A full report is about 6 KB, so the app works on 2G.</p>
      <p class="src">SMS example: <code id="smsx">…</code></p></div>
    <div class="card" style="display:flex;justify-content:center"><div class="phone"><div class="scr" id="ussdscr">Dial *384*1#</div>
      <div class="keys">${["1", "2", "3", "4", "5", "6", "7", "8", "9"].map(k => `<button data-k="${k}">${k}</button>`).join("")}<button data-k="call" style="grid-column:span 2;background:#2a7d6e;color:#fff">Call *384*1#</button><button data-k="end" style="background:#9a4523;color:#fff">End</button></div></div></div>
  </div>`;
  fetch("/api/sms?site=" + (pf.find(r => r.category === "rbf") || pf[0]).site_id).then(r => r.text()).then(t => $("#smsx").textContent = t);
  let path = [];
  const send = async () => {
    const body = new URLSearchParams({ sessionId: "demo", serviceCode: "*384*1#", phoneNumber: "", text: path.join("*") });
    const t = await (await fetch("/ussd", { method: "POST", body })).text();
    $("#ussdscr").textContent = t.replace(/^(CON|END) /, "");
    if (t.startsWith("END")) path = null;
  };
  el.querySelectorAll(".phone button").forEach(b => b.onclick = () => {
    const k = b.dataset.k;
    if (k === "call") { path = []; send(); return; }
    if (k === "end") { path = null; $("#ussdscr").textContent = "Dial *384*1#"; return; }
    if (path === null) return;
    path.push(k); send();
  });
  el.dataset.done = 1;
}

/* ---------------- ledger ---------------- */
async function renderLedger() {
  const el = $("#ledgerpage");
  const [L, M] = await Promise.all([get("/api/ledger"), get("/api/metrics")]);
  const A = M.accuracy, T = M.track_record;
  el.innerHTML = `<h1>Track record</h1>
  <p>A forecasting service should be judged on its record, not its claims. These are the numbers we track and publish: how accurate the forecasts have been against real meters, every forecast we have issued, and how current each data input is.</p>
  <div class="grid4">
    <div class="kpi main"><div class="l">Real demand inside our range</div><div class="v">${pct(A.annual_coverage_p90_p10)}</div><div class="s">${A.n_site_years} site-years, target ${pct(A.target_coverage)} · ${pct(A.monthly_coverage_p90_p10)} of months</div></div>
    <div class="kpi"><div class="l">Forecast error (P50, annual)</div><div class="v">${pct(A.annual_abs_error_p50)}</div><div class="s">year 3: ${Object.entries(A.y3_error_by_site).map(([n, e]) => `${n} ${e >= 0 ? "+" : ""}${pct(e)}`).join(", ")}</div></div>
    <div class="kpi"><div class="l">Error after 6 metered months</div><div class="v">${pct(A.after_6m_meters_error)}</div><div class="s">vs ${pct(A.persistence_after_6m_error)} for "carry the last month forward"</div></div>
    <div class="kpi"><div class="l">Forecasts issued</div><div class="v">${T.forecasts_issued}</div><div class="s">${T.pre_registered_awaiting_meters} awaiting meters · ${T.scored_ledger_forecasts} scored · ${T.superseded} superseded</div></div>
  </div>
  <p class="src">${esc(A.method)}. Last validated ${esc((A.last_validated || "").slice(0, 16).replace("T", " "))} UTC. Model ${esc(M.model.version)}.</p>
  <div class="card"><h3>Data freshness</h3><p class="lede">Every input has a refresh target. "Due" means it is older than its target and the next model release should update it.</p>
    <table class="t"><tr><th>Input</th><th>Source</th><th>As of</th><th class="n">Age</th><th class="n">Refresh every</th><th>Status</th></tr>
    ${M.freshness.map(f => `<tr><td>${esc(f.input)}</td><td>${esc(f.source)}</td><td>${esc(f.as_of || "")}</td><td class="n">${f.age_days == null ? "n/a" : f.age_days < 60 ? f.age_days + " days" : (f.age_days / 365).toFixed(1) + " yrs"}</td><td class="n">${f.refresh_every_days >= 365 ? (f.refresh_every_days / 365).toFixed(0) + " yr" : Math.round(f.refresh_every_days / 30) + " mo"}</td><td><span class="cat ${f.status === "fresh" ? "rbf" : "grid"}">${f.status}</span></td></tr>`).join("")}</table>
    <p class="src">The metered growth curves are the input most in need of refresh: the public panel ends in December 2024. The Demand Bureau is how operators keep it current, each quarter.</p></div>
  <div class="card"><h3>Forecast ledger</h3>
    <p class="lede">Weather forecasters and clinical-trial registries earn trust the same way: commit to the prediction <i>before</i> the outcome is known, then score it in public. Every forecast is hashed and timestamped here and scored when the site's meters report. Replaced forecasts are marked, never deleted.</p>
    <table class="t"><tr><th>Forecast ID</th><th>Issued (UTC)</th><th>Site</th><th class="n">Year-3 P90</th><th class="n">P50</th><th class="n">P10</th><th>Status</th></tr>
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
if (["validation", "bureau", "ledger", "method", "impact", "portfolio"].includes(t0)) showTab(t0);
