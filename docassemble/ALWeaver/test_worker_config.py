import unittest

from .worker_config import (
    CELERY_CONFIGURATION_DOCS_URL,
    CELERY_MODULE,
    get_worker_configuration_status,
    worker_configuration_is_ready,
)


class TestWorkerConfiguration(unittest.TestCase):
    def test_configured_module_passes_preflight(self):
        status = get_worker_configuration_status(
            {"celery modules": ["another.module", CELERY_MODULE]}
        )

        self.assertTrue(status["configured"])
        self.assertEqual(status["code"], "celery_configured")
        self.assertTrue(
            worker_configuration_is_ready({"celery modules": CELERY_MODULE})
        )

    def test_missing_module_has_actionable_safe_failure(self):
        status = get_worker_configuration_status({"celery modules": ["another.module"]})

        self.assertFalse(status["configured"])
        self.assertEqual(status["code"], "celery_module_missing")
        self.assertEqual(status["required_module"], CELERY_MODULE)
        self.assertEqual(status["docs_url"], CELERY_CONFIGURATION_DOCS_URL)
        self.assertIn("Other editor features remain available", status["message"])

    def test_malformed_configuration_does_not_raise(self):
        class BrokenConfig:
            def get(self, key, default=None):
                raise RuntimeError("configuration unavailable")

        status = get_worker_configuration_status(BrokenConfig())

        self.assertFalse(status["configured"])
        self.assertEqual(status["code"], "celery_configuration_check_failed")
        self.assertEqual(status["details"], {"exception_type": "RuntimeError"})


if __name__ == "__main__":
    unittest.main()
