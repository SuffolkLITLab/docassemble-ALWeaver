# do not pre-load

import unittest
from unittest.mock import patch

from docassemble.ALWeaver.custom_values import get_default_github_username


class GetDefaultGithubUsernameTest(unittest.TestCase):
    """Tests for get_default_github_username().

    The function imports its dependencies lazily inside the function body, so we
    patch them at the module they live in rather than in custom_values.
    """

    def test_prefers_first_organization_over_personal_account(self):
        """When the user belongs to orgs, the first org is returned."""
        owners = [
            {"login": "myuser", "type": "user"},
            {"login": "myorg", "type": "organization"},
            {"login": "secondorg", "type": "organization"},
        ]
        with patch(
            "docassemble.ALWeaver.docassemble_compat.get_github_publish_owners",
            return_value=owners,
        ):
            result = get_default_github_username()
        self.assertEqual(result, "myorg")

    def test_falls_back_to_personal_account_when_no_org(self):
        """When there are no orgs, the personal account login is returned."""
        owners = [{"login": "myuser", "type": "user"}]
        with patch(
            "docassemble.ALWeaver.docassemble_compat.get_github_publish_owners",
            return_value=owners,
        ):
            result = get_default_github_username()
        self.assertEqual(result, "myuser")

    def test_falls_back_to_server_config_when_github_raises(self):
        """When get_github_publish_owners raises, fall back to server config."""
        with patch(
            "docassemble.ALWeaver.docassemble_compat.get_github_publish_owners",
            side_effect=Exception("no token"),
        ), patch(
            "docassemble.base.util.get_config",
            return_value={"default repository owner": "ServerOrg"},
        ):
            result = get_default_github_username()
        self.assertEqual(result, "ServerOrg")

    def test_returns_empty_string_when_nothing_available(self):
        """When both GitHub and server config raise, return ''."""
        with patch(
            "docassemble.ALWeaver.docassemble_compat.get_github_publish_owners",
            side_effect=Exception("no token"),
        ), patch(
            "docassemble.base.util.get_config",
            side_effect=Exception("no config"),
        ):
            result = get_default_github_username()
        self.assertEqual(result, "")

    def test_strips_whitespace_from_server_config(self):
        """Server config values with surrounding whitespace are stripped."""
        with patch(
            "docassemble.ALWeaver.docassemble_compat.get_github_publish_owners",
            side_effect=Exception("no token"),
        ), patch(
            "docassemble.base.util.get_config",
            return_value={"default repository owner": "  myorg  "},
        ):
            result = get_default_github_username()
        self.assertEqual(result, "myorg")

    def test_ignores_empty_server_config(self):
        """An empty/blank server config value is treated as not configured."""
        with patch(
            "docassemble.ALWeaver.docassemble_compat.get_github_publish_owners",
            side_effect=Exception("no token"),
        ), patch(
            "docassemble.base.util.get_config",
            return_value={"default repository owner": ""},
        ):
            result = get_default_github_username()
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
