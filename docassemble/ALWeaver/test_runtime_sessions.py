import json
import unittest

from .docassemble_compat import TargetSession
from .runtime_sessions import (
    create_runtime_record,
    delete_runtime_record,
    load_runtime_record,
    playground_yaml_filename,
    store_runtime_record,
)


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.expiry = ex

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


class TestRuntimeSessions(unittest.TestCase):
    def test_playground_reference_matches_docassemble_package_convention(self):
        self.assertEqual(
            playground_yaml_filename(12, "default", "main.yml"),
            "docassemble.playground12:main.yml",
        )
        self.assertEqual(
            playground_yaml_filename(12, "Housing", "main.yml"),
            "docassemble.playground12Housing:main.yml",
        )

    def test_records_are_owner_scoped_and_hide_docassemble_session_id(self):
        redis = FakeRedis()
        target = TargetSession("docassemble.playground12:main.yml", "raw-da-id")
        record = create_runtime_record(
            weaver_session_id="weaver-id",
            owner_user_id=12,
            project="default",
            filename="main.yml",
            yaml_filename=target.yaml_filename,
            target=target,
        )
        store_runtime_record(redis, record)

        self.assertIsNone(load_runtime_record(redis, "weaver-id", 99))
        owned = load_runtime_record(redis, "weaver-id", 12)
        self.assertEqual(owned.target().session_id, "raw-da-id")
        public = owned.public_dict("/interview?opaque")
        self.assertNotIn("docassemble_session_id", public)
        self.assertNotIn("encrypted_secret", public)
        self.assertNotIn("raw-da-id", json.dumps(public))
        self.assertTrue(delete_runtime_record(redis, "weaver-id", 12))
        self.assertIsNone(load_runtime_record(redis, "weaver-id", 12))


if __name__ == "__main__":
    unittest.main()
