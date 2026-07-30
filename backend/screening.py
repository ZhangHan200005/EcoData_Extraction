"""Evidence-based four-state document screening."""

from __future__ import annotations

import re

from .schemas import BlockRecord, DocumentRecord, ProjectSpec


NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?")
UNIT_RE = re.compile(
    r"(?:µmol|μmol|umol|nmol|mmol|mg\s*co2|mgco2|°c|ºc|cm|mm|\bm\b|%|s[−-]?1|m[−-]?2)",
    re.I,
)
MODEL_PREDICTION_RE = re.compile(
    r"\b(?:model(?:led|ed|ing)?|simulation|simulated|prediction|predicted)\b|"
    r"(?:模型|模拟|预测)(?:值|结果|数据)?",
    re.I,
)


def _contains(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms if term)


class DocumentScreener:
    def screen(
        self,
        document: DocumentRecord,
        blocks: list[BlockRecord],
        spec: ProjectSpec,
    ) -> DocumentRecord:
        if document.parser_status == "failed":
            return document.model_copy(
                update={
                    "screening_status": "failed",
                    "screening_reasons": [
                        "全文文本不足，当前解析结果不能支持可靠判断。"
                    ],
                    "missing_required_fields": [
                        field.name for field in spec.required_context
                    ],
                }
            )

        target_terms = [
            term
            for variable in spec.target_variables
            for term in [variable.label, variable.name, *variable.synonyms]
        ]
        target_ordinals = {
            block.ordinal
            for block in blocks
            if _contains(block.text, target_terms)
        }
        evidence_window = {
            ordinal + offset
            for ordinal in target_ordinals
            for offset in (-1, 0, 1)
        }
        target_blocks = [
            block for block in blocks if block.ordinal in evidence_window
        ]
        numeric_blocks = [
            block
            for block in target_blocks
            if NUMBER_RE.search(block.text)
            and (
                UNIT_RE.search(block.text)
                or block.kind in {"table_caption", "figure_caption"}
            )
        ]
        excluded_prediction_blocks = 0
        if "model_prediction" in spec.exclusions:
            retained_blocks = [
                block
                for block in numeric_blocks
                if not MODEL_PREDICTION_RE.search(block.text)
            ]
            excluded_prediction_blocks = len(numeric_blocks) - len(
                retained_blocks
            )
            numeric_blocks = retained_blocks

        missing_required: list[str] = []
        for field in spec.required_context:
            terms = [field.label, field.name, *field.synonyms]
            if not any(_contains(block.text, terms) for block in blocks):
                missing_required.append(field.name)

        reasons = [
            f"目标术语证据块：{len(target_ordinals)}",
            f"目标附近含数字/单位的证据块：{len(numeric_blocks)}",
        ]
        if excluded_prediction_blocks:
            reasons.append(
                f"按研究需求排除模型预测证据块：{excluded_prediction_blocks}"
            )
        if numeric_blocks and not missing_required:
            status = "usable"
            reasons.append("存在明确目标数据，且必须上下文字段均有证据。")
        elif numeric_blocks:
            status = "relative"
            reasons.append(
                "存在目标数据，但缺少必须字段：" + ", ".join(missing_required)
            )
        else:
            status = "nodata"
            reasons.append("未发现满足当前规则的可提取目标数值证据。")

        return document.model_copy(
            update={
                "screening_status": status,
                "screening_reasons": reasons,
                "missing_required_fields": missing_required,
            }
        )
