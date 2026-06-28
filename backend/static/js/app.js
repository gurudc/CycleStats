// CycleStats App
// ── Auth ───────────────────────────────────────────────────
async function checkAuth() {
  var ls = document.getElementById("login-screen");
  var main = document.querySelector(".main");
  if (!ls || !main) return;
  try {
    var r = await fetch("/api/strava/status", {credentials: "include"});
    if (r.ok) {
      ls.style.display = "none";
      main.style.display = "block";
      initTheme();
      var hash = window.location.hash.replace("#", "");
      showPage(hash || "dashboard");
      return;
    }
  } catch(e) {}
  ls.style.display = "flex";
  main.style.display = "none";
}

async function doLogin() {
  var pw = document.getElementById("login-password");
  var err = document.getElementById("login-error");
  if (!pw.value) { err.textContent = "Enter a password"; return; }
  err.textContent = "";
  try {
    var r = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password: pw.value})
    });
    if (r.ok) {
      pw.value = "";
      checkAuth();
    } else {
      var d = await r.json();
      err.textContent = d.detail || "Invalid password";
    }
  } catch(e) {
    err.textContent = "Connection error";
  }
}

// ── HTML Escape ──────────────────────────────────────────
function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/&/g,"&amp;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

// ── Helpers ────────────────────────────────────────────────
var chartInstances = {};
function destroyChart(id) { if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; } }
function smoothData(arr, w) { w = w || 3; var r = []; for (var i = 0; i < arr.length; i++) { var s = 0, c = 0; for (var j = Math.max(0, i-w+1); j <= i; j++) { s += arr[j] || 0; c++; } r.push(s / c); } return r; }

async function apiGet(path) { var r = await fetch("/api" + path); if (!r.ok) { try { var e = await r.json(); throw Error(e.detail || r.statusText); } catch(er) { throw Error(er.message || "GET " + path + " failed"); } } return r.json(); }
async function apiPost(path, body) { var r = await fetch("/api" + path, { method: "POST", credentials: "include", headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined }); if (!r.ok) { try { var e = await r.json(); throw Error(e.detail || r.statusText); } catch(er) { throw Error(er.message || "POST " + path + " failed"); } } return r.json(); }

