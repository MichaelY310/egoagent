import unittest

from garden import should_water, water_millilitres, watering_decision


class GardenTests(unittest.TestCase):
    def test_dry_soil_needs_water(self):
        self.assertTrue(should_water(20))

    def test_wet_soil_does_not_need_water(self):
        self.assertFalse(should_water(70))

    def test_volume_is_flow_times_duration(self):
        self.assertEqual(water_millilitres(12, 5), 60)

    def test_decision_keeps_pump_off_for_wet_soil(self):
        self.assertEqual(watering_decision(80, 12, 5), {"water": False, "millilitres": 0.0})


if __name__ == "__main__":
    unittest.main()
