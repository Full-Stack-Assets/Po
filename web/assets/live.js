/*
 * COO Engine — live dashboard
 * Vanilla JS (no build step). Polls the orchestration backend and drives the
 * human-in-the-loop approval queue.
 *
 * Endpoints used:
 *   GET  /v2/health          provider health + usage
 *   GET  /v2/status          agents, constraints, providers, usage, models
 *   GET  /v2/approvals       pending approval requests
 *   POST /v2/approvals/{id}  { approved, edited_input? }
 */
(function () {
  "use strict";

  var POLL_MS = 4000;
  var timer = null;
  var base = "";

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
        "'": "&#39;" })[c];
    });
  };

  function setHealth(ok, text) {
    var el = $("health");
    el.className = "badge " + (ok ? "ok" : "bad");
    el.textContent = text;
  }

  function showError(msg) { $("error").textContent = msg || ""; }

  async function api(path, opts) {
    var res = await fetch(base + path, opts);
    if (!res.ok) throw new Error(path + " → HTTP " + res.status);
    return res.json();
  }

  function renderConstraints(list) {
    if (!list || !list.length) { $("constraints").innerHTML =
      '<p class="muted">none</p>'; return; }
    var rows = list.map(function (c) {
      var pct = c.utilization || "0%";
      var w = parseFloat(pct) || 0;
      return '<tr><td>' + esc(c.name) + '<div class="bar"><span style="width:' +
        Math.min(100, w) + '%"></span></div></td><td>' + esc(c.used) + " / " +
        esc(c.max) + " " + esc(c.unit) + "</td><td>" + esc(pct) +
        (c.exceeded ? ' ⚠️' : "") + "</td></tr>";
    }).join("");
    $("constraints").innerHTML = "<table><tr><th>Budget</th><th>Used</th>" +
      "<th>Util</th></tr>" + rows + "</table>";
  }

  function renderProviders(list) {
    if (!list || !list.length) { $("providers").innerHTML =
      '<p class="muted">none configured</p>'; return; }
    var rows = list.map(function (p) {
      return "<tr><td>" + esc(p.provider) + "</td><td>" +
        esc(p.success_rate) + "</td><td>" + esc(p.avg_latency_ms) +
        "ms</td><td>" + (p.circuit_open ? "🔴 open" : "🟢") + "</td></tr>";
    }).join("");
    $("providers").innerHTML = "<table><tr><th>Provider</th><th>Success</th>" +
      "<th>Latency</th><th>Circuit</th></tr>" + rows + "</table>";
  }

  function renderAgents(list) {
    if (!list || !list.length) { $("agents").innerHTML =
      '<p class="muted">none</p>'; return; }
    var rows = list.map(function (a) {
      return "<tr><td>" + esc(a.name) + "</td><td>" +
        esc((a.intents || []).slice(0, 3).join(", ")) + "</td><td>" +
        esc(a.active) + "</td></tr>";
    }).join("");
    $("agents").innerHTML = "<table><tr><th>Agent</th><th>Intents</th>" +
      "<th>Active</th></tr>" + rows + "</table>";
  }

  function pct(x) { return (Math.round((x || 0) * 1000) / 10) + "%"; }

  function renderStats(s) {
    var box = $("stats");
    if (!s || s.persistence === "disabled") {
      box.innerHTML = '<p class="muted">Persistence disabled — set ' +
        "DATABASE_URL on the backend to track reliability over time.</p>";
      return;
    }
    var cells = [
      { lbl: "Runs", num: s.total_runs, cls: "" },
      { lbl: "Success rate", num: pct(s.success_rate), cls: "green" },
      { lbl: "Verified pass", num: pct(s.verified_pass_rate), cls: "green" },
      { lbl: "Refund rate", num: pct(s.refund_rate),
        cls: s.refund_rate > 0 ? "red" : "" },
      { lbl: "Validations", num: s.validations_recorded, cls: "" },
      { lbl: "Approvals pending", num: s.approvals_pending, cls: "" },
    ];
    box.innerHTML = '<div class="stats">' + cells.map(function (c) {
      return '<div class="stat"><div class="num ' + c.cls + '">' +
        esc(c.num) + '</div><div class="lbl">' + esc(c.lbl) + "</div></div>";
    }).join("") + "</div>";
  }

  function renderUsage(u) {
    if (!u) { $("usage").innerHTML = '<p class="muted">—</p>'; return; }
    $("usage").innerHTML = "<table>" +
      "<tr><td>Total tokens</td><td>" + esc(u.total_tokens) + "</td></tr>" +
      "<tr><td>Total cost</td><td>$" + esc(u.total_cost_usd) + "</td></tr>" +
      "</table>";
  }

  async function decide(id, approved) {
    showError("");
    try {
      var edited = null;
      if (approved) {
        var current = this && this.dataset ? this.dataset.input : "";
        var input = window.prompt(
          "Approve this action. Edit the instruction if needed, or leave as-is:",
          current || "");
        if (input === null) return; // cancelled
        if (input !== current) edited = input;
      }
      await api("/v2/approvals/" + encodeURIComponent(id), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: approved, edited_input: edited }),
      });
      await refresh();
    } catch (e) { showError(String(e)); }
  }

  function renderApprovals(list) {
    var box = $("approvals");
    if (!list || !list.length) {
      box.innerHTML = '<p class="muted">No pending approvals. Risky actions ' +
        '(outreach, deploy, spend) will appear here for one-tap review.</p>';
      return;
    }
    box.innerHTML = "";
    list.forEach(function (a) {
      var input = (a.payload && a.payload.input) || a.summary || "";
      var div = document.createElement("div");
      div.className = "approval";
      div.innerHTML =
        '<div class="top"><strong>' + esc(a.type) + "</strong>" +
        '<span class="badge">' + esc(a.approval_id) + "</span></div>" +
        '<div class="muted">' + esc(input) + "</div>" +
        '<div class="actions"></div>';
      var actions = div.querySelector(".actions");
      var ok = document.createElement("button");
      ok.className = "approve"; ok.textContent = "Approve";
      ok.dataset.input = input;
      ok.addEventListener("click", decide.bind(ok, a.approval_id, true));
      var no = document.createElement("button");
      no.className = "reject"; no.textContent = "Reject";
      no.addEventListener("click", decide.bind(no, a.approval_id, false));
      actions.appendChild(ok); actions.appendChild(no);
      box.appendChild(div);
    });
  }

  async function refresh() {
    try {
      var status = await api("/v2/status");
      setHealth(true, "connected");
      $("hint").style.display = "none";
      renderConstraints(status.constraints);
      renderProviders(status.providers);
      renderAgents(status.agents);
      renderUsage(status.usage);
      try { renderStats(await api("/v2/stats")); } catch (e) {}
      var ap = await api("/v2/approvals");
      renderApprovals(ap.approvals || []);
      showError("");
    } catch (e) {
      setHealth(false, "error");
      showError(String(e) + " — is the backend running and CORS enabled?");
    }
  }

  function connect() {
    base = ($("baseUrl").value || "http://localhost:8000").replace(/\/+$/, "");
    try { localStorage.setItem("po.baseUrl", base); } catch (e) {}
    if (timer) clearInterval(timer);
    refresh();
    timer = setInterval(refresh, POLL_MS);
  }

  window.addEventListener("DOMContentLoaded", function () {
    var saved = "";
    try { saved = localStorage.getItem("po.baseUrl") || ""; } catch (e) {}
    $("baseUrl").value = saved || "http://localhost:8000";
    $("connect").addEventListener("click", connect);
    $("baseUrl").addEventListener("keydown", function (e) {
      if (e.key === "Enter") connect();
    });
  });
})();