function formatTime(t) { if (!t || t <= 0) return "0:00"; var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60); return h > 0 ? h + ":" + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s : m + ":" + (s < 10 ? "0" : "") + s; }
function showLoading(id) { var el = document.getElementById(id); if (el) el.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>Loading...</span></div>'; }
function hideLoading(id) { var el = document.getElementById(id); if (el) el.querySelectorAll(".loading-overlay").forEach(function(o) { o.remove(); }); }

// ── Theme ──────────────────────────────────────────────────
function toggleTheme() { var html = document.documentElement; var isDark = html.getAttribute("data-theme") !== "light"; html.setAttribute("data-theme", isDark ? "light" : "dark"); localStorage.setItem("cyclestats-theme", isDark ? "light" : "dark"); var icon = document.getElementById("theme-icon"); var label = document.getElementById("theme-label"); if (icon) icon.innerHTML = isDark ? "&#9788;" : "&#9790;"; if (label) label.textContent = isDark ? "Light" : "Dark"; }
function initTheme() { var saved = localStorage.getItem("cyclestats-theme") || "dark"; document.documentElement.setAttribute("data-theme", saved); var icon = document.getElementById("theme-icon"); var label = document.getElementById("theme-label"); if (icon) icon.innerHTML = saved === "light" ? "&#9788;" : "&#9790;"; if (label) label.textContent = saved === "light" ? "Light" : "Dark"; }
function toggleSidebar() { document.querySelector(".sidebar").classList.toggle("open"); var ov = document.getElementById("sidebar-overlay"); if (ov) ov.classList.toggle("open"); }
function closeSidebar() { document.querySelector(".sidebar").classList.remove("open"); var ov = document.getElementById("sidebar-overlay"); if (ov) ov.classList.remove("open"); }

// ── Navigation ────────────────────────────────────────────
function showPage(pageName) {
  document.querySelectorAll(".page").forEach(function(p) { p.classList.remove("active"); });
  var target = document.getElementById("page-" + pageName);
  if (target) target.classList.add("active");
  document.querySelectorAll(".nav-item[data-page]").forEach(function(n) { n.classList.remove("active"); if (n.getAttribute("data-page") === pageName) n.classList.add("active"); });
  var dn = document.getElementById("nav-activity-detail");
  if (pageName === "activity-detail") { if (dn) dn.style.display = "block"; } else { if (dn) dn.style.display = "none"; }
  switch (pageName) {
    case "dashboard": loadDashboard(); break;
    case "activities": loadActivities(); break;
    case "health": loadHealth(); break;
    case "segments": loadSegments(); break;
    case "calendar": loadCalendar(); break;
    case "gear": loadGear(); break;
    case "power-curve": loadPowerCurve(); break;
    case "power-profile": loadPowerProfile(); break;
    case "zones": loadZones(); break;
    case "insights": loadInsights(); break;
    case "settings": loadSettings(); break;
  }
}

document.addEventListener("DOMContentLoaded", function() {
  initTheme();
  var ov = document.getElementById("sidebar-overlay");
  if (ov) ov.addEventListener("click", closeSidebar);
  document.querySelectorAll(".nav-item[data-page]").forEach(function(el) {
    if (el.getAttribute("data-page") !== "activity-detail") {
      el.addEventListener("click", function(e) { e.preventDefault(); showPage(this.getAttribute("data-page")); closeSidebar(); });
    }
  });
  showPage("dashboard");
});

// ── Dashboard ─────────────────────────────────────────────
function populateActivitiesList(data, el) {
  if (!data || !data.activities || data.activities.length === 0) { el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)\">No activities. Sync from Strava or upload a file.</div>'; return; }
  var html = "";
  data.activities.forEach(function(a) {
    var meta = a.sport || "Ride";
    if (a.start_time) meta += " &middot; " + new Date(a.start_time).toLocaleDateString();
    html += "<li onclick=\"openActivity(" + a.id + "); showPage('activity-detail')\">" +
      '<div><div class="act-name">' + esc(a.name) || "Activity #" + a.id + '</div><div class="act-meta">' + esc(meta) + '</div></div>' +
      '<div class="act-stats">' + (a.tss ? '<span>' + esc(Math.round(a.tss)) + " TSS</span>" : "") + (a.distance_km ? '<span>' + esc(a.distance_km.toFixed(1)) + " km</span>" : "") + '</div></li>';
  });
  el.innerHTML = html;
}

async function loadDashboard() {
  var statsEl = document.getElementById("dash-stats");
  var actEl = document.getElementById("dash-activities");
  var healthEl = document.getElementById("dash-health");
  if (!statsEl || !actEl || !healthEl) return;
  showLoading("dash-stats"); showLoading("dash-activities"); showLoading("dash-health");
  try {
    var data = await apiGet("/activities/?limit=5");
    if (data && data.activities) populateActivitiesList(data, actEl);
    var total = data ? data.total : 0;
    var health = await apiGet("/health/dashboard");
    var ftp = await apiGet("/training/ftp");
    statsEl.innerHTML =
      '<div class="stat-card"><div class="stat-value">' + total + '</div><div class="stat-label">Activities</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (ftp.ftp || "--") + '</div><div class="stat-label">FTP (W)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (health.avg_hrv_rmssd_7d || "--") + '</div><div class="stat-label">Avg HRV</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (health.avg_sleep_7d || "--") + '</div><div class="stat-label">Avg Sleep (h)</div></div>';
    healthEl.innerHTML =
      '<div class="stat-card"><div class="stat-value">' + (health.avg_resting_hr_7d || "--") + '</div><div class="stat-label">Avg Rest HR</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (health.latest.weight_kg || "--") + '</div><div class="stat-label">Avg Weight</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (health.latest.body_fat_pct || "--") + '</div><div class="stat-label">Body Fat %</div></div>';
  } catch(e) { statsEl.innerHTML = '<div class="stat-card"><div class="stat-value" style="color:red">Error</div><div class="stat-label">' + esc(e.message) + '</div></div>'; }
  try {
    var ins = await apiGet("/training/insights");
    if (ins.insights && ins.insights.length > 0) { var card = document.getElementById("dash-insights-card"); if (card) card.style.display = "block"; renderInsights(ins.insights.slice(0, 3), "dash-insights"); }
  } catch(e) {}
}

// ── Activities ────────────────────────────────────────────
var activitiesPage = 0, activitiesLimit = 50;
var activitiesSearchQ = "", activitiesSearchSport = "", activitiesSearchFrom = "", activitiesSearchTo = "";
async function searchActivities() {
  activitiesSearchQ = (document.getElementById("search-q") || {}).value || "";
  activitiesSearchSport = (document.getElementById("search-sport") || {}).value || "";
  activitiesSearchFrom = (document.getElementById("search-from") || {}).value || "";
  activitiesSearchTo = (document.getElementById("search-to") || {}).value || "";
  activitiesPage = 0; loadActivities();
}
async function loadActivities() {
  var el = document.getElementById("activities-list");
  if (!el) return; showLoading("activities-list");
  try {
    var offset = activitiesPage * activitiesLimit;
    var params = "limit=" + activitiesLimit + "&offset=" + offset;
    if (activitiesSearchQ) params += "&q=" + encodeURIComponent(activitiesSearchQ);
    if (activitiesSearchSport) params += "&sport=" + encodeURIComponent(activitiesSearchSport);
    if (activitiesSearchFrom) params += "&date_from=" + encodeURIComponent(activitiesSearchFrom);
    if (activitiesSearchTo) params += "&date_to=" + encodeURIComponent(activitiesSearchTo);
    var data = await apiGet("/activities/?" + params);
    var total = data.total || 0;
    var html = '';
    (data.activities || []).forEach(function(a) {
      var meta = a.sport || "Ride";
      if (a.start_time) meta += " &middot; " + new Date(a.start_time).toLocaleDateString();
      html += "<li onclick=\"openActivity(" + a.id + "); showPage('activity-detail')\">" +
        '<div><div class="act-name">' + esc(a.name) || "Activity #" + a.id + '</div><div class="act-meta">' + esc(meta) + '</div></div>' +
        '<div class="act-stats">' + (a.tss ? '<span>' + esc(Math.round(a.tss)) + " TSS</span>" : "") + (a.distance_km ? '<span>' + esc(a.distance_km.toFixed(1)) + " km</span>" : "") + '</div>' +
        '<button class="delete-btn" onclick=\"event.stopPropagation(); deleteActivity(' + a.id + ')" style="margin-left:8px">&times;</button></li>';
    });
    // no closing ul needed
    var tp = Math.ceil(total / activitiesLimit);
    html += '<div class="pagination"><button onclick=\"activitiesPage--;loadActivities()" ' + (activitiesPage <= 0 ? "disabled" : "") + '>&#9664; Prev</button>' +
      '<span>Page ' + (activitiesPage + 1) + " of " + tp + '</span>' +
      '<button onclick=\"activitiesPage++;loadActivities()" ' + (activitiesPage >= tp - 1 ? "disabled" : "") + '>Next &#9654;</button></div>';
    el.innerHTML = html;
  } catch(e) { el.innerHTML = '<div class="status-msg error">' + esc(e.message) + "</div>"; }
}
async function deleteActivity(id) { if (!confirm("Delete activity #" + id + "?")) return; try { await apiPost("/activities/delete", { activity_id: id }); loadActivities(); } catch(e) { alert("Error: " + e.message); } }
async function uploadActivity() {
  var fi = document.getElementById("upload-file"), se = document.getElementById("upload-status");
  if (!fi || !fi.files || !fi.files[0]) { se.innerHTML = '<div class="status-msg error">Select a file</div>'; return; }
  var f = fi.files[0], ext = f.name.split(".").pop().toLowerCase();
  if (!["fit","gpx","tcx"].includes(ext)) { se.innerHTML = '<div class="status-msg error">Unsupported: .' + ext + "</div>"; return; }
  se.innerHTML = '<div class="status-msg info">Uploading...</div>';
  try {
    var fd = new FormData(); fd.append("file", f);
    var n = (document.getElementById("upload-name") || {}).value; if (n) fd.append("name", n);
    var s = (document.getElementById("upload-sport") || {}).value; if (s) fd.append("sport", s);
    var r = await fetch("/api/activities/upload", { method: "POST", body: fd });
    if (!r.ok) { var e = await r.json(); throw Error(e.detail || "Upload failed"); }
    se.innerHTML = '<div class="status-msg success">Imported!</div>'; fi.value = ""; loadActivities();
  } catch(e) { se.innerHTML = '<div class="status-msg error">' + esc(e.message) + "</div>"; }
}

// ── Activity Detail ───────────────────────────────────────
async function openActivity(id) {
  document.getElementById("detail-stats").innerHTML = "";
  document.getElementById("gps-map").innerHTML = "";
  ["chart-power","chart-hr","chart-cadence","chart-speed","chart-altitude"].forEach(destroyChart);
  try {
    var a = await apiGet("/activities/" + id + "?streams=true");
    document.getElementById("detail-title").textContent = a.name || ("Activity #" + a.id);
    var tsbV = "";
    try { var pmc = await apiGet("/training/pmc"); if (pmc && pmc.length > 0) tsbV = '<div class="stat-card"><div class="stat-value">' + pmc[pmc.length-1].tsb.toFixed(1) + '</div><div class="stat-label">TSB</div></div>'; } catch(e) {}
    document.getElementById("detail-stats").innerHTML =
      '<div class="stat-card"><div class="stat-value">' + (a.avg_power_w || "--") + '</div><div class="stat-label">Avg Power (W)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.normalized_power_w || "--") + '</div><div class="stat-label">NP (W)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.max_power_w || "--") + '</div><div class="stat-label">Max Power (W)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.avg_heartrate || "--") + '</div><div class="stat-label">Avg HR (bpm)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.avg_cadence || "--") + '</div><div class="stat-label">Avg Cadence</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + ((a.distance_m || 0) / 1000).toFixed(2) + '</div><div class="stat-label">Distance (km)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.elevation_gain_m || "--") + '</div><div class="stat-label">Elevation (m)</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + formatTime(a.moving_time_s || 0) + '</div><div class="stat-label">Moving Time</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.tss || "--") + '</div><div class="stat-label">TSS</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.intensity_factor || "--") + '</div><div class="stat-label">IF</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (a.calories_kcal || "--") + '</div><div class="stat-label">Calories</div></div>' + tsbV;
    var s = a.streams || {}, lat = s.lat || [], lon = s.lon || [], t = s.time || [], d = s.distance || [];
    if (!s.speed && d.length > 0 && t.length > 0) { s.speed = []; for (var si = 0; si < t.length; si++) { if (si === 0) { s.speed.push(0); continue; } var dd = d[si] - d[si-1], td = t[si] - t[si-1]; s.speed.push(td > 0 ? (dd / td) * 3.6 : 0); } }
    // Ride insights card
    var ec = document.getElementById("ride-insights");
    if (!ec) { var cd = document.createElement("div"); cd.className = "card"; cd.id = "ride-insights"; cd.innerHTML = '<h2>Ride Insights</h2><div style="color:var(--text-muted);padding:12px 0;text-align:center;font-size:13px">Loading...</div>'; var mc = document.getElementById("gps-map"); if (mc) mc.parentNode.parentNode.insertBefore(cd, mc.parentNode); }
    var ic = document.getElementById("ride-insights");
    if (ic) {
      if (a.ai_insight) {
        var ti = a.ai_insight.indexOf("|TIP:"), mt = ti >= 0 ? a.ai_insight.substring(0, ti) : a.ai_insight, tp = ti >= 0 ? a.ai_insight.substring(ti + 5) : "";
        var st = '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">';
        if (a.tss) st += '<span class="badge" style="background:#1a3a5c;color:#80d0ff;font-size:12px;padding:4px 10px">TSS ' + a.tss + "</span>";
        if (a.normalized_power_w) st += '<span class="badge" style="background:#1a3a2c;color:#80ffa0;font-size:12px;padding:4px 10px">NP ' + a.normalized_power_w + "W</span>";
        if (a.intensity_factor) st += '<span class="badge" style="background:#5a3a1a;color:#ffc080;font-size:12px;padding:4px 10px">IF ' + a.intensity_factor + "</span>";
        if (a.avg_power_w) st += '<span class="badge" style="background:#3a1a5c;color:#c080ff;font-size:12px;padding:4px 10px">AP ' + a.avg_power_w + "W</span>";
        if (a.elevation_gain_m) st += '<span class="badge" style="background:#3a3a5a;color:#a0a0ff;font-size:12px;padding:4px 10px">' + a.elevation_gain_m + "m</span>";
        if (a.moving_time) st += '<span class="badge" style="background:#3a5a3a;color:#a0ffa0;font-size:12px;padding:4px 10px">' + a.moving_time + "</span>";
        if (a.distance_km) st += '<span class="badge" style="background:#5a3a3a;color:#ffa0a0;font-size:12px;padding:4px 10px">' + a.distance_km + "km</span>";
        if (a.max_heartrate) st += '<span class="badge" style="background:#5a1a1a;color:#ff8080;font-size:12px;padding:4px 10px">HR ' + a.max_heartrate + ' bpm</span>';
        if (a.avg_heartrate) st += '<span class="badge" style="background:#5a3a3a;color:#ffa0a0;font-size:12px;padding:4px 10px">Avg ' + a.avg_heartrate + ' bpm</span>';
        if (a.calories_kcal) st += '<span class="badge" style="background:#5a5a3a;color:#ffffa0;font-size:12px;padding:4px 10px">' + a.calories_kcal + ' kcal</span>';
        st += "</div>";
        // HR Metrics row
        var hrRow = '';
        if (a.hr_metrics) {
          var hm = a.hr_metrics;
          var drift = hm.cardiac_drift_pct;
          var dc = hm.decoupling_pct;
          var ef = hm.efficiency_factor;
          if (drift !== null && drift !== undefined) {
            var dc2 = Math.abs(drift) < 5 ? '#27ae60' : Math.abs(drift) < 10 ? '#f39c12' : '#e74c3c';
            var dl = Math.abs(drift) < 5 ? 'Stable' : Math.abs(drift) < 10 ? 'Moderate' : 'High';
            hrRow += '<div class="stat-card" style="padding:8px 10px;flex:1;min-width:80px"><div class="stat-value" style="font-size:16px;color:' + dc2 + '">' + (drift > 0 ? '+' : '') + drift + '%</div><div class="stat-label" style="font-size:10px">Drift</div><div style="font-size:10px;color:' + dc2 + '">' + dl + '</div></div>';
          }
          if (ef !== null && ef !== undefined) {
            hrRow += '<div class="stat-card" style="padding:8px 10px;flex:1;min-width:80px"><div class="stat-value" style="font-size:16px;color:var(--accent)">' + ef + '</div><div class="stat-label" style="font-size:10px">EF</div><div style="font-size:10px;color:var(--text-muted)">P:HR</div></div>';
          }
          if (dc !== null && dc !== undefined) {
            var dc3 = Math.abs(dc) < 5 ? '#27ae60' : Math.abs(dc) < 15 ? '#f39c12' : '#e74c3c';
            hrRow += '<div class="stat-card" style="padding:8px 10px;flex:1;min-width:80px"><div class="stat-value" style="font-size:16px;color:' + dc3 + '">' + (dc > 0 ? '+' : '') + dc + '%</div><div class="stat-label" style="font-size:10px">Decouple</div></div>';
          }
          if (hrRow) hrRow = '<div class="stat-grid" style="grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:8px;margin-bottom:10px">' + hrRow + '</div>';
        }
        var h = hrRow + st + '<div style="font-size:14px;line-height:1.6;color:var(--text-secondary);padding:4px 0 8px;border-bottom:1px solid var(--border-light)\">' + esc(mt) + "</div>";
        if (tp) h += '<div style="display:flex;gap:10px;align-items:start;margin-top:10px;padding:10px 12px;background:var(--bg-nav-active);border-radius:6px"><span style="font-size:16px">&#10024;</span><div><div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:2px">Coach Tip</div><div style="font-size:13px;color:var(--text-secondary)\">' + esc(tp) + '</div></div></div>';
        
                // Notes & Tags card
        var nv = a.notes || "";
        h += '<div class="card" style="margin-top:12px"><h2>Notes & Tags</h2>' +
          '<div style="margin-bottom:8px"><label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:4px">Gear Used</label>' +
          '<select id="gear-sel-' + a.id + '" style="width:100%;padding:6px 8px;background:var(--bg-input);border:1px solid var(--border-input);color:var(--input-text);border-radius:6px;font-size:12px;margin-bottom:8px" onchange="setActivityGear(' + a.id + ',this.value)"><option value="">None</option></select></div>' +
          '<div style="margin-bottom:8px">';
        var tags = ["#race","#commute","#indoor","#sick","#recovery","#PR","#group_ride","#solo","#hill_climb","#zwift","#outdoor","#exploring","#ladies"];
        for (var ti = 0; ti < tags.length; ti++) {
          var tag = tags[ti];
          var active = nv.indexOf(tag) >= 0 ? " background:var(--accent);color:#fff" : " background:var(--bg-nav-active);color:var(--text-secondary)";
          h += '<span class="tag-btn" data-tag="' + esc(tag) + '" style="display:inline-block;cursor:pointer;padding:3px 10px;border-radius:12px;font-size:12px;margin:3px;' + active + '" onclick="toggleTag(' + a.id + ',this)">' + esc(tag) + '</span>';
        }
        h += '</div><textarea id="notes-text-' + a.id + '" style="width:100%;min-height:50px;padding:8px;border-radius:6px;border:1px solid var(--border-light);background:var(--bg-card);color:var(--text-primary);font-size:13px;resize:vertical">' + esc(nv) + '</textarea>';
        h += '<button class="btn" style="margin-top:6px;font-size:12px" onclick="saveNotes(' + a.id + ')">Save Notes</button></div>';
        // Load gear dropdown
        fetch("/api/gear/").then(function(r){return r.json()}).then(function(items){
          var sel = document.getElementById("gear-sel-" + a.id);
          if (!sel) return;
          items.forEach(function(g){
            var o = document.createElement("option");
            o.value = g.id; o.textContent = esc(g.name) + " (" + esc(g.current_mileage_km) + "km)";
            if (a.gear_id && a.gear_id == g.id) o.selected = true;
            sel.appendChild(o);
          });
        }).catch(function(){});
        ic.innerHTML = h;
      } else { ic.innerHTML = '<div style="color:var(--text-muted);padding:12px 0;text-align:center;font-size:13px">Not enough power data for insights</div>'; }
    }
    if (lat.length > 0 && lon.length > 0) setTimeout(function() { renderGPSMap(lat, lon); }, 100); else document.getElementById("gps-map").innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)\">No GPS data</div>';
    if (t.length > 0) {
      var pz = null;
      if (s.power && s.power.length > 10) {
        try { var fr = await apiGet("/training/ftp"); var fv = fr.ftp || 200; pz = [{n:"Z1",lw:0,hw:Math.round(fv*0.55),c:"#95a5a6"},{n:"Z2",lw:Math.round(fv*0.55),hw:Math.round(fv*0.75),c:"#27ae60"},{n:"Z3",lw:Math.round(fv*0.75),hw:Math.round(fv*0.90),c:"#f1c40f"},{n:"Z4",lw:Math.round(fv*0.90),hw:Math.round(fv*1.05),c:"#e67e22"},{n:"Z5",lw:Math.round(fv*1.05),hw:Math.round(fv*1.20),c:"#e74c3c"},{n:"Z6",lw:Math.round(fv*1.20),hw:Math.round(fv*1.50),c:"#9b59b6"},{n:"Z7",lw:Math.round(fv*1.50),hw:9999,c:"#8e44ad"}]; } catch(e) {}
      }
      renderStreamChart("chart-power","Power (W)", t, s.power, "#ff6b6b", true, pz);
      renderStreamChart("chart-hr","Heart Rate (bpm)", t, s.heartrate, "#ff6b6b", false);
      renderStreamChart("chart-cadence","Cadence (rpm)", t, s.cadence, "#51cf66", false);
      renderStreamChart("chart-speed","Speed (km/h)", t, s.speed, "#339af0", false);
      renderStreamChart("chart-altitude","Altitude (m)", t, s.altitude, "#845ef7", false);
    }
  } catch(e) { document.getElementById("detail-stats").innerHTML = '<div class="status-msg error">' + esc(e.message) + "</div>"; }
}

