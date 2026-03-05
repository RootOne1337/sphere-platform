# -*- coding: utf-8 -*-
"""
Генератор HTML/JSON отчётов по нагрузочному тестированию.

Создаёт самодостаточный HTML с таблицами, графиками (Chart.js CDN)
и детализацией по шагам.
"""
from __future__ import annotations

import html
import json
from typing import Any


class ReportGenerator:
    """Генератор отчётов по результатам нагрузочного теста."""

    @staticmethod
    def to_html(data: dict[str, Any]) -> str:
        """Генерировать самодостаточный HTML-отчёт."""
        test_name = html.escape(str(data.get("test_name", "load-test")))
        overall = data.get("overall_passed", False)
        duration = data.get("total_duration_sec", 0)
        steps = data.get("steps", [])

        status_cls = "pass" if overall else "fail"
        status_text = "PASS" if overall else "FAIL"

        # Строки таблицы шагов
        step_rows = ""
        for s in steps:
            s_cls = "pass" if s.get("passed") else "fail"
            violations = ", ".join(s.get("violations", [])) or "—"
            step_rows += f"""
            <tr class="{s_cls}">
              <td>{html.escape(s.get('name', ''))}</td>
              <td>{s.get('target', 0)}</td>
              <td>{s.get('actual_online', 0)}</td>
              <td>{s.get('fleet_availability', 0):.1f}%</td>
              <td>{s.get('duration_sec', 0):.0f}s</td>
              <td class="status-{s_cls}">{s_cls.upper()}</td>
              <td class="violations">{html.escape(violations)}</td>
            </tr>"""

        # Chart.js данные
        labels = json.dumps([s.get("name", "") for s in steps])
        fa_data = json.dumps(
            [round(s.get("fleet_availability", 0), 1) for s in steps]
        )
        target_data = json.dumps([s.get("target", 0) for s in steps])
        online_data = json.dumps([s.get("actual_online", 0) for s in steps])

        # Метрики в JSON-блоке
        metrics_json = json.dumps(data, indent=2, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Load Test Report — {test_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --red: #f85149; --blue: #58a6ff; --yellow: #d29922;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); padding: 2rem;
  }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.3rem; margin: 1.5rem 0 0.8rem; color: var(--muted); }}
  .badge {{
    display: inline-block; padding: 0.3rem 1rem; border-radius: 6px;
    font-weight: 700; font-size: 1.1rem; margin-left: 1rem;
  }}
  .badge.pass {{ background: var(--green); color: #000; }}
  .badge.fail {{ background: var(--red); color: #fff; }}
  .meta {{ color: var(--muted); margin-bottom: 1.5rem; }}
  table {{
    width: 100%; border-collapse: collapse; margin-bottom: 1.5rem;
    background: var(--card); border-radius: 8px; overflow: hidden;
  }}
  th, td {{ padding: 0.7rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ background: var(--border); font-weight: 600; }}
  tr.pass td {{ border-left: 3px solid var(--green); }}
  tr.fail td {{ border-left: 3px solid var(--red); }}
  .status-pass {{ color: var(--green); font-weight: 700; }}
  .status-fail {{ color: var(--red); font-weight: 700; }}
  .violations {{ font-size: 0.85rem; color: var(--yellow); }}
  .chart-container {{
    background: var(--card); border-radius: 8px; padding: 1.5rem;
    margin-bottom: 1.5rem; max-width: 900px;
  }}
  canvas {{ max-height: 350px; }}
  details {{
    background: var(--card); border-radius: 8px; padding: 1rem;
    margin-bottom: 1rem;
  }}
  summary {{ cursor: pointer; font-weight: 600; color: var(--blue); }}
  pre {{
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 1rem; overflow-x: auto;
    font-size: 0.82rem; color: var(--muted); margin-top: 0.5rem;
    max-height: 500px;
  }}
</style>
</head>
<body>

<h1>
  Нагрузочный тест: {test_name}
  <span class="badge {status_cls}">{status_text}</span>
</h1>
<p class="meta">Длительность: {duration:.0f} сек &nbsp;|&nbsp; Шагов: {len(steps)}</p>

<h2>Шаги</h2>
<table>
  <thead>
    <tr>
      <th>Шаг</th><th>Target</th><th>Online</th>
      <th>FA</th><th>Время</th><th>Статус</th><th>Нарушения</th>
    </tr>
  </thead>
  <tbody>{step_rows}
  </tbody>
</table>

<h2>Fleet Availability</h2>
<div class="chart-container">
  <canvas id="faChart"></canvas>
</div>

<h2>Масштабирование</h2>
<div class="chart-container">
  <canvas id="scaleChart"></canvas>
</div>

<h2>Полный дамп метрик</h2>
<details>
  <summary>Показать JSON</summary>
  <pre>{html.escape(metrics_json)}</pre>
</details>

<script>
const labels = {labels};
// Fleet Availability chart
new Chart(document.getElementById('faChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      label: 'Fleet Availability %',
      data: {fa_data},
      borderColor: '#3fb950',
      backgroundColor: 'rgba(63,185,80,0.15)',
      fill: true, tension: 0.3
    }}, {{
      label: 'Порог 97%',
      data: labels.map(() => 97),
      borderColor: '#f85149',
      borderDash: [5,5],
      pointRadius: 0, fill: false
    }}]
  }},
  options: {{
    scales: {{
      y: {{ min: 0, max: 100, grid: {{ color: '#30363d' }} }},
      x: {{ grid: {{ color: '#30363d' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }}
  }}
}});

// Scale chart
new Chart(document.getElementById('scaleChart'), {{
  type: 'bar',
  data: {{
    labels,
    datasets: [{{
      label: 'Target',
      data: {target_data},
      backgroundColor: 'rgba(88,166,255,0.5)',
      borderColor: '#58a6ff', borderWidth: 1
    }}, {{
      label: 'Online',
      data: {online_data},
      backgroundColor: 'rgba(63,185,80,0.5)',
      borderColor: '#3fb950', borderWidth: 1
    }}]
  }},
  options: {{
    scales: {{
      y: {{ grid: {{ color: '#30363d' }} }},
      x: {{ grid: {{ color: '#30363d' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }}
  }}
}});
</script>

</body>
</html>"""
