"""Create the reusable, traceable data package and human-readable reports."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from jinja2 import Template

from .models import Candidate, Study
from .utils import utc_now, write_csv, write_json


DATA_FIELDS = [
    "candidate_id", "study_id", "variable_name", "value_raw", "value_numeric",
    "unit_raw", "value_normalized", "unit_normalized", "value_text", "source_type",
    "source_path", "page", "source_locator", "evidence_text", "extraction_method",
    "confidence", "review_status", "observation_level", "value_role", "notes",
]


def _serializable(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
        for key, value in record.items()
    }


def export_dictionary(path: Path, variables: list[dict[str, Any]]) -> None:
    rows = []
    for item in variables:
        rows.append({
            "field_name": item["name"],
            "label": item.get("label", ""),
            "scientific_meaning": item.get("meaning", ""),
            "data_type": item.get("kind", ""),
            "canonical_unit": item.get("canonical_unit") or "",
            "required": item.get("required", False),
            "allowed_sources": ";".join(item.get("allowed_sources", [])),
            "missing_value": "null/empty",
            "valid_range": json.dumps(item.get("valid_range"), ensure_ascii=False) if item.get("valid_range") else "",
            "evidence_required": item.get("evidence_required", True),
            "conflict_policy": item.get("conflict_policy", "human_review"),
            "synonyms": ";".join(str(value) for value in item.get("synonyms", [])),
        })
    write_csv(path, rows)


REPORT_TEMPLATE = Template("""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EcoData MVP 质量报告</title>
<style>
body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17201b;margin:0;background:#f5f7f5}main{max-width:1120px;margin:auto;padding:36px 28px 64px}h1,h2{letter-spacing:0}h1{font-size:30px;margin:0 0 4px}h2{font-size:19px;margin-top:32px;border-bottom:1px solid #cfd7d1;padding-bottom:7px}.muted{color:#607068}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.metric{background:white;border:1px solid #d8dfda;border-radius:6px;padding:14px}.metric strong{display:block;font-size:25px;color:#176645}table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:8px 10px;border:1px solid #dbe1dd;vertical-align:top}th{background:#e9efeb}.warn{color:#9b4a13}.error{color:#a12828}code{background:#e8ece9;padding:2px 5px;border-radius:3px}</style></head>
<body><main><h1>EcoData MVP v1 质量报告</h1><p class="muted">运行 {{ run_id }} · {{ generated_at }}</p>
<div class="metrics"><div class="metric"><strong>{{ summary.study_count }}</strong>篇论文</div><div class="metric"><strong>{{ summary.candidate_count }}</strong>条候选事实</div><div class="metric"><strong>{{ '%.1f'|format(summary.traceable_candidate_rate*100) }}%</strong>可追溯率</div><div class="metric"><strong>{{ summary.open_error_count }}</strong>个开放错误</div></div>
<h2>范围与状态</h2><p>本次输入为用户本地上传的数字版 PDF。V1 使用可审计规则抽取候选事实，所有自动结果默认待人工审核；当前准确率不能在没有人工标准答案时宣称。</p>
<table><tr><th>来源</th><th>候选数</th></tr>{% for key,value in summary.source_type.items() %}<tr><td>{{ key }}</td><td>{{ value }}</td></tr>{% endfor %}</table>
<h2>字段覆盖</h2><table><tr><th>字段</th><th>候选数</th><th>论文覆盖</th></tr>{% for item in summary.variables %}<tr><td>{{ item.name }}</td><td>{{ item.candidate_count }}</td><td>{{ item.study_coverage_count }}/{{ summary.study_count }} ({{ '%.1f'|format(item.study_coverage_rate*100) }}%)</td></tr>{% endfor %}</table>
<h2>验证问题</h2><table><tr><th>严重度</th><th>类型</th><th>论文</th><th>页码</th><th>说明</th></tr>{% for issue in issues[:300] %}<tr><td class="{{ issue.severity }}">{{ issue.severity }}</td><td>{{ issue.issue_type }}</td><td>{{ issue.study_id }}</td><td>{{ issue.page }}</td><td>{{ issue.message }}</td></tr>{% endfor %}</table>
<h2>人工审核</h2><p>在本地审核页逐条接受、修改、拒绝或标为无法确定。所有修改写入 <code>reviews.csv</code>；图数据通过本地 WebPlotDigitizer 标定后导出。</p>
<h2>已知局限</h2><ul><li>规则基线会产生误召回，尤其是数字与变量语义的对应关系。</li><li>跨页表格只标记风险，V1 不静默合并。</li><li>图件自动裁剪依赖 PDF 内嵌图像结构，失败时需人工指定。</li><li>原研究质量不压缩成单一分数；需要审核人根据方法证据判断。</li></ul>
<h2>复现</h2><p><code>ecodata-mvp run --input example</code>，配置哈希 <code>{{ config_sha }}</code>。</p>
</main></body></html>""")


def export_package(
    run_dir: Path,
    run_id: str,
    studies: list[Study],
    candidates: list[Candidate],
    tables: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    variables: list[dict[str, Any]],
    summary: dict[str, Any],
    config_sha: str,
    provenance: list[dict[str, Any]],
) -> None:
    study_rows = [_serializable(study.to_dict()) for study in studies]
    candidate_rows = [_serializable(candidate.to_dict()) for candidate in candidates]
    write_csv(run_dir / "data.csv", candidate_rows, DATA_FIELDS)
    write_csv(run_dir / "studies.csv", study_rows)
    write_csv(run_dir / "tables.csv", tables)
    write_csv(run_dir / "figure_tasks.csv", figures)
    write_csv(run_dir / "provenance.csv", provenance)
    write_csv(run_dir / "validation_issues.csv", issues)
    write_csv(run_dir / "reviews.csv", [], ["review_id", "candidate_id", "action", "old_value", "new_value", "reason", "reviewer", "reviewed_at"])
    export_dictionary(run_dir / "data_dictionary.csv", variables)
    write_json(run_dir / "quality_summary.json", summary)

    resources = []
    for name in ("data.csv", "studies.csv", "data_dictionary.csv", "provenance.csv", "validation_issues.csv", "tables.csv", "figure_tasks.csv", "reviews.csv"):
        resources.append({"name": Path(name).stem, "path": name, "format": "csv"})
    write_json(run_dir / "datapackage.json", {
        "profile": "data-package",
        "name": "stem-respiration-literature-extraction",
        "title": "Stem respiration literature extraction candidates",
        "created": utc_now(),
        "resources": resources,
        "ecodata": {"run_id": run_id, "config_sha256": config_sha, "review_required": True},
    })

    report = REPORT_TEMPLATE.render(run_id=run_id, generated_at=utc_now(), summary=summary, issues=issues, config_sha=config_sha)
    (run_dir / "quality_report.html").write_text(report, encoding="utf-8")

    description = f"""# 数据说明：Stem Respiration Literature MVP

