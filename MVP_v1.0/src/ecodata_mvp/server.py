"""Dependency-free local API and review interface."""

from __future__ import annotations

import csv
import json
import mimetypes
import threading
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .pipeline import run_pipeline
from .review import apply_review
from .utils import read_json, slugify, utc_now, write_csv, write_json


def _read_csv(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[:limit] if limit else rows


def _latest_run(root: Path) -> Path | None:
    marker = read_json(root / "data/output/latest_run.json", {})
    path = Path(marker.get("path", "")) if marker else None
    return path if path and path.exists() else None


def _save_figure_output(run_dir: Path, payload: dict) -> dict:
    task_id = str(payload.get("task_id", ""))
    tasks = _read_csv(run_dir / "figure_tasks.csv")
    task = next((row for row in tasks if row.get("task_id") == task_id), None)
    if not task:
        raise KeyError(f"Unknown figure task: {task_id}")
    datasets = payload.get("datasets") or []
    if not datasets:
        raise ValueError("WPD has no dataset to save")
    output_dir = run_dir / "figure_data" / slugify(task_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for index, dataset in enumerate(datasets, 1):
        fields = [str(field) for field in dataset.get("fields", [])]
        rows = dataset.get("rows", [])
        if not fields or not rows:
            continue
        data_fields = [slugify(field, f"value-{position + 1}").replace("-", "_") for position, field in enumerate(fields)]
        records = []
        for values in rows:
            record = {
                "study_id": task["study_id"], "source_pdf": task["source_pdf"],
                "page": task["page"], "figure_label": task["figure_label"],
                "task_id": task_id, "dataset": dataset.get("name") or f"dataset-{index}",
                "x_label": payload.get("x_label", ""), "x_unit": payload.get("x_unit", ""),
                "y_label": payload.get("y_label", ""), "y_unit": payload.get("y_unit", ""),
            }
            record.update({field: values[position] if position < len(values) else "" for position, field in enumerate(data_fields)})
            records.append(record)
        if records:
            path = output_dir / f"{index:02d}-{slugify(str(dataset.get('name') or 'dataset'))}.csv"
            write_csv(path, records)
            saved.append(str(path.relative_to(run_dir)))
    if not saved:
        raise ValueError("WPD datasets contain no rows")

    reviews_path = run_dir / "figure_reviews.json"
    reviews = read_json(reviews_path, {})
    reviews[task_id] = {
        "task_id": task_id, "study_id": task["study_id"], "figure_label": task["figure_label"],
        "page": task["page"], "x_label": payload.get("x_label", ""), "x_unit": payload.get("x_unit", ""),
        "y_label": payload.get("y_label", ""), "y_unit": payload.get("y_unit", ""),
        "note": payload.get("note", ""), "saved_files": saved,
        "point_count": sum(len(dataset.get("rows", [])) for dataset in datasets), "reviewed_at": utc_now(),
    }
    write_json(reviews_path, reviews)
    for row in tasks:
        if row.get("task_id") == task_id:
            row["status"] = "completed"
    write_csv(run_dir / "figure_tasks.csv", tasks)
    return reviews[task_id]


def _bundle_figure_outputs(run_dir: Path) -> Path:
    source = run_dir / "figure_data"
    files = sorted(source.rglob("*.csv")) if source.exists() else []
    if not files:
        raise FileNotFoundError("No saved figure CSV files")
    bundle = run_dir / "digitized_figure_data.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(run_dir))
        reviews = run_dir / "figure_reviews.json"
        if reviews.exists():
            archive.write(reviews, reviews.name)
    return bundle


def make_handler(root: Path):
    web_root = root / "web"

    class Handler(BaseHTTPRequestHandler):
        server_version = "EcoDataMVP/0.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, payload: object, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))

        def _serve(self, path: Path) -> None:
            try:
                path = path.resolve()
                allowed = [web_root.resolve(), (root / "data/output").resolve(), (root / "example").resolve(), (root / "vendor").resolve()]
                if not any(path == base or base in path.parents for base in allowed) or not path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                run_dir = _latest_run(root)
                if not run_dir:
                    self._json({"run": None, "studies": [], "candidates": [], "issues": [], "figures": []})
                    return
                self._json({
                    "run": read_json(run_dir / "run_manifest.json", {}),
                    "summary": read_json(run_dir / "quality_summary.json", {}),
                    "studies": _read_csv(run_dir / "studies.csv"),
                    "candidates": _read_csv(run_dir / "data.csv"),
                    "issues": _read_csv(run_dir / "validation_issues.csv"),
                    "figures": _read_csv(run_dir / "figure_tasks.csv"),
                    "run_url": f"/runs/{run_dir.name}/",
                })
                return
            if parsed.path == "/":
                self._serve(web_root / "index.html")
                return
            if parsed.path.startswith("/static/"):
                self._serve(web_root / unquote(parsed.path.removeprefix("/static/")))
                return
            if parsed.path.startswith("/runs/"):
                parts = Path(unquote(parsed.path.removeprefix("/runs/")))
                self._serve(root / "data/output" / parts)
                return
            if parsed.path.startswith("/pdfs/"):
                self._serve(root / "example" / unquote(parsed.path.removeprefix("/pdfs/")))
                return
            if parsed.path.startswith("/wpd/"):
                self._serve(root / "vendor/webplotdigitizer" / unquote(parsed.path.removeprefix("/wpd/")))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path == "/api/upload":
                    filename = Path(unquote(self.headers.get("X-Filename", "upload.pdf"))).name
                    body = self._body()
                    if not filename.lower().endswith(".pdf") or not body.startswith(b"%PDF"):
                        raise ValueError("Only PDF files are accepted")
                    target = root / "example" / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                    self._json({"ok": True, "filename": filename, "size": len(body)})
                    return
                if self.path == "/api/run":
                    run_dir = run_pipeline(root)
                    self._json({"ok": True, "run_id": run_dir.name})
                    return
                if self.path == "/api/review":
                    run_dir = _latest_run(root)
                    if not run_dir:
                        raise FileNotFoundError("No completed run")
                    payload = json.loads(self._body() or b"{}")
                    self._json({"ok": True, "review": apply_review(run_dir, payload)})
                    return
                if self.path == "/api/figure-save":
                    run_dir = _latest_run(root)
                    if not run_dir:
                        raise FileNotFoundError("No completed run")
                    payload = json.loads(self._body() or b"{}")
                    self._json({"ok": True, "figure_review": _save_figure_output(run_dir, payload)})
                    return
                if self.path == "/api/figure-bundle":
                    run_dir = _latest_run(root)
                    if not run_dir:
                        raise FileNotFoundError("No completed run")
                    bundle = _bundle_figure_outputs(run_dir)
                    self._json({"ok": True, "url": f"/runs/{run_dir.name}/{bundle.name}"})
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(root.resolve()))
    url = f"http://{host}:{port}/"
    print(f"EcoData MVP review: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
