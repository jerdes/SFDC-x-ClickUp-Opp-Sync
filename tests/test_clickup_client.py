 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/tests/test_clickup_client.py b/tests/test_clickup_client.py
new file mode 100644
index 0000000000000000000000000000000000000000..935a306a4f78fb7b6c3f5b3172feb1a438ec69e9
--- /dev/null
+++ b/tests/test_clickup_client.py
@@ -0,0 +1,141 @@
+import unittest
+from unittest.mock import Mock, patch
+
+from clickup.client import ClickUpClient
+
+
+class TestClickUpClientHydration(unittest.TestCase):
+    def test_hydrates_tasks_missing_custom_fields(self):
+        client = ClickUpClient("token", "list")
+
+        calls = []
+
+        def fake_get(path, params=None):
+            calls.append((path, params))
+            if path == "/list/list/task":
+                page = params.get("page")
+                if page == 0:
+                    return {
+                        "tasks": [
+                            {"id": "1", "name": "A"},
+                            {"id": "2", "name": "B", "custom_fields": []},
+                        ]
+                    }
+                return {"tasks": []}
+            if path == "/task/1":
+                return {"id": "1", "name": "A", "custom_fields": [{"id": "sf", "value": "OPP-1"}]}
+            raise AssertionError(f"Unexpected path: {path}")
+
+        client._get = fake_get  # type: ignore[assignment]
+
+        tasks = client.get_all_tasks()
+
+        self.assertEqual(len(tasks), 2)
+        self.assertEqual(tasks[0]["custom_fields"][0]["value"], "OPP-1")
+        self.assertEqual(tasks[1]["custom_fields"], [])
+
+    def test_does_not_hydrate_when_custom_fields_already_present(self):
+        client = ClickUpClient("token", "list")
+
+        calls = []
+
+        def fake_get(path, params=None):
+            calls.append(path)
+            if path == "/list/list/task":
+                if params.get("page") == 0:
+                    return {"tasks": [{"id": "1", "custom_fields": []}]}
+                return {"tasks": []}
+            raise AssertionError(f"Unexpected path: {path}")
+
+        client._get = fake_get  # type: ignore[assignment]
+
+        tasks = client.get_all_tasks()
+
+        self.assertEqual(len(tasks), 1)
+        self.assertEqual(calls.count("/task/1"), 0)
+
+    def test_hydrates_when_sf_field_missing_in_list_payload(self):
+        client = ClickUpClient("token", "list")
+
+        calls = []
+
+        def fake_get(path, params=None):
+            calls.append(path)
+            if path == "/list/list/task":
+                if params.get("page") == 0:
+                    return {
+                        "tasks": [
+                            {
+                                "id": "1",
+                                "name": "A",
+                                "custom_fields": [{"id": "other", "value": "x"}],
+                            }
+                        ]
+                    }
+                return {"tasks": []}
+            if path == "/task/1":
+                return {
+                    "id": "1",
+                    "name": "A",
+                    "custom_fields": [{"id": "sf", "value": "OPP-1"}],
+                }
+            raise AssertionError(f"Unexpected path: {path}")
+
+        client._get = fake_get  # type: ignore[assignment]
+
+        tasks = client.get_all_tasks(sf_id_field_id="sf")
+
+        self.assertEqual(len(tasks), 1)
+        self.assertEqual(tasks[0]["custom_fields"][0]["id"], "sf")
+        self.assertEqual(calls.count("/task/1"), 1)
+
+
+class TestClickUpClientBaseUrl(unittest.TestCase):
+    def test_request_uses_default_production_base_url(self):
+        client = ClickUpClient("token", "list")
+
+        response = Mock()
+        response.status_code = 200
+        response.ok = True
+        response.json.return_value = {"ok": True}
+
+        with patch.dict("os.environ", {}, clear=False):
+            client._session.request = Mock(return_value=response)
+            client._request("GET", "/test")
+
+        called_url = client._session.request.call_args[0][1]
+        self.assertEqual(called_url, "https://api.clickup.com/api/v2/test")
+
+    def test_request_allows_base_url_override(self):
+        client = ClickUpClient("token", "list")
+
+        response = Mock()
+        response.status_code = 200
+        response.ok = True
+        response.json.return_value = {"ok": True}
+
+        with patch.dict("os.environ", {"CLICKUP_BASE_URL": "https://example.com/api/v2/"}, clear=False):
+            client._session.request = Mock(return_value=response)
+            client._request("GET", "/test")
+
+        called_url = client._session.request.call_args[0][1]
+        self.assertEqual(called_url, "https://example.com/api/v2/test")
+
+    def test_request_accepts_host_only_base_url_override(self):
+        client = ClickUpClient("token", "list")
+
+        response = Mock()
+        response.status_code = 200
+        response.ok = True
+        response.json.return_value = {"ok": True}
+
+        with patch.dict("os.environ", {"CLICKUP_BASE_URL": "https://api.clickup-stg.com"}, clear=False):
+            client._session.request = Mock(return_value=response)
+            client._request("GET", "/test")
+
+        called_url = client._session.request.call_args[0][1]
+        self.assertEqual(called_url, "https://api.clickup-stg.com/api/v2/test")
+
+
+if __name__ == "__main__":
+    unittest.main()
 
EOF
)