function renderStreamChart(cid, label, td, vals, color, up, zones) {
  var c = document.getElementById(cid); if (!c) return; destroyChart(cid);
  if (vals && vals.length > 10) vals = smoothData(vals, 5);
  var mp = 3000, st = 1; if (td.length > mp) st = Math.ceil(td.length / mp);
  var lb = [], dv = []; for (var i = 0; i < td.length; i += st) { lb.push((td[i] / 60).toFixed(1)); dv.push(vals && i < vals.length ? vals[i] : null); }
  var zp = null;
  if (up && zones && zones.length > 0) { zp = { id: "zoneBands", beforeDraw: function(ch) { var ctx = ch.ctx, ca = ch.chartArea, ys = ch.scales.y; zones.forEach(function(z) { var yt = ys.getPixelForValue(z.hw), yb = ys.getPixelForValue(z.lw); if (yt === undefined || yb === undefined) return; if (yt > ca.bottom) yt = ca.bottom; if (yb < ca.top) yb = ca.top; ctx.fillStyle = z.c + "22"; ctx.fillRect(ca.left, yt, ca.right - ca.left, yb - yt); }); } }; }
  chartInstances[cid] = new Chart(c.getContext("2d"), {
    type: "line",
    data: { labels: lb, datasets: [{ label: label, data: dv, borderColor: color, backgroundColor: color + "22", borderWidth: 2, pointRadius: 0, fill: true, tension: 0.4 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, spanGaps: true, plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false, callbacks: { title: function(items) { return items[0].label + " min"; } } } }, scales: { x: { display: true, title: { display: true, text: "Time (minutes)", color: "#8080a0" }, ticks: { color: "#8080a0", maxTicksLimit: 20 } }, y: { display: true, title: { display: true, text: label, color: "#8080a0" }, ticks: { color: "#8080a0" }, beginAtZero: !up } } },
    plugins: zp ? [zp] : []
  });
}

