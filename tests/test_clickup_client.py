import unittest

from clickup.client import ClickUpClient


class TestClickUpClientHydration(unittest.TestCase):
    def test_hydrates_tasks_missing_custom_fields(self):
        client = ClickUpClient("token", "list")

        calls = []

        def fake_get(path, params=None):
            calls.append((path, params))
            if path == "/list/list/task":
                page = params.get("page")
                if page == 0:
                    return {
                        "tasks": [
                            {"id": "1", "name": "A"},
                            {"id": "2", "name": "B", "custom_fields": []},
                        ]
                    }
                return {"tasks": []}
            if path == "/task/1":
                return {"id": "1", "name": "A", "custom_fields": [{"id": "sf", "value": "OPP-1"}]}
            raise AssertionError(f"Unexpected path: {path}")

        client._get = fake_get  # type: ignore[assignment]

        tasks = client.get_all_tasks()

        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["custom_fields"][0]["value"], "OPP-1")
        self.assertEqual(tasks[1]["custom_fields"], [])

    def test_does_not_hydrate_when_custom_fields_already_present(self):
        client = ClickUpClient("token", "list")

        calls = []

        def fake_get(path, params=None):
            calls.append(path)
            if path == "/list/list/task":
                if params.get("page") == 0:
                    return {"tasks": [{"id": "1", "custom_fields": []}]}
                return {"tasks": []}
            raise AssertionError(f"Unexpected path: {path}")

        client._get = fake_get  # type: ignore[assignment]

        tasks = client.get_all_tasks()

        self.assertEqual(len(tasks), 1)
        self.assertEqual(calls.count("/task/1"), 0)

    def test_hydrates_when_sf_field_missing_in_list_payload(self):
        client = ClickUpClient("token", "list")

        calls = []

        def fake_get(path, params=None):
            calls.append(path)
            if path == "/list/list/task":
                if params.get("page") == 0:
                    return {
                        "tasks": [
                            {
                                "id": "1",
                                "name": "A",
                                "custom_fields": [{"id": "other", "value": "x"}],
                            }
                        ]
                    }
                return {"tasks": []}
            if path == "/task/1":
                return {
                    "id": "1",
                    "name": "A",
                    "custom_fields": [{"id": "sf", "value": "OPP-1"}],
                }
            raise AssertionError(f"Unexpected path: {path}")

        client._get = fake_get  # type: ignore[assignment]

        tasks = client.get_all_tasks(sf_id_field_id="sf")

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["custom_fields"][0]["id"], "sf")
        self.assertEqual(calls.count("/task/1"), 1)


if __name__ == "__main__":
    unittest.main()
