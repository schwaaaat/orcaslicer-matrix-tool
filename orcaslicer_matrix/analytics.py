"""Analytics, G-code Line-Type Parser, Delta Engine, and Reporting for OrcaSlicer Matrix Tool.

Provides:
- Fast G-code streaming parser to extract filament mass by extrusion role (Inner wall, Outer wall,
  Infill, Brim, Support, etc.).
- Multi-variant comparison engine calculating time and material deltas against baseline.
- Pareto optimality and recommendation solver (fastest, lightest, best trade-off).
- GitHub-flavored Markdown tables matching Image 1 (Summary) and Image 2 (Filament by line type).
- Self-contained dark-themed HTML report generator with embedded vector charts (Pareto Frontier,
  Stacked Bar breakdown).
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CANONICAL_ROLE_ORDER = [
    "Inner wall",
    "Outer wall",
    "Sparse infill",
    "Internal solid infill",
    "Top surface",
    "Bottom surface",
    "Brim",
    "Support",
    "Support interface",
    "Bridge",
    "Internal Bridge",
    "Gap infill",
    "Custom",
    "Other",
]

ROLE_COLORS: Dict[str, str] = {
    "Inner wall": "#2563eb",             # Royal Blue
    "Outer wall": "#059669",             # Vibrant Emerald
    "Sparse infill": "#f59e0b",          # Amber
    "Internal solid infill": "#8b5cf6",  # Purple
    "Top surface": "#ec4899",            # Pink
    "Bottom surface": "#6366f1",         # Indigo
    "Brim": "#64748b",                   # Slate Gray
    "Support": "#06b6d4",                # Cyan
    "Support interface": "#0891b2",      # Dark Cyan
    "Bridge": "#ef4444",                 # Red
    "Internal Bridge": "#f97316",        # Orange
    "Gap infill": "#14b8a6",             # Teal
    "Custom": "#a855f7",                 # Lavender
    "Other": "#94a3b8",                  # Cool Gray
}

FALLBACK_PALETTE: List[str] = [
    "#2563eb", "#059669", "#f59e0b", "#8b5cf6", "#ec4899",
    "#6366f1", "#64748b", "#06b6d4", "#ef4444", "#14b8a6",
    "#f97316", "#a855f7",
]


def get_role_color(role: str) -> str:
    """Return a consistent, high-contrast hex color for a given extrusion role."""
    if role in ROLE_COLORS:
        return ROLE_COLORS[role]
    idx = abs(hash(role)) % len(FALLBACK_PALETTE)
    return FALLBACK_PALETTE[idx]


def format_compact_label(name: str) -> str:
    """Turn a verbose variant name like 'layer_height=0.16, wall_loops=2' into '0.16mm • 2w'.

    Extracts essential distinguishing values without repeating verbose setting keys.
    """
    if not name:
        return ""
    parts = [p.strip() for p in name.split(",") if p.strip()]
    short_parts: List[str] = []
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "layer_height":
                short_parts.append(f"{v}mm" if not v.endswith("mm") else v)
            elif k == "wall_loops":
                short_parts.append(f"{v}w")
            elif k == "sparse_infill_density":
                short_parts.append(v)
            elif k == "sparse_infill_pattern":
                short_parts.append(v)
            elif k == "wall_generator":
                short_parts.append(v[:4])
            elif k == "seam_position":
                short_parts.append(f"seam:{v[:3]}")
            elif k == "outer_wall_speed":
                short_parts.append(f"{v}mm/s" if not v.endswith("mm/s") else v)
            else:
                words = k.split("_")
                k_abbr = "".join(w[0] for w in words if w)[:3] or k[:3]
                short_parts.append(f"{k_abbr}:{v}")
        else:
            short_parts.append(part)
    return " • ".join(short_parts)



def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds into 'Xh Ym' or 'Ym' or 'Zs'."""
    if seconds is None or seconds < 0:
        return "-"
    total_sec = int(round(seconds))
    if total_sec < 60:
        return f"{total_sec}s"
    total_min = int(round(total_sec / 60.0))
    h, m = divmod(total_min, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def signed_time_delta(delta_s: float) -> str:
    """Format time difference as signed '+Xm' or '-Xm'."""
    if abs(delta_s) < 30:
        return "0m"
    total_min = int(round(abs(delta_s) / 60.0))
    h, m = divmod(total_min, 60)
    time_str = f"{h}h {m:02d}m" if h > 0 else f"{m}m"
    sign = "+" if delta_s > 0 else "-"
    return f"{sign}{time_str}"


def signed_mass_delta(delta_g: float) -> str:
    """Format filament mass difference as signed '+X.Xg' or '-X.Xg'."""
    r = round(delta_g, 1)
    if abs(r) < 0.05:
        return "0.0g"
    sign = "+" if r > 0 else "-"
    return f"{sign}{abs(r):.1f}g"


def parse_gcode_filament_by_role(
    gcode_path: Path,
    fallback_mass_g: Optional[float] = None,
) -> Dict[str, float]:
    """Parse a G-code file and calculate filament mass in grams spent on each extrusion role.

    Streams the file line by line to minimize memory usage on large files.
    Extracts '; FEATURE: <role>' markers, calculates positive extrusion lengths (E),
    and normalizes against the total filament mass reported in the G-code header/footer.

    Returns:
        Dictionary mapping canonical role names to mass in grams (e.g. {'Inner wall': 8.11}).
    """
    gpath = Path(gcode_path)
    if not gpath.is_file():
        return {}

    roles_e: Dict[str, float] = {}
    current_role = "Other"
    density = 1.25  # g/cm3 default
    diameter = 1.75  # mm default
    total_g_footer: Optional[float] = None
    is_relative_e = True  # OrcaSlicer default is M83
    prev_e = 0.0

    try:
        with open(gpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if line_str.startswith("; FEATURE:"):
                    current_role = line_str[10:].strip()
                elif line_str.startswith("; filament_density:"):
                    try:
                        density = float(line_str.split(":")[1].strip())
                    except Exception:
                        pass
                elif line_str.startswith("; filament_diameter:"):
                    try:
                        diameter = float(line_str.split(":")[1].strip())
                    except Exception:
                        pass
                elif line_str.startswith("; filament used [g] ="):
                    try:
                        total_g_footer = float(line_str.split("=")[1].strip())
                    except Exception:
                        pass
                elif line_str == "M82":
                    is_relative_e = False
                elif line_str == "M83":
                    is_relative_e = True
                elif line_str.startswith("G92") and "E0" in line_str:
                    prev_e = 0.0
                elif line_str.startswith("G1 ") and "E" in line_str:
                    m = re.search(r"E(-?\d*\.?\d+)", line_str)
                    if m:
                        raw_e = float(m.group(1))
                        if is_relative_e:
                            delta_e = raw_e
                        else:
                            delta_e = raw_e - prev_e
                            prev_e = raw_e
                        if delta_e > 0.0001:
                            roles_e[current_role] = roles_e.get(current_role, 0.0) + delta_e

        total_e = sum(roles_e.values())
        if total_e <= 0:
            return {}

        # Determine target total mass
        if total_g_footer is not None and total_g_footer > 0:
            target_mass = total_g_footer
        elif fallback_mass_g is not None and fallback_mass_g > 0:
            target_mass = fallback_mass_g
        else:
            radius = diameter / 2.0
            area = math.pi * (radius**2)
            target_mass = (total_e * area / 1000.0) * density

        # Normalize proportions so sum matches total mass
        result: Dict[str, float] = {}
        for role, e_val in roles_e.items():
            fraction = e_val / total_e
            val = round(fraction * target_mass, 2)
            if val > 0.01:
                result[role] = val

        return result

    except Exception:
        return {}


def compute_matrix_comparison(
    variants: List[Dict[str, Any]],
    baseline_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze sliced matrix variants and calculate deltas, rankings, and markdown tables.

    Args:
        variants: List of variant result dictionaries from MatrixRunner or manifest.json.
        baseline_name: Name of the baseline variant. Defaults to first variant.

    Returns:
        Structured dictionary containing summary rows, line-type breakdown matrix,
        trade-off recommendations, and markdown tables.
    """
    if not variants:
        return {
            "baseline": None,
            "summary_rows": [],
            "line_type_matrix": {"columns": [], "rows": []},
            "recommendation": {"winner": None, "reason": "No variants to compare."},
            "summary_markdown": "",
            "line_type_markdown": "",
        }

    # Determine baseline
    names = [v["name"] for v in variants]
    if baseline_name and baseline_name in names:
        base_name = baseline_name
    else:
        # Default to first variant
        base_name = names[0]

    base_var = next((v for v in variants if v["name"] == base_name), variants[0])
    base_stats = base_var.get("stats") or {}
    base_time_s = base_stats.get("time_s")
    base_filament_g = base_stats.get("filament_g")

    # Filter successful candidates for extremes
    successful = [
        v for v in variants
        if not v.get("error") and (v.get("stats") or {}).get("time_s") is not None
    ]

    fastest_var = min(successful, key=lambda v: (v.get("stats") or {}).get("time_s", float("inf"))) if successful else None
    lightest_var = min(successful, key=lambda v: (v.get("stats") or {}).get("filament_g", float("inf"))) if successful else None

    fastest_name = fastest_var["name"] if fastest_var else None
    lightest_name = lightest_var["name"] if lightest_var else None

    # Determine recommendation
    warning_free = [v for v in successful if not (v.get("warnings"))]
    pool = warning_free if warning_free else successful
    recommended_var = min(pool, key=lambda v: (v.get("stats") or {}).get("time_s", float("inf"))) if pool else None
    recommended_name = recommended_var["name"] if recommended_var else None

    # Recommendation reason
    rec_reason = ""
    if recommended_name:
        parts = []
        if recommended_name == fastest_name:
            parts.append("fastest slice time")
        if recommended_name == lightest_name:
            parts.append("lowest filament usage")
        if warning_free and recommended_var in warning_free:
            parts.append("zero warnings")
        rec_reason = f"Suggested due to {', '.join(parts) if parts else 'balanced print characteristics'}."

    # Build summary rows
    summary_rows: List[Dict[str, Any]] = []
    for v in variants:
        v_name = v["name"]
        stats = v.get("stats") or {}
        time_s = stats.get("time_s")
        filament_g = stats.get("filament_g")
        cost_usd = stats.get("cost_usd")
        err = v.get("error")

        is_base = (v_name == base_name)
        is_fastest = (v_name == fastest_name and not is_base)
        is_lightest = (v_name == lightest_name and not is_base and not is_fastest)

        badge_parts = []
        if is_base:
            badge_parts.append("(baseline)")
        if is_fastest:
            badge_parts.append("★ fastest")
        elif is_lightest:
            badge_parts.append("★ lightest")

        display_name = f"{v_name} {' '.join(badge_parts)}".strip()

        # Delta calculation
        delta_str = "-"
        delta_t_s = 0.0
        delta_m_g = 0.0
        if not err and not is_base and base_time_s is not None and time_s is not None:
            delta_t_s = time_s - base_time_s
            delta_m_g = (filament_g - base_filament_g) if (filament_g is not None and base_filament_g is not None) else 0.0
            t_delta_str = signed_time_delta(delta_t_s)
            m_delta_str = signed_mass_delta(delta_m_g)
            delta_str = f"{t_delta_str}, {m_delta_str}"

        cost_str = f"${cost_usd:.2f}" if cost_usd is not None else "-"
        fil_str = f"{filament_g:.1f} g" if filament_g is not None else "-"
        time_str = format_duration(time_s) if time_s is not None else "-"

        row = {
            "name": v_name,
            "display_name": display_name,
            "print_time": time_str,
            "time_s": time_s,
            "filament": fil_str,
            "filament_g": filament_g,
            "cost": cost_str,
            "cost_usd": cost_usd,
            "vs_baseline": delta_str,
            "delta_time_s": delta_t_s,
            "delta_filament_g": delta_m_g,
            "is_baseline": is_base,
            "is_fastest": is_fastest,
            "is_lightest": is_lightest,
            "is_recommended": (v_name == recommended_name),
            "warnings_count": len(v.get("warnings") or []),
            "error": err,
            "filament_by_role": stats.get("filament_by_role") or {},
        }
        summary_rows.append(row)

    # Collect all roles present across variants for line type table
    present_roles: set[str] = set()
    for row in summary_rows:
        present_roles.update(row["filament_by_role"].keys())

    # Order roles canonically
    ordered_roles = [r for r in CANONICAL_ROLE_ORDER if r in present_roles]
    # Add any extra roles not in canonical list
    for r in sorted(present_roles):
        if r not in ordered_roles:
            ordered_roles.append(r)

    # Build line type matrix rows
    line_type_rows: List[Dict[str, Any]] = []
    for row in summary_rows:
        role_vals = {role: row["filament_by_role"].get(role, 0.0) for role in ordered_roles}
        line_type_rows.append({
            "name": row["name"],
            "display_name": row["display_name"],
            "roles": role_vals,
            "total_g": row["filament_g"] or 0.0,
        })

    # Generate Markdown Table for Summary (Image 1 style)
    sum_md_lines = [
        "### Summary\n",
        "| Variant | Print Time | Filament | Cost | vs baseline |",
        "|---|---|---|---|---|",
    ]
    for r in summary_rows:
        label = r["display_name"]
        if r["error"]:
            sum_md_lines.append(f"| {label} | - | - | - | ERROR: {r['error'][:40]} |")
        else:
            sum_md_lines.append(
                f"| {label} | {r['print_time']} | {r['filament']} | {r['cost']} | {r['vs_baseline']} |"
            )
    summary_markdown = "\n".join(sum_md_lines)

    # Generate Markdown Table for Filament by Line Type (Image 2 style)
    if ordered_roles:
        lt_md_lines = [
            "### Filament by line type (grams)\n",
            f"| Variant | {' | '.join(ordered_roles)} |",
            f"|---|{'---|' * len(ordered_roles)}",
        ]
        for r in line_type_rows:
            vals = [f"{r['roles'].get(role, 0.0):.2f}" for role in ordered_roles]
            lt_md_lines.append(f"| {r['name']} | {' | '.join(vals)} |")
        line_type_markdown = "\n".join(lt_md_lines)
    else:
        line_type_markdown = ""

    return {
        "baseline": base_name,
        "fastest": fastest_name,
        "lightest": lightest_name,
        "recommended": recommended_name,
        "recommendation_reason": rec_reason,
        "summary_rows": summary_rows,
        "line_type_matrix": {
            "columns": ordered_roles,
            "rows": line_type_rows,
        },
        "summary_markdown": summary_markdown,
        "line_type_markdown": line_type_markdown,
    }


def generate_html_report(
    manifest_data: Dict[str, Any],
    comparison: Dict[str, Any],
    output_path: Path,
) -> Path:
    """Generate a self-contained, responsive dark-themed HTML report.

    Embeds SVG charts for the Pareto Frontier and Stacked Bar breakdown,
    along with styled interactive summary and line-type tables.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    source = manifest_data.get("source", {})
    app_str = f"{source.get('app', 'OrcaSlicer')} v{source.get('app_version', '2.4.2')}"
    printer = source.get("printer_preset", "Default")
    print_preset = source.get("print_preset", "Default")
    filament = source.get("filament_preset", "Default")
    objects = ", ".join(source.get("plate_objects", [])) or "Active Plater"

    summary_rows = comparison.get("summary_rows", [])
    lt_matrix = comparison.get("line_type_matrix", {})
    columns = lt_matrix.get("columns", [])
    lt_rows = lt_matrix.get("rows", [])
    rec_name = comparison.get("recommended") or "None"
    rec_reason = comparison.get("recommendation_reason") or ""

    # Generate SVG Pareto Chart
    svg_pareto = _generate_pareto_svg(summary_rows)

    # Generate SVG Stacked Bar Chart
    svg_stacked_bars = _generate_stacked_bars_svg(lt_rows, columns)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OrcaSlicer Matrix Comparison Report</title>
<style>
  :root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-card: #243248;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --border: #334155;
    --primary: #38bdf8;
    --accent-fast: #fbbf24;
    --accent-light: #34d399;
    --accent-err: #f87171;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background-color: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.5;
    padding: 24px;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  header {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  h1 {{ font-size: 22px; margin-bottom: 4px; color: #fff; }}
  .meta {{ color: var(--text-muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 16px; margin-top: 8px; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .card-title {{ font-size: 16px; font-weight: 700; margin-bottom: 14px; color: #fff; display: flex; justify-content: space-between; align-items: center; }}
  .banner {{
    background: linear-gradient(90deg, #1e3a8a, #0369a1);
    border: 1px solid #38bdf8;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 20px;
  }}
  .banner-title {{ font-weight: bold; color: #e0f2fe; margin-bottom: 2px; }}
  .banner-desc {{ color: #bae6fd; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
  th {{ background: #0f172a; padding: 10px 12px; font-weight: 600; color: #cbd5e1; border-bottom: 2px solid var(--border); }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); }}
  tr:hover {{ background: rgba(255,255,255,0.03); }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
  }}
  .badge-fast {{ background: #78350f; color: #fef08a; border: 1px solid #ca8a04; }}
  .badge-base {{ background: #1e3a8a; color: #bfdbfe; border: 1px solid #3b82f6; }}
  .badge-light {{ background: #064e3b; color: #a7f3d0; border: 1px solid #059669; }}
  .chart-box {{ width: 100%; overflow-x: auto; background: var(--surface-card); border-radius: 8px; padding: 14px; margin-top: 10px; }}
  footer {{ text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 30px; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>OrcaSlicer Matrix Comparison Report</h1>
    <div class="meta">
      <span><strong>App:</strong> {app_str}</span>
      <span><strong>Printer:</strong> {printer}</span>
      <span><strong>Print Preset:</strong> {print_preset}</span>
      <span><strong>Filament:</strong> {filament}</span>
      <span><strong>Plater Objects:</strong> {objects}</span>
    </div>
  </header>

  <div class="banner">
    <div class="banner-title">★ Recommended Choice: {rec_name}</div>
    <div class="banner-desc">{rec_reason}</div>
  </div>

  <div class="card">
    <div class="card-title">Summary & Delta vs Baseline</div>
    <table>
      <thead>
        <tr>
          <th>Variant</th>
          <th>Print Time</th>
          <th>Filament</th>
          <th>Cost</th>
          <th>vs Baseline</th>
        </tr>
      </thead>
      <tbody>
"""

    for r in summary_rows:
        disp = r["display_name"]
        badge_html = ""
        if r["is_baseline"]:
            badge_html = ' <span class="badge badge-base">baseline</span>'
        elif r["is_fastest"]:
            badge_html = ' <span class="badge badge-fast">★ fastest</span>'
        elif r["is_lightest"]:
            badge_html = ' <span class="badge badge-light">★ lightest</span>'

        clean_name = r["name"] + badge_html
        html_content += f"""        <tr>
          <td><strong>{clean_name}</strong></td>
          <td>{r['print_time']}</td>
          <td>{r['filament']}</td>
          <td>{r['cost']}</td>
          <td><code>{r['vs_baseline']}</code></td>
        </tr>
"""

    html_content += """      </tbody>
    </table>
  </div>
"""

    # Line type table
    if columns:
        html_content += """  <div class="card">
    <div class="card-title">Filament by Line Type (grams)</div>
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Variant</th>
"""
        for col in columns:
            html_content += f"            <th>{col}</th>\n"
        html_content += """          </tr>
        </thead>
        <tbody>
"""
        for r in lt_rows:
            html_content += f"          <tr>\n            <td><strong>{r['name']}</strong></td>\n"
            for col in columns:
                val = r["roles"].get(col, 0.0)
                html_content += f"            <td>{val:.2f}g</td>\n"
            html_content += "          </tr>\n"
        html_content += """        </tbody>
      </table>
    </div>
  </div>
"""

    # Charts Section
    html_content += f"""  <div class="card">
    <div class="card-title">Pareto Frontier: Print Time vs Filament Mass</div>
    <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 10px;">
      Lower and further left is optimal. Points on the dashed line represent Pareto-efficient trade-offs.
    </p>
    <div class="chart-box">
      {svg_pareto}
    </div>
  </div>

  <div class="card">
    <div class="card-title">Filament Extrusion Breakdown by Role</div>
    <div class="chart-box">
      {svg_stacked_bars}
    </div>
  </div>

  <footer>
    Generated by OrcaSlicer Matrix Tool • Manifest: <code>manifest.json</code>
  </footer>
</div>
</body>
</html>
"""

    out_file.write_text(html_content, encoding="utf-8")
    return out_file


def _generate_pareto_svg(summary_rows: List[Dict[str, Any]]) -> str:
    """Generate inline SVG for the 2D Pareto frontier scatter plot."""
    valid_pts = [
        r for r in summary_rows
        if r.get("time_s") is not None and r.get("filament_g") is not None and not r.get("error")
    ]
    if not valid_pts:
        return "<p style='color:#94a3b8;'>Not enough data for chart.</p>"

    times = [p["time_s"] / 60.0 for p in valid_pts]  # minutes
    masses = [p["filament_g"] for p in valid_pts]

    min_t, max_t = min(times), max(times)
    min_m, max_m = min(masses), max(masses)

    t_pad = max(4, (max_t - min_t) * 0.18)
    m_pad = max(0.6, (max_m - min_m) * 0.18)

    y_min, y_max = max(0, min_t - t_pad), max_t + t_pad
    x_min, x_max = max(0, min_m - m_pad), max_m + m_pad

    width, height = 760, 320
    margin_l, margin_r, margin_t, margin_b = 65, 40, 25, 45
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    def to_x(m: float) -> float:
        return margin_l + ((m - x_min) / (x_max - x_min + 1e-6)) * plot_w

    def to_y(t: float) -> float:
        return margin_t + plot_h - ((t - y_min) / (y_max - y_min + 1e-6)) * plot_h

    # Grid lines & ticks
    x_ticks = [x_min + (x_max - x_min) * (i / 4.0) for i in range(5)]
    y_ticks = [y_min + (y_max - y_min) * (i / 4.0) for i in range(5)]

    svg = f"""<svg viewBox="0 0 {width} {height}" style="width: 100%; max-width: 800px; height: auto;">
  <!-- Grid Lines -->
"""
    for xt in x_ticks:
        gx = to_x(xt)
        svg += f"""  <line x1="{gx:.1f}" y1="{margin_t}" x2="{gx:.1f}" y2="{margin_t + plot_h}" stroke="#334155" stroke-width="1" stroke-dasharray="3,3"/>\n"""
        svg += f"""  <text x="{gx:.1f}" y="{margin_t + plot_h + 16}" fill="#94a3b8" font-size="10" text-anchor="middle">{xt:.1f}g</text>\n"""

    for yt in y_ticks:
        gy = to_y(yt)
        svg += f"""  <line x1="{margin_l}" y1="{gy:.1f}" x2="{margin_l + plot_w}" y2="{gy:.1f}" stroke="#334155" stroke-width="1" stroke-dasharray="3,3"/>\n"""
        svg += f"""  <text x="{margin_l - 8}" y="{gy + 4:.1f}" fill="#94a3b8" font-size="10" text-anchor="end">{int(round(yt))}m</text>\n"""

    svg += f"""  <!-- Axes -->
  <line x1="{margin_l}" y1="{margin_t + plot_h}" x2="{margin_l + plot_w}" y2="{margin_t + plot_h}" stroke="#64748b" stroke-width="1.5"/>
  <line x1="{margin_l}" y1="{margin_t}" x2="{margin_l}" y2="{margin_t + plot_h}" stroke="#64748b" stroke-width="1.5"/>

  <!-- Axis Labels -->
  <text x="{margin_l + plot_w / 2}" y="{height - 6}" fill="#cbd5e1" font-size="11" font-weight="600" text-anchor="middle">Filament Mass (grams)</text>
  <text transform="rotate(-90)" x="-{margin_t + plot_h / 2}" y="16" fill="#cbd5e1" font-size="11" font-weight="600" text-anchor="middle">Print Time (minutes)</text>
"""

    # Sort to draw Pareto frontier line
    pts_sorted = sorted(valid_pts, key=lambda p: (p["filament_g"], p["time_s"]))
    frontier = []
    curr_min_t = float("inf")
    for p in pts_sorted:
        t_val = p["time_s"] / 60.0
        if t_val <= curr_min_t:
            frontier.append((p["filament_g"], t_val))
            curr_min_t = t_val

    frontier_poly = " ".join(f"{to_x(m):.1f},{to_y(t):.1f}" for m, t in frontier)
    svg += f"""  <!-- Pareto Frontier Curve -->
  <polyline points="{frontier_poly}" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-dasharray="4,4" opacity="0.9"/>
"""

    for p in valid_pts:
        t_m = p["time_s"] / 60.0
        m_g = p["filament_g"]
        cx = to_x(m_g)
        cy = to_y(t_m)
        is_base = p.get("is_baseline", False)
        is_rec = p.get("is_recommended", False)
        is_fast = p.get("is_fastest", False)

        col = "#38bdf8"
        r_size = 6
        if is_base:
            col = "#60a5fa"
            r_size = 7
        if is_fast:
            col = "#fbbf24"
            r_size = 8
        if is_rec:
            col = "#34d399"
            r_size = 8

        lbl = format_compact_label(p["name"])
        if is_base:
            lbl += " (base)"
        elif is_fast:
            lbl += " ★"
        elif is_rec:
            lbl += " ★ rec"

        tooltip = f"{p['name']}&#10;Time: {p['print_time']}&#10;Filament: {p['filament']}&#10;Cost: {p['cost']}"
        svg += f"""  <g>
    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r_size}" fill="{col}" stroke="#0f172a" stroke-width="2">
      <title>{tooltip}</title>
    </circle>
    <text x="{cx + 10:.1f}" y="{cy + 4:.1f}" fill="#f8fafc" font-size="11" font-weight="600">{lbl}</text>
  </g>
"""

    svg += "</svg>"
    return svg


def _generate_stacked_bars_svg(
    lt_rows: List[Dict[str, Any]],
    columns: List[str],
) -> str:
    """Generate inline SVG for horizontal stacked bars showing role extrusion breakdown."""
    if not lt_rows or not columns:
        return "<p style='color:#94a3b8;'>No line type data available.</p>"

    # Multi-row wrapping legend
    width = 760
    margin_l = 170
    margin_r = 55
    margin_b = 25
    plot_w = width - margin_l - margin_r

    leg_items = []
    curr_leg_x = margin_l
    curr_leg_y = 12
    line_h = 18

    for col in columns:
        c = get_role_color(col)
        item_w = len(col) * 7 + 28
        if curr_leg_x + item_w > width - margin_r and curr_leg_x > margin_l:
            curr_leg_x = margin_l
            curr_leg_y += line_h
        leg_items.append((col, c, curr_leg_x, curr_leg_y))
        curr_leg_x += item_w

    margin_t = curr_leg_y + 24
    bar_h = 24
    bar_gap = 12
    height = margin_t + len(lt_rows) * (bar_h + bar_gap) + margin_b

    max_mass = max(r["total_g"] for r in lt_rows) if lt_rows else 100.0
    scale = plot_w / (max_mass + 1e-6)

    svg = f"""<svg viewBox="0 0 {width} {height}" style="width: 100%; max-width: 800px; height: auto;">
  <!-- Legend -->
  <g>
"""
    for col, c, lx, ly in leg_items:
        svg += f"""    <rect x="{lx}" y="{ly - 9}" width="10" height="10" fill="{c}" rx="2"/>
    <text x="{lx + 14}" y="{ly}" fill="#cbd5e1" font-size="10">{col}</text>
"""
    svg += "  </g>\n"

    for i, row in enumerate(lt_rows):
        y = margin_t + i * (bar_h + bar_gap)
        name = row["name"]
        compact_name = format_compact_label(name) or name
        total = row["total_g"]

        svg += f"""  <text x="{margin_l - 10}" y="{y + 16}" fill="#f8fafc" font-size="11" text-anchor="end" font-weight="600">{compact_name}</text>
"""
        curr_x = margin_l
        for col in columns:
            val = row["roles"].get(col, 0.0)
            if val <= 0.001:
                continue
            seg_w = val * scale
            c = get_role_color(col)
            pct = (val / total * 100.0) if total > 0 else 0.0
            tooltip = f"{compact_name}&#10;{col}: {val:.2f}g ({pct:.1f}%)&#10;Total: {total:.1f}g"
            svg += f"""  <rect x="{curr_x:.1f}" y="{y}" width="{seg_w:.1f}" height="{bar_h}" fill="{c}">
    <title>{tooltip}</title>
  </rect>
"""
            # Label inside segment if wide enough
            if seg_w >= 28:
                svg += f"""  <text x="{curr_x + seg_w / 2:.1f}" y="{y + 16}" fill="#ffffff" font-size="10" font-weight="600" text-anchor="middle">{val:.1f}g</text>\n"""
            curr_x += seg_w

        # Right-aligned total mass
        svg += f"""  <text x="{width - 15}" y="{y + 16}" fill="#94a3b8" font-size="11" font-weight="600" text-anchor="end">{total:.1f}g</text>\n"""

    svg += "</svg>"
    return svg

