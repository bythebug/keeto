"""
Keeto web dashboard — FastAPI + HTMX + SSE.

Issues #31–38: server skeleton, trace list, trace detail, SSE live updates,
cost chart (Chart.js), error panel, recommendations panel, auto-open browser.

Start with:
    from keeto.dashboard.web.server import start_web_dashboard
    start_web_dashboard(storage, block=False)   # daemon thread, opens browser
    start_web_dashboard(storage, block=True)    # blocks (e.g. CLI usage)
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import webbrowser
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from keeto.dashboard.tui.widgets._utils import _age, _fmt_cost, _fmt_lat, _fmt_tokens
from keeto.dashboard.tui.widgets.timeline import build_waterfall

if TYPE_CHECKING:
    from keeto.storage.base import StorageBackend


# ---------------------------------------------------------------------------
# HTML shell
# ---------------------------------------------------------------------------

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Keeto — AI Observability</title>
  <script src="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg:        #0f1117;
      --surface:   #1a1d27;
      --border:    #2e3142;
      --accent:    #6c8fff;
      --success:   #4ade80;
      --warning:   #facc15;
      --danger:    #f87171;
      --text:      #e2e8f0;
      --muted:     #64748b;
      --font:      'Menlo', 'Consolas', monospace;
    }}
    :root.light {{
      --bg:        #f8fafc;
      --surface:   #ffffff;
      --border:    #e2e8f0;
      --accent:    #3b5bdb;
      --success:   #16a34a;
      --warning:   #ca8a04;
      --danger:    #dc2626;
      --text:      #1e293b;
      --muted:     #64748b;
    }}
    #theme-toggle {{
      margin-left: 8px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      cursor: pointer;
      font-family: var(--font);
      font-size: 12px;
      padding: 3px 10px;
    }}
    #theme-toggle:hover {{ background: var(--accent); color: #fff; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      font-size: 13px;
      min-height: 100vh;
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 10px 20px;
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    header h1 {{ font-size: 18px; color: var(--accent); letter-spacing: 2px; }}
    #live-badge {{
      margin-left: auto;
      background: var(--border);
      border-radius: 12px;
      padding: 3px 10px;
      font-size: 12px;
      color: var(--success);
    }}
    main {{
      display: grid;
      grid-template-columns: 1fr 380px;
      gap: 0;
      height: calc(100vh - 41px);
    }}
    .left-col {{
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .right-col {{
      border-left: 1px solid var(--border);
      overflow-y: auto;
      padding: 16px;
    }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }}
    .panel-header {{
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      font-size: 11px;
      letter-spacing: 1px;
      color: var(--muted);
      text-transform: uppercase;
    }}
    .panel-body {{ padding: 12px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{
      text-align: left;
      color: var(--muted);
      font-weight: normal;
      padding: 4px 8px;
      font-size: 11px;
      border-bottom: 1px solid var(--border);
    }}
    td {{ padding: 5px 8px; border-bottom: 1px solid var(--border); }}
    tr:last-child td {{ border-bottom: none; }}
    tr.trace-row {{ cursor: pointer; }}
    tr.trace-row:hover td {{ background: var(--border); }}
    .badge-ok    {{ color: var(--success); }}
    .badge-err   {{ color: var(--danger); }}
    .badge-warn  {{ color: var(--warning); }}
    .muted       {{ color: var(--muted); }}
    .detail-meta {{ margin-bottom: 12px; }}
    .detail-meta dt {{
      color: var(--muted); font-size: 11px;
      text-transform: uppercase; margin-top: 8px;
    }}
    .detail-meta dd {{ font-size: 13px; }}
    pre.waterfall {{
      font-family: var(--font);
      font-size: 12px;
      white-space: pre;
      overflow-x: auto;
      line-height: 1.6;
    }}
    .recommendations li {{ margin: 4px 0; padding: 4px 0; list-style: none; }}
    canvas {{ max-height: 200px; }}
    .no-data {{ color: var(--muted); padding: 12px; text-align: center; }}
    a {{ color: var(--accent); text-decoration: none; }}
  </style>
</head>
<body>
<header>
  <h1>keeto</h1>
  <span class="muted">AI Observability</span>
  <span id="live-badge">&#9679; {trace_count} traces</span>
  <button id="theme-toggle" onclick="toggleTheme()" title="Toggle dark/light mode">&#9788;</button>
</header>
<script>
  (function() {{
    if (localStorage.getItem('keeto-theme') === 'light') {{
      document.documentElement.classList.add('light');
    }}
  }})();
  function toggleTheme() {{
    const isLight = document.documentElement.classList.toggle('light');
    localStorage.setItem('keeto-theme', isLight ? 'light' : 'dark');
  }}
</script>
<main>
  <div class="left-col">

    <!-- Traces panel -->
    <div class="panel">
      <div class="panel-header">Recent Traces</div>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Age</th><th>Provider</th><th>Model</th>
            <th>Latency</th><th>In</th><th>Out</th><th>Cost</th><th></th>
          </tr>
        </thead>
        <tbody id="traces-tbody"
               hx-get="/api/traces"
               hx-trigger="every 2s"
               hx-target="#traces-tbody"
               hx-swap="innerHTML">
          {traces_rows}
        </tbody>
      </table>
    </div>

    <!-- Cost chart panel -->
    <div class="panel">
      <div class="panel-header">Cost by Model</div>
      <div class="panel-body">
        <canvas id="cost-chart"></canvas>
      </div>
    </div>

    <!-- Errors panel -->
    <div class="panel">
      <div class="panel-header">Errors</div>
      <table>
        <thead>
          <tr><th>ID</th><th>Model</th><th>Age</th><th>Message</th></tr>
        </thead>
        <tbody id="errors-tbody"
               hx-get="/api/traces?errors_only=1"
               hx-trigger="every 5s"
               hx-target="#errors-tbody"
               hx-swap="innerHTML">
          {errors_rows}
        </tbody>
      </table>
    </div>

    <!-- Recommendations panel -->
    <div class="panel">
      <div class="panel-header">Recommendations</div>
      <div class="panel-body">
        {recommendations}
      </div>
    </div>

  </div><!-- /left-col -->

  <div class="right-col">
    <div id="detail-panel" class="panel">
      <div class="panel-header">Trace Detail</div>
      <div class="panel-body no-data">Select a trace to inspect</div>
    </div>
  </div>
</main>

<script>
// SSE live counter
const es = new EventSource('/api/stream');
es.onmessage = function(e) {{
  try {{
    const d = JSON.parse(e.data);
    document.getElementById('live-badge').textContent = '● ' + d.count + ' traces';
  }} catch(_) {{}}
}};

// Cost chart
async function loadChart() {{
  try {{
    const r = await fetch('/api/metrics');
    const d = await r.json();
    const ctx = document.getElementById('cost-chart').getContext('2d');
    const labels = d.model_breakdown.map(m => m.model);
    const data   = d.model_breakdown.map(m => m.cost);
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: labels.length ? labels : ['(no data)'],
        datasets: [{{
          label: 'Cost (USD)',
          data: data.length ? data : [0],
          backgroundColor: '#6c8fff99',
          borderColor: '#6c8fff',
          borderWidth: 1,
        }}]
      }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#2e3142' }} }},
          y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#2e3142' }} }},
        }}
      }}
    }});
  }} catch(e) {{ console.error('Chart load failed', e); }}
}}
loadChart();
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# HTML fragment builders
# ---------------------------------------------------------------------------

_RICH_TAG = re.compile(r"\[/?[a-zA-Z0-9_ /=#]*\]")


def _strip_rich(text: str) -> str:
    return _RICH_TAG.sub("", text)


def _trace_rows(traces: list) -> str:  # type: ignore[type-arg]
    if not traces:
        return '<tr><td colspan="9" class="no-data">No traces captured yet</td></tr>'
    rows = []
    for t in traces:
        status_cls = "badge-err" if t.has_error else "badge-ok"
        status_sym = "✗" if t.has_error else "✓"
        rows.append(
            f'<tr class="trace-row" hx-get="/api/traces/{t.trace_id}"'
            f' hx-target="#detail-panel" hx-swap="innerHTML">'
            f"<td>{t.trace_id[:8]}</td>"
            f"<td class='muted'>{_age(t.start_time)}</td>"
            f"<td>{t.provider or '&mdash;'}</td>"
            f"<td>{(t.model or '&mdash;')[:20]}</td>"
            f"<td>{_fmt_lat(t.latency_ms)}</td>"
            f"<td>{_fmt_tokens(t.total_input_tokens)}</td>"
            f"<td>{_fmt_tokens(t.total_output_tokens)}</td>"
            f"<td>{_fmt_cost(t.total_cost_usd)}</td>"
            f"<td class='{status_cls}'>{status_sym}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _error_rows(traces: list) -> str:  # type: ignore[type-arg]
    errors = [t for t in traces if t.has_error]
    if not errors:
        return '<tr><td colspan="4" class="no-data">No errors</td></tr>'
    rows = []
    for t in errors:
        msg = ""
        for s in t.spans:
            if s.status_message:
                msg = s.status_message[:60]
                break
        rows.append(
            f"<tr>"
            f"<td>{t.trace_id[:8]}</td>"
            f"<td>{(t.model or '&mdash;')[:16]}</td>"
            f"<td class='muted'>{_age(t.start_time)}</td>"
            f"<td class='badge-err'>{msg or '(no message)'}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _recommendations_html(traces: list) -> str:  # type: ignore[type-arg]
    items: list[str] = []
    if not traces:
        return (
            '<ul class="recommendations" id="recommendations">'
            '<li class="muted">No data yet</li></ul>'
        )

    total_cost = sum(t.total_cost_usd for t in traces)
    error_count = sum(1 for t in traces if t.has_error)
    lats = [t.latency_ms for t in traces if t.latency_ms is not None]
    slow = [lat for lat in lats if lat > 5000]

    if slow:
        items.append(
            f'<li class="badge-warn">&#9889; {len(slow)} request(s) exceed 5s'
            " &mdash; consider streaming</li>"
        )
    if total_cost > 1.0:
        items.append(
            f'<li class="badge-warn">&#128176; Total cost ${total_cost:.2f}'
            " exceeds $1 &mdash; review model usage</li>"
        )
    if error_count > 0:
        items.append(
            f'<li class="badge-err">&#9888; {error_count} error(s) detected'
            " in this session</li>"
        )
    if not items:
        items.append(
            '<li class="badge-ok">&#10003; No recommendations &mdash; looking good!</li>'
        )

    body = "\n".join(items)
    return f'<ul class="recommendations" id="recommendations">\n{body}\n</ul>'


def _trace_detail_html(trace) -> str:  # type: ignore[no-untyped-def]
    waterfall_raw = build_waterfall(trace, bar_cols=40)
    waterfall_plain = _strip_rich(waterfall_raw)

    provider = trace.provider or "—"
    model = trace.model or "—"
    latency = _fmt_lat(trace.latency_ms)
    cost = _fmt_cost(trace.total_cost_usd)
    in_tok = _fmt_tokens(trace.total_input_tokens)
    out_tok = _fmt_tokens(trace.total_output_tokens)
    status_cls = "badge-err" if trace.has_error else "badge-ok"
    status_txt = "error" if trace.has_error else "ok"

    return (
        '<div class="panel-header">Trace Detail</div>'
        '<div class="panel-body">'
        '<dl class="detail-meta">'
        f"<dt>Trace ID</dt><dd>{trace.trace_id}</dd>"
        f"<dt>Provider</dt><dd>{provider}</dd>"
        f"<dt>Model</dt><dd>{model}</dd>"
        f"<dt>Latency</dt><dd>{latency}</dd>"
        f"<dt>Cost</dt><dd>{cost}</dd>"
        f"<dt>Tokens</dt><dd>{in_tok} in / {out_tok} out</dd>"
        f'<dt>Status</dt><dd class="{status_cls}">{status_txt}</dd>'
        "</dl>"
        '<div class="panel-header" style="margin:8px -12px;padding:8px 12px">Timeline</div>'
        f"<pre class='waterfall'>{waterfall_plain}</pre>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(storage: "StorageBackend") -> FastAPI:
    app = FastAPI(title="Keeto", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        traces = await storage.list_traces(limit=200)
        recs = _recommendations_html(traces)
        return HTMLResponse(
            _PAGE_TEMPLATE.format(
                trace_count=len(traces),
                traces_rows=_trace_rows(traces),
                errors_rows=_error_rows(traces),
                recommendations=recs,
            )
        )

    @app.get("/api/traces", response_class=HTMLResponse)
    async def api_traces(errors_only: int = Query(default=0)) -> HTMLResponse:
        traces = await storage.list_traces(limit=200)
        if errors_only:
            return HTMLResponse(_error_rows(traces))
        return HTMLResponse(_trace_rows(traces))

    @app.get("/api/traces/{trace_id}", response_class=HTMLResponse)
    async def api_trace_detail(trace_id: str) -> HTMLResponse:
        trace = await storage.get_trace(trace_id)
        if trace is None:
            return HTMLResponse(
                '<div class="no-data">Trace not found</div>', status_code=404
            )
        return HTMLResponse(_trace_detail_html(trace))

    @app.get("/api/metrics")
    async def api_metrics() -> JSONResponse:
        traces = await storage.list_traces(limit=1000)
        total_cost = sum(t.total_cost_usd for t in traces)

        midnight = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_cost = sum(
            t.total_cost_usd for t in traces if t.start_time >= midnight
        )
        lats = [t.latency_ms for t in traces if t.latency_ms is not None]
        avg_lat = sum(lats) / len(lats) if lats else 0.0
        error_count = sum(1 for t in traces if t.has_error)

        model_agg: dict[str, dict[str, float | int]] = {}
        for t in traces:
            key = t.model or "unknown"
            if key not in model_agg:
                model_agg[key] = {"cost": 0.0, "requests": 0}
            model_agg[key]["cost"] = float(model_agg[key]["cost"]) + t.total_cost_usd
            model_agg[key]["requests"] = int(model_agg[key]["requests"]) + 1

        breakdown = [
            {
                "model": k,
                "cost": round(float(v["cost"]), 6),
                "requests": int(v["requests"]),
            }
            for k, v in sorted(
                model_agg.items(), key=lambda x: x[1]["cost"], reverse=True
            )
        ]

        return JSONResponse({
            "total_cost_usd": round(total_cost, 6),
            "today_cost_usd": round(today_cost, 6),
            "total_traces": len(traces),
            "avg_latency_ms": round(avg_lat, 2),
            "error_count": error_count,
            "model_breakdown": breakdown,
        })

    @app.get("/api/recommendations", response_class=HTMLResponse)
    async def api_recommendations() -> HTMLResponse:
        traces = await storage.list_traces(limit=200)
        return HTMLResponse(_recommendations_html(traces))

    @app.get("/api/stream")
    async def api_stream() -> StreamingResponse:
        async def generator() -> AsyncGenerator[str, None]:
            while True:
                traces = await storage.list_traces(limit=1000)
                payload = json.dumps({
                    "count": len(traces),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                yield f"data: {payload}\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def start_web_dashboard(
    storage: "StorageBackend",
    host: str = "127.0.0.1",
    port: int = 7842,
    block: bool = True,
) -> None:
    """
    Start the Keeto web dashboard.

    block=True  — run uvicorn in the current thread (blocks until Ctrl-C).
    block=False — run uvicorn in a daemon thread and return immediately;
                  also opens the browser automatically.
    """
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "Web dashboard requires uvicorn. Install with: pip install keeto[web]"
        ) from exc

    app = create_app(storage)

    if block:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    else:
        def _run() -> None:
            uvicorn.run(app, host=host, port=port, log_level="warning")

        thread = threading.Thread(target=_run, daemon=True, name="keeto-web")
        thread.start()
        time.sleep(1.0)
        webbrowser.open(f"http://{host}:{port}")
