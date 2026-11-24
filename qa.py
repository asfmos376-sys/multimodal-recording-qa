"""Audit multimodal recording manifests before dataset ingestion."""

import argparse
import csv
import json
from html import escape
from pathlib import Path

STREAMS = ("video", "tactile", "emg")
MARKERS = ("start", "end")


def finite(value):
    return type(value) in (int, float) and abs(value) <= 1e15


def issue(code, **details):
    return {"code": code, **details}


def inspect_stream(stream, gap_factor):
    metrics = {}
    issues = []
    if stream is None:
        return metrics, [issue("missing_stream")], None
    if not isinstance(stream, dict):
        return metrics, [issue("invalid_stream")], None
    times = stream.get("timestamps_ms")
    period = stream.get("period_ms")
    if not isinstance(times, list) or len(times) < 2 or not all(map(finite, times)):
        return metrics, [issue("invalid_timestamps")], None
    if not finite(period) or period <= 0:
        return metrics, [issue("invalid_period")], None

    metrics["samples"] = len(times)
    gaps = []
    reversed_count = 0
    largest = 0
    for before, after in zip(times, times[1:]):
        delta = after - before
        largest = max(largest, delta)
        if delta <= 0:
            reversed_count += 1
        if delta > gap_factor * period:
            gaps.append({"from_ms": before, "to_ms": after, "duration_ms": delta})
    metrics["largest_gap_ms"] = largest
    if reversed_count:
        issues.append(issue("timestamp_order", count=reversed_count))
    if gaps:
        issues.append(issue("sample_gap", count=len(gaps), largest_ms=largest,
                            locations=gaps))

    markers = stream.get("markers_ms")
    if isinstance(markers, dict):
        start, end = (markers.get(name) for name in MARKERS)
        if finite(start) and finite(end) and min(times) <= start < end <= max(times):
            return metrics, issues, (start, end)
    issues.append(issue("invalid_sync_markers"))
    return metrics, issues, None


def audit(manifest, *, gap_factor=2.5, offset_ms=50, drift_ms=20):
    if not isinstance(manifest, dict) or not isinstance(manifest.get("streams"), dict):
        raise ValueError("Expected an object containing a streams object")
    streams = manifest["streams"]
    checked = {name: inspect_stream(streams.get(name), gap_factor) for name in STREAMS}
    video_markers = checked["video"][2]
    report_streams = {}
    for name, (metrics, issues, markers) in checked.items():
        if name != "video" and markers:
            if not video_markers:
                issues.append(issue("video_reference_unavailable"))
            else:
                offset = markers[0] - video_markers[0]
                drift = (markers[1] - markers[0]) - (video_markers[1] - video_markers[0])
                metrics.update(offset_ms=round(offset, 3), drift_ms=round(drift, 3))
                if abs(offset) > offset_ms:
                    issues.append(issue("clock_offset", measured_ms=round(offset, 3)))
                if abs(drift) > drift_ms:
                    issues.append(issue("clock_drift", measured_ms=round(drift, 3)))
        report_streams[name] = {"metrics": metrics, "issues": issues}
    return {
        "status": "review" if any(row["issues"] for row in report_streams.values()) else "pass",
        "streams": report_streams,
    }


def sample(kind):
    streams = {}
    for name, period in zip(STREAMS, (1000 / 30, 10, 2)):
        skew = name == "emg" and kind in {"mixed", "drift"}
        scale, offset = (1.008, 80) if skew else (1, 0)
        times = [index * period * scale + offset for index in range(int(6000 / period) + 1)]
        streams[name] = {
            "period_ms": period,
            "timestamps_ms": times,
            "markers_ms": {"start": 500 * scale + offset, "end": 5500 * scale + offset},
        }
    if kind in {"mixed", "dropout"}:
        del streams["tactile"]["timestamps_ms"][260:281]
    if kind == "missing":
        del streams["emg"]
    if kind == "markers":
        del streams["video"]["markers_ms"]
    if kind == "order":
        times = streams["tactile"]["timestamps_ms"]
        times[260] = times[259]
    return {"streams": streams}