function renderGPSMap(lat, lon) {
  var el = document.getElementById("gps-map"); if (!el || lat.length < 2) return;
  if (window._gpsMap) { window._gpsMap.remove(); window._gpsMap = null; }
  var m = L.map(el).setView([lat[0], lon[0]], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap" }).addTo(m);
  var co = []; for (var i = 0; i < lat.length; i++) co.push([lat[i], lon[i]]);
  L.polyline(co, { color: "#6366f1", weight: 3 }).addTo(m);
  window._gpsMap = m; setTimeout(function() { m.invalidateSize(); }, 200);
}

// ── Health ─────────────────────────────────────────────────
async function loadHealth() {
  var c = document.getElementById("health-container"); if (!c) return; showLoading("health-container");
  try {
    var d = await apiGet("/health/checkins?days=90");
    if (!d || d.length === 0) { c.innerHTML = '<div class="card" style="text-align:center;padding:20px">No health data</div>'; return; }
    var ch = [{id:"chart-hr-health",lb:"Resting HR",k:"resting_hr",co:"#ff6b6b"},{id:"chart-hrv",lb:"HRV (RMSSD)",k:"hrv_rmssd",co:"#51cf66"},{id:"chart-sleep",lb:"Sleep (hours)",k:"sleep_hours",co:"#339af0"},{id:"chart-weight",lb:"Weight (kg)",k:"weight_kg",co:"#845ef7"},{id:"chart-bodyfat",lb:"Body Fat %",k:"body_fat_pct",co:"#f0c040"}];
    var h = '<div class="stat-grid" style="margin-bottom:16px">' +
      '<div class="stat-card"><div class="stat-value">' + (d[d.length-1].resting_hr || "--") + '</div><div class="stat-label">Resting HR</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (d[d.length-1].hrv_rmssd || "--") + '</div><div class="stat-label">HRV</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (d[d.length-1].sleep_hours || "--") + '</div><div class="stat-label">Sleep</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + (d[d.length-1].weight_kg || "--") + '</div><div class="stat-label">Weight</div></div></div>';
    ch.forEach(function(cv) { h += '<div class="card"><h2>' + cv.lb + '</h2><div class="chart-container"><canvas id="' + cv.id + '"></canvas></div></div>'; });
    c.innerHTML = h;
    ch.forEach(function(cv) {
      destroyChart(cv.id);
      var lb = [], vl = []; d.forEach(function(r) { lb.push(new Date(r.date).toLocaleDateString("en-US",{month:"short",day:"numeric"})); vl.push(r[cv.k] !== undefined ? r[cv.k] : null); });
      chartInstances[cv.id] = new Chart(document.getElementById(cv.id).getContext("2d"), {
        type: "line", data: { labels: lb, datasets: [{ label: cv.lb, data: vl, borderColor: cv.co, backgroundColor: cv.co + "22", borderWidth: 2, pointRadius: 2, fill: true, tension: 0.3 }] },
        options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" } }, y: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" } } } }
      });
    });
  } catch(e) { c.innerHTML = '<div class="status-msg error">' + esc(e.message) + "</div>"; }
}

