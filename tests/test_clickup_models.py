import unittest

from clickup.models import build_custom_fields_payload, build_dropdown_option_maps
from sync.parser import Opportunity


class TestClickUpDropdownMapping(unittest.TestCase):
    def test_stage_dropdown_uses_option_id_when_mapping_exists(self):
        opp = Opportunity(sf_opportunity_id="006X", name="Deal", stage="Prospecting")
        field_ids = {"stage": "stage-field-id"}
        list_fields = [
            {
                "id": "stage-field-id",
                "type": "drop_down",
                "type_config": {
                    "options": [
                        {"id": "opt-1", "name": "Prospecting"},
                        {"id": "opt-2", "name": "Closed Won"},
                    ]
                },
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [{"id": "stage-field-id", "value": "opt-1"}])

    def test_stage_dropdown_skips_unmapped_value_when_dropdown_metadata_present(self):
        opp = Opportunity(sf_opportunity_id="006X", name="Deal", stage="Unknown Stage")
        field_ids = {"stage": "stage-field-id"}
        list_fields = [
            {
                "id": "stage-field-id",
                "type": "drop_down",
                "type_config": {"options": [{"id": "opt-1", "name": "Prospecting"}]},
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [])

    def test_stage_falls_back_to_raw_value_without_dropdown_metadata(self):
        opp = Opportunity(sf_opportunity_id="006X", name="Deal", stage="Prospecting")
        field_ids = {"stage": "stage-field-id"}

        payload = build_custom_fields_payload(opp, field_ids)

        self.assertEqual(payload, [{"id": "stage-field-id", "value": "Prospecting"}])

    def test_stage_dropdown_matches_normalized_labels(self):
        opp = Opportunity(sf_opportunity_id="006X", name="Deal", stage="Closed - Won")
        field_ids = {"stage": "stage-field-id"}
        list_fields = [
            {
                "id": "stage-field-id",
                "type": "drop_down",
                "type_config": {
                    "options": [
                        {"id": "opt-1", "name": "Closed Won"},
                    ]
                },
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [{"id": "stage-field-id", "value": "opt-1"}])

    def test_stage_dropdown_matches_by_stage_index_when_text_differs(self):
        opp = Opportunity(
            sf_opportunity_id="006X",
            name="Deal",
            stage="4 - Paper Process",
        )
        field_ids = {"stage": "stage-field-id"}
        list_fields = [
            {
                "id": "stage-field-id",
                "type": "drop_down",
                "type_config": {
                    "options": [
                        {"id": "opt-45", "name": "4 & 5 - Paper Process & Closing"},
                        {"id": "opt-6", "name": "6 - Closed Won"},
                    ]
                },
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [{"id": "stage-field-id", "value": "opt-45"}])

    def test_stage_dropdown_uses_index_when_csv_label_has_mismatched_text(self):
        opp = Opportunity(
            sf_opportunity_id="006X",
            name="Deal",
            stage="7 - Closed Won",
        )
        field_ids = {"stage": "stage-field-id"}
        list_fields = [
            {
                "id": "stage-field-id",
                "type": "drop_down",
                "type_config": {
                    "options": [
                        {"id": "opt-7", "name": "7 - Closed Lost"},
                    ]
                },
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [{"id": "stage-field-id", "value": "opt-7"}])

    def test_forecast_category_alias_pipeline_maps_to_best_case(self):
        opp = Opportunity(sf_opportunity_id="006X", name="Deal", forecast_category="Pipeline")
        field_ids = {"forecast_category": "forecast-field-id"}
        list_fields = [
            {
                "id": "forecast-field-id",
                "type": "drop_down",
                "type_config": {
                    "options": [
                        {"id": "opt-best", "name": "Best Case"},
                        {"id": "opt-likely", "name": "Likely"},
                        {"id": "opt-commit", "name": "Commit"},
                    ]
                },
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [{"id": "forecast-field-id", "value": "opt-best"}])

    def test_forecast_category_alias_closed_won_maps_to_commit(self):
        opp = Opportunity(sf_opportunity_id="006X", name="Deal", forecast_category="Closed Won")
        field_ids = {"forecast_category": "forecast-field-id"}
        list_fields = [
            {
                "id": "forecast-field-id",
                "type": "drop_down",
                "type_config": {
                    "options": [
                        {"id": "opt-commit", "name": "Commit"},
                    ]
                },
            }
        ]

        option_maps = build_dropdown_option_maps(list_fields, field_ids)
        payload = build_custom_fields_payload(opp, field_ids, option_maps)

        self.assertEqual(payload, [{"id": "forecast-field-id", "value": "opt-commit"}])


if __name__ == "__main__":
    unittest.main()