def write_samples(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for kind in ("clean", "mixed", "dropout", "drift", "missing", "markers", "order"):
        path = directory / f"{kind}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(sample(kind), handle)


def read_recording(path, limits):
    try:
        report = audit(json.loads(path.read_text(encoding="utf-8-sig")), **limits)
    except (OSError, ValueError) as error:
        report = {"status": "error", "error": str(error), "streams": {}}
    return {"recording": path.name, **report}


def rows(reports):
    for report in reports:
        if report["status"] == "error":
            yield (report["recording"], "error", "", "", "", "", "", report["error"])
        for name, stream in report["streams"].items():
            metrics = stream["metrics"]
            codes = ", ".join(item["code"] for item in stream["issues"])
            yield (report["recording"], report["status"], name,
                   metrics.get("samples", ""), metrics.get("largest_gap_ms", ""),
                   metrics.get("offset_ms", ""), metrics.get("drift_ms", ""), codes)


HEADERS = ("Recording", "Take status", "Stream", "Samples", "Largest gap (ms)",
           "Offset (ms)", "Drift (ms)", "Issues")


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_reports(directory, reports, limits):
    # Require a new directory so repeated runs cannot overwrite earlier reports.
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "report.json").open("w", encoding="utf-8") as handle:
        json.dump({"thresholds": limits, "recordings": reports}, handle, indent=2)
    with (directory / "report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows([csv_cell(value) for value in row] for row in rows(reports))
    headers = "".join(f"<th>{heading}</th>" for heading in HEADERS)
    body = []
    for row in rows(reports):
        cells = "".join(f"<td>{escape(str(value))}</td>" for value in row)
        body.append(f'<tr class="{row[1]}">{cells}</tr>')
    counts = " · ".join(
        f"{sum(report['status'] == status for report in reports)} {status}"
        for status in ("pass", "review", "error")
    )
    html = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Recording QA report</title>
<style>
body{{font:16px/1.5 system-ui;background:#eef3ef;color:#142921;margin:0}}
main{{max-width:1150px;margin:auto;padding:36px 20px}}
h1{{font-size:clamp(28px,5vw,48px);margin-bottom:4px}}
.scroll{{overflow:auto;background:white;border:1px solid #cad8cf;border-radius:12px}}
table{{border-collapse:collapse;width:100%;text-align:left}}
th,td{{padding:10px;border-bottom:1px solid #dce6de}}
th{{background:#18392c;color:white}}
.review td:nth-child(2),.error td:nth-child(2){{font-weight:bold;color:#963a25}}
</style>
<main><h1>Recording QA report</h1><p>{counts}</p>
<p>Gap &gt; {limits['gap_factor']}× period · Offset &gt; {limits['offset_ms']} ms · Drift &gt; {limits['drift_ms']} ms</p>
<div class="scroll"><table><thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p>See <a href="report.json">report.json</a> for timestamps around each flagged sample gap.</p>
</main></html>"""
    (directory / "report.html").write_text(html, encoding="utf-8")


def positive(value):
    number = float(value)
    if not finite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected a positive finite number")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="generate synthetic recording manifests")
    demo.add_argument("directory", type=Path)
    check = commands.add_parser("check", help="audit a JSON file or directory of JSON files")
    check.add_argument("input", type=Path)
    check.add_argument("--out", type=Path, required=True)
    check.add_argument("--gap-factor", type=positive, default=2.5)
    check.add_argument("--offset-ms", type=positive, default=50)
    check.add_argument("--drift-ms", type=positive, default=20)
    args = parser.parse_args()
    try:
        if args.command == "demo":
            write_samples(args.directory)
            print(f"Synthetic recordings written to {args.directory}")
            return 0
        paths = (sorted(path for path in args.input.glob("*.json") if path.is_file())
                 if args.input.is_dir() else [args.input])
        if not paths:
            raise ValueError("No JSON manifests found")
        limits = dict(gap_factor=args.gap_factor, offset_ms=args.offset_ms,
                      drift_ms=args.drift_ms)
        reports = [read_recording(path, limits) for path in paths]
        write_reports(args.out, reports, limits)
        for report in reports:
            print(f"{report['status']:6} {report['recording']}")
        print(f"Open {args.out / 'report.html'}")
        statuses = {report["status"] for report in reports}
        return 2 if "error" in statuses else int("review" in statuses)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
