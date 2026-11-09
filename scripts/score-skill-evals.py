#!/usr/bin/env python3
"""Score the diagrams produced by a `claude plugin eval` run of evals/.

`claude plugin eval` runs each case in a throwaway sandbox and grades it with
its own graders, none of which can run the repository verifiers. Run the suite
with `--keep-temp --json <file>`, then pass that file here. For every run this
script finds the files the agent wrote, then records:

* self_check.py failures, verify-geometry.py findings and lint-render.py
  findings for each HTML file;
* the node count (stroked boxes at least 60x40 that hold no other box;
  diamonds and circles are not counted) against the case budget in
  evals/<case>/expect.json;
* from the trace: whether the skill was loaded, whether the agent tried to render a
  PNG and whether a PNG file exists afterwards, opened an image with Read, and ran self_check.py itself.

Visual quality is left to people: every HTML output is rasterised into a
contact sheet. Outputs, scores.json, scores.md and contact-sheet.html go to
<results>/scores/ unless --out is given.

    claude plugin eval . --ablation none --keep-temp --trust-plugin \\
        --allow-tools Bash Write Edit --no-publish --json evals/results/run.json
    python3 scripts/score-skill-evals.py evals/results/run.json
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = ROOT / "skills/diagram-design/scripts"
SUMMARY_RE = re.compile(r"Summary: .*?(\d+) finding\(s\)")
IMAGE_RE = re.compile(r"\.(png|jpe?g|webp|gif)$", re.IGNORECASE)
RENDER_RE = re.compile(r"export_png|screenshot|\.png\b", re.IGNORECASE)


def load_geometry():
    spec = importlib.util.spec_from_file_location("verify_geometry", ROOT / "scripts/verify-geometry.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


GEOMETRY = load_geometry()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def summary_count(output: str) -> int | None:
    match = SUMMARY_RE.search(output)
    return int(match.group(1)) if match else None


def node_count(source: str) -> int:
    # A stroked rect that contains another stroked rect is a zone, not a node.
    rects = GEOMETRY.stroked_nodes(source)
    return sum(
        1 for r in rects if not any(o is not r and GEOMETRY.contained(o, r) for o in rects)
    )


def score_html(path: Path, max_nodes: int | None, lint_render: bool) -> dict:
    check = run([sys.executable, str(SKILL_SCRIPTS / "self_check.py"), str(path)])
    geometry = run([sys.executable, str(ROOT / "scripts/verify-geometry.py"), str(path)])
    result = {
        "file": path.name,
        "self_check_failures": sum(1 for l in check.stdout.splitlines() if l.startswith("  - ")),
        "geometry_findings": summary_count(geometry.stdout),
        "render_findings": None,
        "nodes": node_count(path.read_text(encoding="utf-8", errors="replace")),
        "max_nodes": max_nodes,
    }
    if lint_render:
        render = run([sys.executable, str(ROOT / "scripts/lint-render.py"), str(path)])
        result["render_findings"] = summary_count(render.stdout)
    result["over_budget"] = max_nodes is not None and result["nodes"] > max_nodes
    return result


def tool_uses(trace: Path):
    for line in trace.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message")
        if event.get("type") != "assistant" or not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if block.get("type") == "tool_use":
                yield block.get("name"), block.get("input") or {}


def behaviour(trace: Path) -> dict:
    # Whether a render *succeeded* is read from the files it left, not from
    # tool output: a trailing `; echo` or `| tail` hides a failed exit code.
    sealed = trace.parent.parent / "sealed"
    seen = {
        "skill_loaded": False,
        "tried_render": False,
        "rendered_png": any(
            any((sealed / part).glob("**/*.png")) for part in ("home/cwd", "tmp")
        ),
        "opened_image": False,
        "ran_self_check": False,
        "html_edits_after_image": 0,
    }
    for name, args in tool_uses(trace):
        if name == "Skill" and "diagram-design" in json.dumps(args):
            seen["skill_loaded"] = True
        elif name == "Bash":
            command = str(args.get("command", ""))
            seen["tried_render"] |= bool(RENDER_RE.search(command))
            seen["ran_self_check"] |= "self_check.py" in command
        elif name == "Read" and IMAGE_RE.search(str(args.get("file_path", ""))):
            seen["opened_image"] = True
        elif name in {"Write", "Edit"} and seen["opened_image"] and str(args.get("file_path", "")).endswith(".html"):
            seen["html_edits_after_image"] += 1
    return seen


def workspace(trace: Path) -> Path:
    # --keep-temp leaves <kept>/out/trace.jsonl and seals the agent's files in
    # <kept>/sealed (mode 000) until the owner opens it.
    kept = trace.parent.parent
    sealed = kept / "sealed"
    for directory in (kept, sealed):
        if directory.exists() and not os.access(directory, os.R_OK | os.X_OK):
            os.chmod(directory, 0o700)
    return sealed / "home" / "cwd"


def rasterise(src: Path, out: Path) -> bool:
    proc = run([sys.executable, str(SKILL_SCRIPTS / "export_png.py"), str(src), str(out), "1"])
    return proc.returncode == 0 and out.exists()


def score(result_file: Path, out: Path, lint_render: bool) -> list[dict]:
    data = json.loads(result_file.read_text(encoding="utf-8"))
    rows = []
    for case in data["cases"]:
        expect_file = ROOT / case["dir"] / "expect.json"
        expect = json.loads(expect_file.read_text(encoding="utf-8")) if expect_file.exists() else {}
        for arm, runs in case.get("arms", {}).items():
            for index, run_result in enumerate(runs, 1):
                row = {
                    "case": case["name"],
                    "arm": arm,
                    "run": index,
                    "trap": expect.get("trap"),
                    "cost_usd": run_result.get("costUsd"),
                    "turns": run_result.get("turns"),
                    "error": run_result.get("error"),
                    "outputs": [],
                }
                trace_path = run_result.get("tracePath")
                trace = Path(trace_path) if trace_path else None
                if trace is None or not trace.exists():
                    row["error"] = row["error"] or "no trace; was the suite run with --keep-temp?"
                    rows.append(row)
                    continue
                cwd = workspace(trace)
                row.update(behaviour(trace))
                dest = out / "artifacts" / f"{case['name']}-{arm}-{index}"
                for html_file in sorted(cwd.glob("**/*.html")) if cwd.exists() else []:
                    if ".claude" in html_file.relative_to(cwd).parts:
                        continue
                    dest.mkdir(parents=True, exist_ok=True)
                    copy = dest / html_file.name
                    shutil.copyfile(html_file, copy)
                    scored = score_html(copy, expect.get("max_nodes"), lint_render)
                    png = copy.with_suffix(".png")
                    scored["png"] = str(png.relative_to(out)) if rasterise(copy, png) else None
                    row["outputs"].append(scored)
                rows.append(row)
    return rows


def flag(value) -> str:
    return "-" if value is None else ("yes" if value is True else "no" if value is False else str(value))


def write_reports(rows: list[dict], out: Path) -> None:
    (out / "scores.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    header = [
        "case", "arm", "run", "html", "self_check", "geometry", "render", "nodes/budget",
        "skill", "tried render", "rendered png", "opened image", "html edits after image", "ran self_check", "cost $",
    ]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    totals = {"self_check": 0, "geometry": 0, "render": 0, "over_budget": 0, "cost": 0.0}
    for row in rows:
        outputs = row["outputs"]
        sums = {
            key: sum(o[field] or 0 for o in outputs)
            for key, field in (("self_check", "self_check_failures"), ("geometry", "geometry_findings"), ("render", "render_findings"))
        }
        for key, value in sums.items():
            totals[key] += value
        totals["over_budget"] += sum(1 for o in outputs if o["over_budget"])
        totals["cost"] += row["cost_usd"] or 0
        nodes = ", ".join(f"{o['nodes']}/{flag(o['max_nodes'])}" for o in outputs) or "-"
        cells = [
            row["case"], row["arm"], str(row["run"]), str(len(outputs)),
            str(sums["self_check"]), str(sums["geometry"]), str(sums["render"]), nodes,
            flag(row.get("skill_loaded")), flag(row.get("tried_render")), flag(row.get("rendered_png")),
            flag(row.get("opened_image")), flag(row.get("html_edits_after_image")),
            flag(row.get("ran_self_check")),
            f"{row['cost_usd']:.2f}" if row["cost_usd"] is not None else "-",
        ]
        lines.append("| " + " | ".join(cells) + " |")
        if row["error"]:
            lines.append(f"| ^ error: {row['error']} |" + " |" * (len(header) - 1))
    lines.append(
        f"\nTotals: {totals['self_check']} self_check failures, {totals['geometry']} geometry findings, "
        f"{totals['render']} render findings, {totals['over_budget']} outputs over the node budget, "
        f"${totals['cost']:.2f} agent cost."
    )
    (out / "scores.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cells = []
    for row in rows:
        for o in row["outputs"]:
            caption = html.escape(f"{row['case']} / {row['arm']} {row['run']} / {o['file']}")
            image = f'<img src="{html.escape(o["png"])}" alt="{caption}">' if o["png"] else "<p>not rasterised</p>"
            cells.append(f"<figure>{image}<figcaption>{caption}</figcaption></figure>")
    (out / "contact-sheet.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Skill eval contact sheet</title>"
        "<style>body{font:14px system-ui;margin:24px;display:grid;"
        "grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:24px}"
        "img{width:100%;border:1px solid #ddd}figure{margin:0}</style>\n"
        + "\n".join(cells) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result", type=Path, help="JSON written by claude plugin eval --json")
    parser.add_argument("--out", type=Path, help="output directory (default: <result dir>/scores)")
    parser.add_argument("--no-render", action="store_true", help="skip lint-render.py (needs Playwright)")
    args = parser.parse_args()

    out = args.out or args.result.parent / "scores"
    out.mkdir(parents=True, exist_ok=True)
    rows = score(args.result, out, lint_render=not args.no_render)
    write_reports(rows, out)
    print((out / "scores.md").read_text(encoding="utf-8"))
    print(f"Wrote {out / 'scores.json'} and {out / 'contact-sheet.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
