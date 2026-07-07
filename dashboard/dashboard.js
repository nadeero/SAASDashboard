/**
 * dashboard/dashboard.js
 *
 * Renders the Revenue Intelligence dashboard from a data payload.
 *
 * DESIGN DECISION: The dashboard works in two modes:
 *   1. STATIC (default): reads the embedded JSON snapshot in the
 *      <script id="dashboard-data"> tag, generated from the real ETL
 *      pipeline. This lets the dashboard be opened as a plain HTML file
 *      (no server required) for portfolio screenshots / review.
 *   2. LIVE: if the person enters the running Flask API's base URL
 *      (e.g. http://localhost:5000) and clicks "Load from live API", the
 *      dashboard fetches all /api/kpis/* endpoints and re-renders with
 *      live data. This demonstrates the full-stack wiring, not just a
 *      static export.
 *
 * All rendering logic is factored into render(payload) so both modes
 * share one code path -- there is no separate "static charts" vs "live
 * charts" implementation to keep in sync.
 */

const CHART_COLORS = {
  gold: "#D4A03C",
  teal: "#2FBF9F",
  red: "#E0616B",
  blue: "#6E8CFF",
  muted: "#8996AF",
  grid: "#1B2436",
};

const charts = {}; // keep references so we can .destroy() before re-render

function fmtCurrency(n) {
  if (n === null || n === undefined || isNaN(n)) return "$0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtPct(n, digits = 1) {
  if (n === null || n === undefined || isNaN(n)) return "0%";
  return `${n.toFixed(digits)}%`;
}

function fmtInt(n) {
  return Number(n).toLocaleString("en-US");
}

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function renderTicker(summary, forecast) {
  const cells = [
    { label: "ARR", value: fmtCurrency(summary.arr) },
    { label: "MRR", value: fmtCurrency(summary.mrr) },
    {
      label: "MRR Growth (MoM)",
      value: fmtPct(summary.mrr_mom_growth_pct),
      cls: summary.mrr_mom_growth_pct >= 0 ? "pos" : "neg",
    },
    { label: "Win Rate", value: fmtPct(summary.win_rate_pct) },
    { label: "Open Pipeline", value: fmtCurrency(summary.open_pipeline_value), sub: `${fmtInt(summary.open_opportunity_count)} deals` },
    { label: "Weighted Forecast", value: fmtCurrency(forecast.weighted_forecast) },
  ];

  const el = document.getElementById("ticker");
  el.innerHTML = cells
    .map(
      (c) => `
      <div class="ticker-cell">
        <div class="ticker-label">${c.label}</div>
        <div class="ticker-value ${c.cls || ""}">${c.value}</div>
        ${c.sub ? `<div class="ticker-sub">${c.sub}</div>` : ""}
      </div>`
    )
    .join("");
}

function renderRevenueChart(timeseries) {
  destroyChart("revenue");
  const ctx = document.getElementById("revenueChart");
  charts.revenue = new Chart(ctx, {
    type: "line",
    data: {
      labels: timeseries.map((r) => r.month),
      datasets: [
        {
          label: "MRR",
          data: timeseries.map((r) => r.mrr),
          borderColor: CHART_COLORS.gold,
          backgroundColor: "rgba(212,160,60,0.12)",
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: CHART_COLORS.muted, maxTicksLimit: 8, font: { family: "monospace", size: 10 } }, grid: { color: CHART_COLORS.grid } },
        y: {
          ticks: { color: CHART_COLORS.muted, callback: (v) => fmtCurrency(v), font: { family: "monospace", size: 10 } },
          grid: { color: CHART_COLORS.grid },
        },
      },
    },
  });
}

function renderLeaderboard(rows) {
  const top = [...rows]
    .sort((a, b) => b.revenue_closed - a.revenue_closed)
    .slice(0, 8);
  const tbody = document.querySelector("#leaderboardTable tbody");
  tbody.innerHTML = top
    .map((r, i) => {
      const total = r.deals_won + r.deals_lost;
      const winPct = total > 0 ? (r.deals_won / total) * 100 : 0;
      return `<tr>
        <td class="rank">${i + 1}</td>
        <td class="name-cell">${r.rep_name}</td>
        <td>${r.region}</td>
        <td>${r.deals_won}</td>
        <td>${fmtPct(winPct)}</td>
        <td>${fmtCurrency(r.revenue_closed)}</td>
      </tr>`;
    })
    .join("");
}

function renderFunnel(funnel) {
  const maxCount = Math.max(...funnel.map((f) => f.count), 1);
  const el = document.getElementById("funnel");
  el.innerHTML = funnel
    .map((f) => {
      const width = (f.count / maxCount) * 100;
      const conv = f.conversion_from_previous_stage_pct;
      return `<div class="funnel-row">
        <div class="funnel-label">${f.stage}</div>
        <div class="funnel-bar-track"><div class="funnel-bar-fill" style="width:${width}%"></div></div>
        <div class="funnel-count">${fmtInt(f.count)}</div>
        <div class="funnel-conv">${conv !== null && conv !== undefined ? fmtPct(conv) : "&mdash;"}</div>
      </div>`;
    })
    .join("");
}

function renderChurnTable(rows) {
  const top = [...rows]
    .sort((a, b) => b.risk_score - a.risk_score)
    .slice(0, 8);
  const tbody = document.querySelector("#churnTable tbody");
  tbody.innerHTML = top
    .map(
      (r) => `<tr>
        <td class="name-cell">${r.company_name}</td>
        <td>${r.industry}</td>
        <td>${r.last_close_date}</td>
        <td><span class="badge ${r.risk_band}">${r.risk_band}</span></td>
      </tr>`
    )
    .join("");
}