## 本次运行

- 运行编号：`{run_id}`
- 论文数：{len(studies)}
- 候选事实：{len(candidates)}
- 配置哈希：`{config_sha}`
- 状态：自动抽取候选，未经人工接受的记录不能视为最终科学数据。

## 数据粒度

`data.csv` 每一行是一条“候选事实”，并不自动代表一棵树的一条完整观测。只有在确认物种、站点、处理、测量层级和时间关系后，才能构建宽表观测。

## 主要文件

| 文件 | 内容 |
|---|---|
| `data.csv` | 文本和表格中抽取的候选变量，含证据、页码和审核状态 |
| `studies.csv` | PDF 哈希、文献元数据、筛选状态和数据可用性线索 |
| `tables.csv` | 发现的原始表格索引；具体 CSV 位于 `tables/` |
| `figure_tasks.csv` | 图件审核与 WebPlotDigitizer 任务索引 |
| `data_dictionary.csv` | 字段语义、单位、范围、来源与冲突规则 |
| `provenance.csv` | 各处理步骤、工具版本与输入输出记录 |
| `validation_issues.csv` | 单位缺失、越界、低置信度和解析失败等问题 |
| `reviews.csv` | 人工接受、修改、拒绝和无法确定的审计日志 |
| `quality_report.html` | 可阅读的 QC 汇总与局限 |
| `datapackage.json` | 数据包资源清单（借鉴 Frictionless Data Package） |

## 使用原则

1. 先查看 `quality_report.html` 和开放错误。
2. 在审核界面逐条检查原文证据和 PDF 页码。
3. 图表数据在本地 WebPlotDigitizer 中标定坐标和单位后导出。
4. 仅使用 `review_status=accepted` 的记录形成正式数据集。
"""
    (run_dir / "DATA_DESCRIPTION.md").write_text(description, encoding="utf-8")

