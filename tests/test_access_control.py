"""Tests for AccessControl — role-based access control scaffold."""

from src.auth.access_control import AccessControl, Role


class TestAccessControl:
    def test_add_and_get_user(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        ac.add_user("alice", Role.ADMIN, api_key="key1")
        user = ac.get_user("alice")
        assert user is not None
        assert user.role == Role.ADMIN

    def test_unknown_user(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        assert ac.get_user("nobody") is None

    def test_can_view_pii(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        ac.add_user("admin", Role.ADMIN)
        ac.add_user("editor", Role.EDITOR)
        ac.add_user("viewer", Role.VIEWER)
        assert ac.can_view_pii("admin") is True
        assert ac.can_view_pii("editor") is True
        assert ac.can_view_pii("viewer") is False
        assert ac.can_view_pii("unknown") is False

    def test_can_edit(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        ac.add_user("viewer", Role.VIEWER)
        ac.add_user("editor", Role.EDITOR)
        assert ac.can_edit("editor") is True
        assert ac.can_edit("viewer") is False

    def test_can_admin(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        ac.add_user("admin", Role.ADMIN)
        ac.add_user("editor", Role.EDITOR)
        assert ac.can_admin("admin") is True
        assert ac.can_admin("editor") is False

    def test_filter_results_for_viewer(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        ac.add_user("viewer", Role.VIEWER)
        results = [
            {"content": "safe content", "is_sensitive": False},
            {"content": "SSN: 123-45-6789", "is_sensitive": True, "pii_detections": ["ssn"]},
        ]
        filtered = ac.filter_results(results, "viewer")
        assert "SSN" not in filtered[1]["content"]
        assert "pii_detections" not in filtered[1]
        assert filtered[0]["content"] == "safe content"

    def test_filter_results_for_admin(self, tmp_path):
        ac = AccessControl(config_path=tmp_path / "ac.yaml")
        ac.add_user("admin", Role.ADMIN)
        results = [{"content": "SSN: 123-45-6789", "is_sensitive": True}]
        filtered = ac.filter_results(results, "admin")
        assert "SSN" in filtered[0]["content"]

    def test_persistence(self, tmp_path):
        config_path = tmp_path / "ac.yaml"
        ac1 = AccessControl(config_path=config_path)
        ac1.add_user("alice", Role.EDITOR)

        ac2 = AccessControl(config_path=config_path)
        user = ac2.get_user("alice")
        assert user is not None
        assert user.role == Role.EDITOR
