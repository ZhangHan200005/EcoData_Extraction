"""Convert a free-form research brief into a reviewable ProjectSpec."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import ContextFieldSpec, ProjectSpec, VariableSpec


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    label: str
    synonyms: tuple[str, ...]
    canonical_unit: str = ""


TARGET_FIELDS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        "stem_respiration_rate",
        "树干呼吸速率",
        (
            "树干呼吸",
            "树干co2通量",
            "树干co₂通量",
            "stem respiration",
            "stem co2 efflux",
            "stem co₂ efflux",
            "woody tissue respiration",
            "bole respiration",
        ),
        "µmol CO₂ m⁻² s⁻¹",
    ),
    FieldDefinition(
        "measurement_temperature",
        "测量温度",
        (
            "测量温度",
            "树干温度",
            "气温",
            "measurement temperature",
            "stem temperature",
            "air temperature",
        ),
        "°C",
    ),
    FieldDefinition(
        "diameter_at_breast_height",
        "胸径",
        (
            "胸径",
            "径级",
            "dbh",
            "diameter at breast height",
            "stem diameter",
        ),
        "cm",
    ),
)


CONTEXT_FIELDS: tuple[FieldDefinition, ...] = (
    FieldDefinition("species", "物种", ("物种", "树种", "species", "taxon")),
    FieldDefinition(
        "sample_size",
        "样本量",
        ("样本量", "样本数", "sample size", "replicates", "number of trees", "n="),
    ),
    FieldDefinition(
        "site_name",
        "站点",
        ("站点", "样地", "研究区", "site", "plot", "study area"),
    ),
    FieldDefinition(
        "latitude",
        "纬度",
        ("纬度", "经纬度", "latitude", "°n", "°s"),
    ),
    FieldDefinition(
        "longitude",
        "经度",
        ("经度", "经纬度", "longitude", "°e", "°w"),
    ),
    FieldDefinition(
        "measurement_method",
        "测量方法",
        (
            "测量方法",
            "呼吸室",
            "红外气体分析仪",
            "measurement method",
            "chamber",
            "infrared gas analyzer",
            "irga",
        ),
    ),
    FieldDefinition(
        "treatment",
        "处理方法",
        ("处理方法", "处理组", "treatment", "girdling", "fertilization"),
    ),
    FieldDefinition(
        "observation_time",
        "观测时间",
        ("观测时间", "测量时间", "measurement date", "sampling period", "season"),
    ),
)


REQUIRED_MARKERS = (
    "必须",
    "一定要",
    "至少要有",
    "必需",
    "required",
    "must have",
    "at least",
)
OPTIONAL_MARKERS = (
    "希望",
    "关注",
    "优先",
    "最好",
    "可选",
    "optional",
    "prefer",
)


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _sentences(text: str) -> list[str]:
    return [
        value.strip()
        for value in re.split(r"(?<=[。！？!?；;])|\n+", text)
        if value.strip()
    ]


def _field_to_variable(field: FieldDefinition) -> VariableSpec:
    return VariableSpec(
        name=field.name,
        label=field.label,
        synonyms=list(field.synonyms),
        canonical_unit=field.canonical_unit,
    )


def _field_to_context(field: FieldDefinition) -> ContextFieldSpec:
    return ContextFieldSpec(
        name=field.name,
        label=field.label,
        synonyms=list(field.synonyms),
    )


class RequirementInterpreter:
    """Transparent baseline that can later be replaced by an LLM adapter."""

    def interpret(self, brief: str) -> ProjectSpec:
        normalized = re.sub(r"\s+", " ", brief).strip()
        target_variables = [
            _field_to_variable(field)
            for field in TARGET_FIELDS
            if _contains(normalized, field.synonyms)
        ]
        warnings: list[str] = []
        if not target_variables:
            target_variables = [
                VariableSpec(
                    name="custom_target",
                    label="用户自定义目标变量",
                    synonyms=self._custom_target_terms(normalized),
                )
            ]
            warnings.append("未匹配内置领域变量，请确认自定义目标变量和同义词。")

        required: list[ContextFieldSpec] = []
        optional: list[ContextFieldSpec] = []
        for field in CONTEXT_FIELDS:
            matching_sentences = [
                sentence
                for sentence in _sentences(normalized)
                if _contains(sentence, field.synonyms)
            ]
            if not matching_sentences:
                continue
            if any(
                _contains(sentence, REQUIRED_MARKERS)
                for sentence in matching_sentences
            ):
                required.append(_field_to_context(field))
            else:
                optional.append(_field_to_context(field))

        accepted_sources: list[str] = []
        source_terms = {
            "text": ("正文", "文本", "text"),
            "table": ("表格", "表中", "table"),
            "figure": ("图中", "图件", "数据图", "figure", "chart", "plot"),
        }
        for source, terms in source_terms.items():
            if _contains(normalized, terms):
                accepted_sources.append(source)
        if not accepted_sources:
            accepted_sources = ["text", "table", "figure"]

        exclusions: list[str] = []
        exclusion_terms = {
            "model_prediction": ("不接受模型", "排除模型", "模型预测值不要", "no model"),
            "review_article": ("不接受综述", "排除综述", "no review article"),
            "citation_only": ("不接受引用数据", "排除引用", "original data only"),
        }
        for exclusion, terms in exclusion_terms.items():
            if _contains(normalized, terms):
                exclusions.append(exclusion)

        if not required:
            warnings.append("未识别到必须字段；系统暂时只按目标变量判断可用性。")

        return ProjectSpec(
            brief=normalized,
            target_variables=target_variables,
            required_context=required,
            optional_context=optional,
            accepted_sources=accepted_sources,
            exclusions=exclusions,
            interpretation_warnings=warnings,
        )

    @staticmethod
    def _custom_target_terms(brief: str) -> list[str]:
        match = re.search(
            r"(?:提取|需要|关注|研究)\s*([^，。；;]{2,40}?)(?:数据|变量|，|。|；|;)",
            brief,
            re.I,
        )
        value = match.group(1).strip() if match else brief[:30].strip()
        return [value] if value else ["目标变量"]