// ── PMC ────────────────────────────────────────────────────
async function loadPMC() {
  var cv = document.getElementById("chart-pmc"); if (!cv) return; destroyChart("chart-pmc");
  try {
    var d = await apiGet("/training/pmc"); if (!d || d.length === 0) return;
    var lb = [], ctl = [], atl = [], tsb = [], tss = [];
    d.forEach(function(r) { lb.push(new Date(r.date).toLocaleDateString("en-US",{month:"short",day:"numeric"})); ctl.push(r.ctl||0); atl.push(r.atl||0); tsb.push(r.tsb||0); tss.push(r.daily_tss||0); });
    chartInstances["chart-pmc"] = new Chart(cv.getContext("2d"), {
      type: "line",
      data: { labels: lb, datasets: [
        { label: "CTL (Fitness)", data: ctl, borderColor: "#51cf66", backgroundColor: "#51cf6633", borderWidth: 2, pointRadius: 2, fill: false, tension: 0.2 },
        { label: "ATL (Fatigue)", data: atl, borderColor: "#ff6b6b", backgroundColor: "#ff6b6b33", borderWidth: 2, pointRadius: 2, fill: false, tension: 0.2 },
        { label: "TSB (Form)", data: tsb, borderColor: "#339af0", backgroundColor: "#339af033", borderWidth: 2, pointRadius: 2, fill: false, tension: 0.2 },
        { label: "Daily TSS", data: tss, borderColor: "#f0c040", backgroundColor: "#f0c04033", borderWidth: 1, pointRadius: 1, fill: false, tension: 0.1, borderDash: [4, 4] }
      ]},
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { color: "#e0e0e0" } } }, scales: { x: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" } }, y: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" } } } }
    });
  } catch(e) {}
}

// ── Power Curve ────────────────────────────────────────────
async function loadPowerCurve() {
  var c = document.getElementById("power-curve-container"); if (!c) return; showLoading("power-curve-container");
  try {
    var d = await apiGet("/training/power-curve"); var cv = d.curve || {};
    var lb = Object.keys(cv).sort(function(a,b){return parseInt(a)-parseInt(b);});
    var vl = lb.map(function(l){return Math.round(cv[l]);});
    var pp = d.power_profile || {};
    var ftpV = 0; try { var fr = await apiGet("/training/ftp"); ftpV = fr.ftp || 0; } catch(e) {}
    c.innerHTML = '<div class="card"><div class="chart-container"><canvas id="chart-power-curve"></canvas></div></div>';
    chartInstances["chart-power-curve"] = new Chart(document.getElementById("chart-power-curve").getContext("2d"), {
      type: "line",
      data: { labels: lb.map(function(l){return l<60?l+"s":Math.floor(l/60)+"m";}), datasets: [
        { label: "Best Power (W)", data: vl, borderColor: "#00d4ff", backgroundColor: "#00d4ff33", borderWidth: 2, pointRadius: 3, pointBackgroundColor: "#00d4ff", fill: true, tension: 0.2 },
        { label: "100% FTP (" + ftpV + "W)", data: lb.map(function(){return ftpV;}), borderColor: "#ff6b6b", borderWidth: 1, pointRadius: 0, borderDash: [6, 3], fill: false },
        { label: "120% FTP", data: lb.map(function(){return ftpV*1.2;}), borderColor: "#f39c12", borderWidth: 1, pointRadius: 0, borderDash: [4, 4], fill: false }
      ]},
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { color: "#e0e0e0", font: {size:11} } } }, scales: { x: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" } }, y: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" }, beginAtZero: false } } }
    });
  } catch(e) { c.innerHTML = '<div class="status-msg error">' + esc(e.message) + "</div>"; }
}

