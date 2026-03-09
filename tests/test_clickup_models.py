import unittest

from clickup.models import build_custom_fields_payload, build_dropdown_option_maps
from sync.parser import Opportunity


class TestClickUpDropdownMapping(unittest.TestCase):
    def test_build_dropdown_option_maps_extracts_stage_and_forecast(self):
        list_fields = [
            {
                "id": "stage-field",
                "type": "drop_down",
                "type_config": {"options": [{"id": "opt-1", "name": "Closed Won"}]},
            },
            {
                "id": "forecast-field",
                "type": "drop_down",
                "type_config": {"options": [{"id": "opt-2", "name": "Commit"}]},
            },
            {"id": "other", "type": "short_text", "type_config": {}},
        ]
        field_ids = {
            "stage": "stage-field",
            "forecast_category": "forecast-field",
            "account_name": "other",
        }

        maps = build_dropdown_option_maps(list_fields, field_ids)

        self.assertEqual(maps["stage"]["closed won"], "opt-1")
        self.assertEqual(maps["forecast_category"]["commit"], "opt-2")

    def test_build_custom_fields_payload_uses_dropdown_option_ids(self):
        opp = Opportunity(
            sf_opportunity_id="0061",
            name="Deal",
            stage="Closed Won",
            forecast_category="Commit",
        )
        field_ids = {
            "sf_opportunity_id": "sf-field",
            "stage": "stage-field",
            "forecast_category": "forecast-field",
        }
        dropdown_maps = {
            "stage": {"closed won": "opt-1"},
            "forecast_category": {"commit": "opt-2"},
        }

        payload = build_custom_fields_payload(opp, field_ids, dropdown_maps)
        by_id = {item["id"]: item["value"] for item in payload}

        self.assertEqual(by_id["stage-field"], "opt-1")
        self.assertEqual(by_id["forecast-field"], "opt-2")


if __name__ == "__main__":
    unittest.main()
