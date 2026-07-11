import unittest

from ecodata_mvp.normalization import normalize_numeric


class NormalizationTests(unittest.TestCase):
    def test_temperature_conversions(self):
        self.assertEqual(normalize_numeric("measurement_temperature", 273.15, "K")[:2], (0.0, "°C"))
        self.assertEqual(normalize_numeric("measurement_temperature", 32, "°F")[:2], (0.0, "°C"))

    def test_length_conversions(self):
        self.assertEqual(normalize_numeric("measurement_height", 130, "cm")[:2], (1.3, "m"))
        self.assertEqual(normalize_numeric("diameter_at_breast_height", 250, "mm")[:2], (25.0, "cm"))

    def test_compound_respiration_unit_is_preserved(self):
        value, unit, note = normalize_numeric("stem_respiration_rate", 1.2, "µmol CO2 m⁻² s⁻¹")
        self.assertEqual((value, unit), (1.2, "µmol CO2 m⁻² s⁻¹"))
        self.assertIn("requires_review", note)


if __name__ == "__main__":
    unittest.main()