// ── Power Profile ──────────────────────────────────────────
async function loadPowerProfile() {
  var c = document.getElementById("power-profile-container"); if (!c) return; showLoading("power-profile-container");
  try {
    var d = await apiGet("/training/power-profile");
    if (!d || !d.profile) { c.innerHTML = '<div class="card" style="text-align:center;padding:20px;color:var(--text-muted)\">No profile data</div>'; return; }
    var cats = d.profile || {};
    c.innerHTML = '<div class="card"><div class="chart-container"><canvas id="chart-power-profile"></canvas></div></div>';
    destroyChart("chart-power-profile");
    var lb = Object.keys(cats), vl = Object.values(cats).map(function(v){return Math.round(v);});
    chartInstances["chart-power-profile"] = new Chart(document.getElementById("chart-power-profile").getContext("2d"), {
      type: "bar",
      data: { labels: lb, datasets: [{ label: "Power (W/kg)", data: vl, backgroundColor: ["#ff6b6b","#f39c12","#f1c40f","#51cf66","#339af0","#845ef7"], borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" } }, y: { ticks: { color: "#8080a0" }, grid: { color: "#2a2a40" }, beginAtZero: true } } }
    });
  } catch(e) { c.innerHTML = '<div class="status-msg error">' + esc(e.message) + "</div>"; }
}

// ── Calendar ───────────────────────────────────────────────
async function loadCalendar() {
  try {
    var d = await apiGet("/training/calendar?days=365"); var c = document.getElementById("calendar-container"); if (!c) return;
    if (!d || d.length === 0) { c.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)\">No data</div>'; return; }
    var tm = {}, mx = 0; d.forEach(function(r){tm[r.date]=r.tss;if(r.tss>mx)mx=r.tss;});
    var td = new Date(), ds = [];
    for (var i = 364; i >= 0; i--) { var dd = new Date(td); dd.setDate(dd.getDate()-i); ds.push({date:dd,key:dd.toISOString().substring(0,10),tss:tm[dd.toISOString().substring(0,10)]||0}); }
    var ws = [], wk = []; ds.forEach(function(d){wk.push(d);if(d.date.getDay()===6){ws.push(wk);wk=[];}}); if(wk.length>0)ws.push(wk);
    var h = '<div style="display:flex;gap:4px;overflow-x:auto;padding:8px 0"><div style="display:flex;flex-direction:column;gap:3px;padding-top:20px;margin-right:4px">';
    ["","Mon","","Wed","","Fri",""].forEach(function(l){h+='<div style="font-size:10px;color:#606080;height:13px;line-height:13px">'+l+"</div>";}); h+="</div>";
    ws.forEach(function(w){h+='<div style="display:flex;flex-direction:column;gap:3px">';w.forEach(function(d){var ins=mx>0?Math.min(1,d.tss/mx):0;var co=d.tss===0?"#1e1e30":ins<0.25?"#0f3460":ins<0.5?"#1a5276":ins<0.75?"#2980b9":"#00d4ff";h+='<div title="'+d.key+": "+d.tss.toFixed(0)+' TSS" style="width:13px;height:13px;border-radius:2px;background:'+co+';cursor:pointer"></div>';});h+="</div>";});
    h+="</div><div style='display:flex;align-items:center;gap:8px;margin-top:12px;font-size:12px;color:#8080a0'><span>Less</span>";
    [[0,"#1e1e30"],[0.25,"#0f3460"],[0.5,"#1a5276"],[0.75,"#2980b9"],[1,"#00d4ff"]].forEach(function(t){h+='<div style="width:14px;height:14px;border-radius:2px;background:'+t[1]+'"></div>';});
    h+="<span>More</span></div>"; c.innerHTML = h;
  } catch(e) { var cl = document.getElementById("calendar-container"); if (cl) cl.innerHTML = '<div style="padding:40px;text-align:center;color:#ff8080">Error: '+esc(e.message)+"</div>"; }
}

// ── Zones ──────────────────────────────────────────────────
async function loadZones() {
  var el = document.getElementById("zones-list"); if (!el) return;
  el.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>Loading zones...</span></div>';
  try {
    var d = await apiGet("/training/zones?days=90");
    var fv = document.getElementById("zones-ftp-value"); if (fv) fv.textContent = (d.ftp||0) + " W";
    var th = document.getElementById("zones-total-hours"); if (th) th.textContent = (d.total_hours||0) + "h";
    var rc = document.getElementById("zones-rides"); if (rc) rc.textContent = (d.activities_analyzed||0);
    el.innerHTML = (d.zones||[]).map(function(z){return '<div class="card" style="padding:16px;margin-bottom:10px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'+
      '<div><span style="display:inline-block;width:24px;height:24px;border-radius:4px;background:'+z.color+';vertical-align:middle;margin-right:8px"></span>'+
      '<strong style="color:#e0e0e0">Z'+z.zone+": "+z.name+'</strong><span style="color:#8080a0;font-size:13px;margin-left:8px">'+z.low_watts+"-"+z.high_watts+"W</span></div>"+
      '<span style="color:#e0e0e0;font-size:14px">'+(z.hours>0?z.hours+"h":z.seconds+"s")+' <span style="color:#8080a0;font-size:12px">('+z.pct_of_total+"%)</span></span></div>"+
      '<div style="height:20px;background:#1e1e30;border-radius:4px;overflow:hidden;margin-bottom:4px"><div style="height:100%;width:'+Math.max(z.pct_of_total,1)+'%;background:'+z.color+';border-radius:4px;transition:width 0.3s"></div></div>'+
      '<div style="color:#606080;font-size:12px">'+z.description+"</div></div>";}).join("");
  } catch(e) { el.innerHTML = '<div class="status-msg error">'+esc(e.message)+"</div>"; }
}

// ── Insights ───────────────────────────────────────────────
function renderInsights(ins, cid) {
  var el = document.getElementById(cid); if (!el) return;
  if (!ins || ins.length === 0) { el.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px">No insights</div>'; return; }
  el.innerHTML = ins.map(function(i){var bc="#8080a0";if(i.severity==="positive")bc="#27ae60";else if(i.severity==="warning")bc="#f39c12";else if(i.severity==="critical")bc="#e74c3c";return '<div style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border-light);align-items:start"><span style="font-size:20px;flex-shrink:0">'+i.icon+'</span><div style="flex:1"><div style="font-weight:600;color:var(--text-primary);margin-bottom:2px">'+i.title+'</div><div style="font-size:13px;color:var(--text-muted)\">'+i.detail+'</div></div><span style="width:4px;min-height:36px;border-radius:2px;background:'+bc+';flex-shrink:0"></span></div>';}).join("");
}
async function toggleCoachHistory() {
  var el = document.getElementById("coach-history"); if (!el) return;
  if (el.style.display !== "none") { el.style.display = "none"; return; }
  el.style.display = "block"; el.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>Loading...</span></div>';
  try { var n = await apiGet("/coach/history?limit=10"); if (!n||n.length===0){el.innerHTML='<div style="color:var(--text-muted);padding:8px 0;font-size:13px">No history</div>';return;}
    el.innerHTML = n.map(function(x){return '<div style="padding:8px 0;border-bottom:1px solid var(--border-light)\"><div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">'+(x.date?new Date(x.date).toLocaleDateString():"")+'</div><div style="font-size:13px;color:var(--text-secondary)\">'+x.note+"</div></div>";}).join("");
  } catch(e) { el.innerHTML = '<div style="color:var(--text-muted)\">Error</div>'; }
}
async function loadInsights() {
  var c = document.getElementById("insights-container"); if (!c) return;
  c.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>Analyzing...</span></div>';
  var cc = document.getElementById("coach-card"); if(cc)cc.style.display="none";
  try { var ch = await apiGet("/coach/latest"); if(ch&&ch.note&&cc){cc.style.display="block";cc.innerHTML='<div class="card" style="border-left:4px solid var(--accent);margin-bottom:16px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><h2 style="margin:0">AI Coach</h2><span style="font-size:12px;color:var(--text-muted)\">'+(ch.date?new Date(ch.date).toLocaleDateString():"")+'</span></div><div style="font-size:15px;line-height:1.5;color:var(--text-primary);padding:4px 0">'+ch.note+'</div><div style="margin-top:8px"><a href="#" onclick=\"toggleCoachHistory()" style="color:var(--accent);font-size:12px">View history</a></div><div id="coach-history" style="display:none;margin-top:12px;border-top:1px solid var(--border-light);padding-top:12px"></div></div>';} } catch(e) {}
  try { var d = await apiGet("/training/insights"); renderInsights(d.insights, "insights-container"); setTimeout(loadPMC,100); } catch(e) { c.innerHTML = '<div class="status-msg error">'+esc(e.message)+"</div>"; }
}

// ── Segments ───────────────────────────────────────────────
async function loadSegments() { var c = document.getElementById("segments-container"); if(!c)return; c.innerHTML="<p>Loading...</p>"; try{var d=await apiGet("/segments/");renderSegments(c,d);}catch(e){c.innerHTML="<p>Error: "+esc(e.message)+"</p>";} }
function renderSegments(r,s){if(!s||s.length===0){r.innerHTML='<p>No segments</p><button class="btn btn-primary" onclick=\"autoDetectSegments()\">Auto-Detect</button>';return;}r.innerHTML='<button class="btn btn-primary" onclick=\"autoDetectSegments()\">Auto-Detect</button><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px;margin-top:16px">'+s.map(function(s){return'<div class="card" style="cursor:pointer" onclick=\"showSegmentLeaderboard('+s.id+')\"><h3>'+s.name+'</h3><p style="color:#8a9aa8;font-size:14px">'+(s.distance_m/1000).toFixed(1)+" km"+(s.occurrences?" &middot; "+s.occurrences+" rides":"")+"</p></div>";}).join("")+"</div>";}
async function autoDetectSegments(){if(!confirm("Auto-detect segments?"))return;document.getElementById("segments-container").innerHTML="Detecting...";try{await apiPost("/segments/auto-detect?min_occurrences=2");loadSegments();}catch(e){document.getElementById("segments-container").innerHTML="<p>Error: "+esc(e.message)+"</p>";}}
async function showSegmentLeaderboard(sid){var c=document.getElementById("segments-container");c.innerHTML="<p>Loading leaderboard...</p>";try{var d=await apiGet("/segments/"+sid+"/leaderboard");if(!d||d.length===0){c.innerHTML='<p>No data</p><button class="btn" onclick=\"loadSegments()\">Back</button>';return;}var h='<button class="btn" onclick=\"loadSegments()\">&#9664; Back</button><h2>'+esc(d[0].segment_name||"Segment")+'</h2><table style="width:100%;border-collapse:collapse"><tr style="color:#8080a0;border-bottom:1px solid #2a2a40"><th style="padding:8px;text-align:left">#</th><th style="padding:8px;text-align:left">Rider</th><th style="padding:8px;text-align:left">Time</th></tr>';d.forEach(function(r){h+='<tr style="border-bottom:1px solid #1e1e30"><td style="padding:8px">'+esc(r.rank||"-")+'</td><td style="padding:8px">'+esc(r.athlete_name)+'</td><td style="padding:8px">'+esc(r.time?formatTime(r.time):"-")+"</td></tr>";});h+="</table>";c.innerHTML=h;}catch(e){c.innerHTML="<p>Error: "+esc(e.message)+"</p>";}}
async function loadStravaSegments(){try{var s=await apiGet("/strava/segments");alert("Loaded "+s.length+" segments");renderStravaSegments(s);}catch(e){alert("Error: "+e.message);}}
function renderStravaSegments(s){var c=document.getElementById("strava-segments-container");if(!c||!s)return;c.innerHTML="<h3>Strava Segments ("+s.length+")</h3><div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;margin-top:12px'>"+s.map(function(s){return'<div class="card" style="cursor:pointer;padding:14px"><h3>'+s.name+'</h3><p style="color:#8a9aa8;font-size:13px">'+(s.distance||0).toFixed(0)+"m, "+(s.average_grade||0).toFixed(1)+"%</p></div>";}).join("")+"</div>";}

// ── Settings ───────────────────────────────────────────────
async function loadSettings(){loadStravaStatus();loadGarminStatus();try{var f=await apiGet("/training/ftp");var fe=document.getElementById("ftp-value");if(fe)fe.value=f.ftp||"";var fd=document.getElementById("ftp-current");if(fd)fd.textContent=(f.ftp||"--")+"W";}catch(e){}}
async function loadStravaStatus(){try{var s=await apiGet("/strava/status");if(s.connected){try{var a=await apiGet("/strava/me");document.getElementById("strava-status").innerHTML='<div class="status-msg success">Connected: '+(a.firstname||"")+" "+(a.lastname||"")+"</div>";}catch(e){document.getElementById("strava-status").innerHTML='<div class="status-msg success">Connected</div>';}}else{document.getElementById("strava-status").innerHTML='<div class="status-msg info">Not connected</div>';}}catch(e){document.getElementById("strava-status").innerHTML='<div class="status-msg info">Not connected</div>';}}
async function stravaConnect(){document.getElementById("strava-status").innerHTML='<div class="status-msg info">Opening Strava...</div>';try{var d=await apiGet("/strava/auth-url");if(d.auth_url){window.open(d.auth_url,"_blank");document.getElementById("strava-status").innerHTML='<div class="status-msg info">Strava opened in new tab. Complete authorization, then refresh.</div>';}else{document.getElementById("strava-status").innerHTML='<div class="status-msg error">No auth URL</div>';}}catch(e){document.getElementById("strava-status").innerHTML='<div class="status-msg error">Error: '+esc(e.message)+"</div>";}}
async function stravaConnectToken(){var t=document.getElementById("strava-token").value;if(!t){alert("Enter a token");return;}try{await apiPost("/strava/connect?token="+encodeURIComponent(t));loadStravaStatus();document.getElementById("strava-token").value="";}catch(e){document.getElementById("strava-status").innerHTML='<span style="color:red">Error: '+esc(e.message)+"</span>";}}
async function stravaSync(){try{var s=await apiGet("/strava/segments");alert("Synced "+s.length+" segments");}catch(e){alert("Error: "+e.message);}}
async function stravaImportActivities(){var se=document.getElementById("strava-status");var bt=document.querySelectorAll("#page-settings .card:first-of-type .btn");se.innerHTML='<div class="status-msg info"><div class="spinner" style="display:inline-block;vertical-align:middle;margin-right:8px"></div> Importing...</div>';bt.forEach(function(b){b.disabled=true;});try{var r=await apiPost("/strava/import-activities?limit=50");se.innerHTML='<div class="status-msg success">Imported '+r.imported+" new. "+r.skipped+" existed.</div>";loadActivities();}catch(e){se.innerHTML='<div class="status-msg error">Import failed: '+esc(e.message)+"</div>";}bt.forEach(function(b){b.disabled=false;});}
async function stravaDisconnect(){try{await apiPost("/strava/disconnect");loadStravaStatus();}catch(e){alert("Error: "+e.message);}}
async function loadGarminStatus(){try{var s=await apiGet("/garmin/status");document.getElementById("garmin-status").innerHTML=s.configured?'<div class="status-msg success">Configured</div>':'<div class="status-msg info">Not configured</div>';}catch(e){document.getElementById("garmin-status").innerHTML='<div class="status-msg info">Not configured</div>';}}
async function garminConfigure(){var e=document.getElementById("garmin-email").value;var p=document.getElementById("garmin-password").value;if(!e||!p){alert("Enter email and password");return;}try{await apiPost("/garmin/save-credentials?email="+encodeURIComponent(e)+"&password="+encodeURIComponent(p));loadGarminStatus();alert("Saved");}catch(e2){alert("Error: "+e2.message);}}
async function garminSync(){document.getElementById("garmin-status").innerHTML='<div class="status-msg info"><div class="spinner" style="display:inline-block;vertical-align:middle;margin-right:8px"></div> Syncing...</div>';try{await apiPost("/garmin/sync");document.getElementById("garmin-status").innerHTML='<div class="status-msg success">Sync complete</div>';}catch(e){document.getElementById("garmin-status").innerHTML='<div class="status-msg error">Error: '+esc(e.message)+"</div>";}}
async function garminSyncHealth(){document.getElementById("garmin-status").innerHTML='<div class="status-msg info"><div class="spinner" style="display:inline-block;vertical-align:middle;margin-right:8px"></div> Syncing health...</div>';try{await apiPost("/garmin/sync?health_only=true");document.getElementById("garmin-status").innerHTML='<div class="status-msg success">Health sync complete</div>';}catch(e){document.getElementById("garmin-status").innerHTML='<div class="status-msg error">Error: '+esc(e.message)+"</div>";}}
// Notes & tag functions
async function saveNotes(id) {
  var ta = document.getElementById("notes-text-" + id);
  if (!ta) return;
  try {
    await fetch("/api/activities/" + id + "/notes", {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({notes: ta.value})
    });
    ta.style.border = "1px solid #27ae60";
    setTimeout(function(){ ta.style.border = "1px solid var(--border-light)"; }, 2000);
  } catch(e) { alert("Error saving: " + e.message); }
}
function toggleTag(id, el) {
  var ta = document.getElementById("notes-text-" + id);
  if (!ta) return;
  var tag = el.getAttribute("data-tag");
  var notes = ta.value;
  if (notes.indexOf(tag) >= 0) {
    notes = notes.split(tag).join("").trim().replace(/\s+/g, " ");
    el.style.background = "var(--bg-nav-active)";
    el.style.color = "var(--text-secondary)";
  } else {
    notes = (notes + " " + tag).trim();
    el.style.background = "var(--accent)";
    el.style.color = "#fff";
  }
  ta.value = notes;
}
// ── Gear ────────────────────────────────────────────────────
async function loadGear() {
  var c = document.getElementById("gear-list"); if (!c) return;
  c.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>Loading...</span></div>';
  try {
    var items = await apiGet("/gear/");
    if (!items || items.length === 0) {
      c.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">No gear added yet. Fill in the form above to add your first item.</div>';
      return;
    }
    var h = '<div class="stat-grid">';
    items.forEach(function(g) {
      var pct = g.pct_used || 0;
      var barColor = pct > 90 ? "#e74c3c" : pct > 70 ? "#f39c12" : "#27ae60";
      var warn = pct > 90 ? '<div style="color:#e74c3c;font-size:11px;margin-top:4px">&#9888; Replace soon!</div>' : '';
      var remaining = g.remaining_km !== null && g.remaining_km !== undefined ? '<div style="font-size:11px;color:var(--text-muted)">' + g.remaining_km + ' km remaining</div>' : '';
      h += '<div class="stat-card" style="position:relative;text-align:left;min-width:200px">' +
        '<div style="font-size:14px;font-weight:600;color:var(--accent)">' + esc(g.name) + '</div>' +
        '<div style="font-size:11px;color:var(--text-muted);margin:2px 0 6px">' + g.type + (g.brand ? " - " + g.brand : "") + '</div>' +
        '<div style="font-size:20px;font-weight:700;color:' + barColor + '">' + g.current_mileage_km + ' km</div>' +
        '<div style="height:4px;background:var(--bg-nav-active);border-radius:2px;margin:6px 0;overflow:hidden">' +
        '<div style="height:100%;width:' + Math.min(pct,100) + '%;background:' + barColor + ';border-radius:2px"></div></div>' +
        remaining + warn +
        '<div style="margin-top:8px"><button class="btn" style="font-size:11px;padding:4px 10px" onclick="deleteGear(' + g.id + ')">Delete</button></div></div>';
    });
    h += '</div>';
    c.innerHTML = h;
  } catch(e) { c.innerHTML = '<div class="status-msg error">Error: ' + esc(e.message) + '</div>'; }
}

async function addGear() {
  var name = document.getElementById("gear-name").value;
  if (!name) { alert("Enter a name"); return; }
  try {
    await apiPost("/gear/", {
      name: name,
      type: document.getElementById("gear-type").value,
      brand: document.getElementById("gear-brand").value,
      replacement_mileage_km: parseFloat(document.getElementById("gear-replacement").value) || 0,
      purchase_date: document.getElementById("gear-purchase").value || null,
      start_mileage_km: parseFloat(document.getElementById("gear-start-miles").value) || 0,
    });
    document.getElementById("gear-name").value = "";
    document.getElementById("gear-brand").value = "";
    document.getElementById("gear-replacement").value = "";
    document.getElementById("gear-purchase").value = "";
    document.getElementById("gear-start-miles").value = "";
    loadGear();
  } catch(e) { alert("Error: " + e.message); }
}

async function setActivityGear(activityId, gearId) {
  try {
    await fetch("/api/gear/activity/" + activityId + "/gear", {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({gear_id: gearId ? parseInt(gearId) : null})
    });
  } catch(e) { console.error(e); }
}

async function deleteGear(id) {
  if (!confirm("Delete this gear item?")) return;
  try {
    await apiPost("/gear/" + id, null, "DELETE");
    loadGear();
  } catch(e) { alert("Error: " + e.message); }
}

async function saveFTP(){var v=document.getElementById("ftp-value").value;if(!v||isNaN(v)){alert("Enter a valid FTP value");return;}try{await apiPost("/training/ftp?ftp="+encodeURIComponent(v));alert("FTP saved as "+v+"W");}catch(e){alert("Error: "+e.message);}}
