"""Conservative unit normalization with explicit conversion notes."""

from __future__ import annotations

import re


def clean_unit(unit: str) -> str:
    value = unit.strip().replace("μ", "µ").replace("º", "°")
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_numeric(variable: str, value: float, unit: str) -> tuple[float, str, str]:
    raw = clean_unit(unit)
    compact = raw.lower().replace(" ", "")

    if variable == "measurement_temperature":
        if compact in {"k", "kelvin"}:
            return round(value - 273.15, 6), "°C", "kelvin_to_celsius"
        if compact in {"°f", "f"}:
            return round((value - 32) * 5 / 9, 6), "°C", "fahrenheit_to_celsius"
        return value, "°C" if raw else "", "identity_or_unit_missing"

    if variable in {"tree_height", "measurement_height"}:
        if compact == "cm":
            return round(value / 100, 8), "m", "centimeter_to_meter"
        if compact == "mm":
            return round(value / 1000, 8), "m", "millimeter_to_meter"
        return value, "m" if compact == "m" else raw, "identity_or_unconverted"

    if variable == "diameter_at_breast_height":
        if compact == "mm":
            return round(value / 10, 8), "cm", "millimeter_to_centimeter"
        if compact == "m":
            return round(value * 100, 8), "cm", "meter_to_centimeter"
        return value, "cm" if compact == "cm" else raw, "identity_or_unconverted"

    if variable == "tree_age":
        return value, "year", "identity"

    # Respiration units encode both amount and denominator. Converting merely from
    # a nearby µmol/nmol token would be scientifically unsafe, so V1 preserves it.
    if variable == "stem_respiration_rate":
        return value, raw, "preserved_compound_unit_requires_review"

    return value, raw, "identity"