function renderPipelineChart(byStage) {
  destroyChart("pipeline");
  const ctx = document.getElementById("pipelineChart");
  const order = ["Prospecting", "Qualification", "Needs Analysis", "Proposal", "Negotiation"];
  const sorted = [...byStage].sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage));
  charts.pipeline = new Chart(ctx, {
    type: "bar",
    data: {
      labels: sorted.map((r) => r.stage),
      datasets: [
        {
          data: sorted.map((r) => r.total_value),
          backgroundColor: CHART_COLORS.blue,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: CHART_COLORS.muted, font: { size: 9 } }, grid: { display: false } },
        y: { ticks: { color: CHART_COLORS.muted, callback: (v) => fmtCurrency(v), font: { size: 9 } }, grid: { color: CHART_COLORS.grid } },
      },
    },
  });
}

function renderSegmentChart(segmentation) {
  destroyChart("segment");
  const ctx = document.getElementById("segmentChart");

  const byIndustry = {};
  segmentation.forEach((row) => {
    byIndustry[row.industry] = byIndustry[row.industry] || { SMB: 0, "Mid-Market": 0, Enterprise: 0 };
    byIndustry[row.industry][row.company_size] = row.total_revenue;
  });
  const topIndustries = Object.entries(byIndustry)
    .map(([industry, sizes]) => [industry, sizes.SMB + sizes["Mid-Market"] + sizes.Enterprise])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([industry]) => industry);

  charts.segment = new Chart(ctx, {
    type: "bar",
    data: {
      labels: topIndustries,
      datasets: [
        { label: "SMB", data: topIndustries.map((i) => byIndustry[i].SMB), backgroundColor: CHART_COLORS.teal },
        { label: "Mid-Market", data: topIndustries.map((i) => byIndustry[i]["Mid-Market"]), backgroundColor: CHART_COLORS.gold },
        { label: "Enterprise", data: topIndustries.map((i) => byIndustry[i].Enterprise), backgroundColor: CHART_COLORS.blue },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "bottom", labels: { color: CHART_COLORS.muted, font: { size: 9 }, boxWidth: 10 } },
      },
      scales: {
        x: { stacked: true, ticks: { color: CHART_COLORS.muted, font: { size: 8 } }, grid: { display: false } },
        y: { stacked: true, ticks: { color: CHART_COLORS.muted, callback: (v) => fmtCurrency(v), font: { size: 9 } }, grid: { color: CHART_COLORS.grid } },
      },
    },
  });
}

function renderActivityChart(activity) {
  destroyChart("activity");
  const ctx = document.getElementById("activityChart");
  charts.activity = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: activity.map((a) => a.activity_type),
      datasets: [
        {
          data: activity.map((a) => a.activity_count),
          backgroundColor: [CHART_COLORS.gold, CHART_COLORS.teal, CHART_COLORS.blue, CHART_COLORS.red, "#B98BD9", "#5AC8E0"],
          borderColor: "#121A29",
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "bottom", labels: { color: CHART_COLORS.muted, font: { size: 9 }, boxWidth: 10 } },
      },
    },
  });
}

function render(payload) {
  document.getElementById("as-of-text").textContent = `Snapshot as of ${payload.generated_at || payload.summary?.as_of || "\u2014"}`;
  renderTicker(payload.summary, payload.forecast);
  renderRevenueChart(payload.revenue_timeseries);
  renderLeaderboard(payload.rep_leaderboard);
  renderFunnel(payload.funnel);
  renderChurnTable(payload.churn_risk_top || payload.churn_risk || []);
  renderPipelineChart(payload.pipeline_by_stage);
  renderSegmentChart(payload.segmentation);
  renderActivityChart(payload.activity_volume);
}

async function loadFromLiveApi(baseUrl) {
  const statusEl = document.getElementById("status-msg");
  statusEl.textContent = "Loading\u2026";
  try {
    const [summary, revenueTs, pipeline, funnel, leaderboard, segmentation, churn, activity] = await Promise.all([
      fetch(`${baseUrl}/api/kpis/summary`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/revenue-timeseries`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/pipeline`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/funnel`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/rep-leaderboard`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/segmentation`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/churn-risk`).then((r) => r.json()),
      fetch(`${baseUrl}/api/kpis/activity-volume`).then((r) => r.json()),
    ]);

    render({
      generated_at: "live",
      summary,
      revenue_timeseries: revenueTs,
      pipeline_by_stage: pipeline.by_stage,
      forecast: pipeline.forecast,
      funnel,
      rep_leaderboard: leaderboard,
      segmentation,
      churn_risk_top: churn,
      activity_volume: activity,
    });
    statusEl.textContent = "Connected \u2014 live data loaded.";
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Could not reach API (check URL, CORS, and that Flask is running).";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const dataEl = document.getElementById("dashboard-data");
  let payload;
  try {
    payload = JSON.parse(dataEl.textContent);
  } catch (e) {
    payload = null;
  }
  if (payload) render(payload);

  document.getElementById("connectBtn").addEventListener("click", () => {
    const base = document.getElementById("apiBase").value.trim().replace(/\/$/, "");
    if (!base) {
      document.getElementById("status-msg").textContent = "Enter an API base URL first.";
      return;
    }
    loadFromLiveApi(base);
  });
});
