"""Tests for auto-port-fallback server startup."""

import socket

import pytest

# ── _port_is_available ────────────────────────────────────────────────────────


class TestPortIsAvailable:
    def test_available_port(self):
        from src.server import _port_is_available

        assert _port_is_available("127.0.0.1", 59123) is True

    def test_occupied_port(self):
        from src.server import _port_is_available

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 59124))
            s.listen(1)
            assert _port_is_available("127.0.0.1", 59124) is False


# ── find_available_port ───────────────────────────────────────────────────────


class TestFindAvailablePort:
    def test_preferred_port_available(self):
        from src.server import find_available_port

        port = find_available_port("127.0.0.1", 59200, max_attempts=3)
        assert port == 59200

    def test_fallback_to_next_port(self):
        from src.server import find_available_port

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 59300))
            s.listen(1)
            port = find_available_port("127.0.0.1", 59300, max_attempts=3)
            assert port == 59301

    def test_skips_multiple_occupied_ports(self):
        from src.server import find_available_port

        sockets = []
        try:
            for i in range(2):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", 59400 + i))
                s.listen(1)
                sockets.append(s)

            port = find_available_port("127.0.0.1", 59400, max_attempts=5)
            assert port == 59402
        finally:
            for s in sockets:
                s.close()

    def test_all_ports_occupied_raises(self):
        from src.server import find_available_port

        sockets = []
        try:
            for i in range(3):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", 59500 + i))
                s.listen(1)
                sockets.append(s)

            with pytest.raises(RuntimeError, match="No available port"):
                find_available_port("127.0.0.1", 59500, max_attempts=3)
        finally:
            for s in sockets:
                s.close()


# ── Port file lifecycle ───────────────────────────────────────────────────────


class TestPortFile:
    def test_write_and_read(self, tmp_path, monkeypatch):
        import src.config

        monkeypatch.setattr(src.config, "SERVER_PORT_FILE", tmp_path / "server.port")

        from src.server import _write_port_file

        _write_port_file(8042)
        assert (tmp_path / "server.port").read_text() == "8042"

    def test_remove(self, tmp_path, monkeypatch):
        import src.config

        port_file = tmp_path / "server.port"
        port_file.write_text("8000")
        monkeypatch.setattr(src.config, "SERVER_PORT_FILE", port_file)

        from src.server import _remove_port_file

        _remove_port_file()
        assert not port_file.exists()

    def test_remove_missing_no_error(self, tmp_path, monkeypatch):
        import src.config

        monkeypatch.setattr(src.config, "SERVER_PORT_FILE", tmp_path / "nonexistent.port")

        from src.server import _remove_port_file

        _remove_port_file()  # Should not raise


# ── get_server_url ────────────────────────────────────────────────────────────


class TestGetServerUrl:
    def test_default_when_no_port_file(self, tmp_path, monkeypatch):
        import src.config

        monkeypatch.setattr(src.config, "SERVER_PORT_FILE", tmp_path / "nope.port")
        monkeypatch.setattr(src.config, "SERVER_PORT", 8000)
        monkeypatch.setattr(src.config, "SERVER_HOST", "127.0.0.1")

        assert src.config.get_server_url() == "http://127.0.0.1:8000"

    def test_reads_port_from_file(self, tmp_path, monkeypatch):
        import src.config

        port_file = tmp_path / "server.port"
        port_file.write_text("8003")
        monkeypatch.setattr(src.config, "SERVER_PORT_FILE", port_file)
        monkeypatch.setattr(src.config, "SERVER_PORT", 8000)
        monkeypatch.setattr(src.config, "SERVER_HOST", "127.0.0.1")

        assert src.config.get_server_url() == "http://127.0.0.1:8003"

    def test_falls_back_on_corrupt_port_file(self, tmp_path, monkeypatch):
        import src.config

        port_file = tmp_path / "server.port"
        port_file.write_text("not_a_number")
        monkeypatch.setattr(src.config, "SERVER_PORT_FILE", port_file)
        monkeypatch.setattr(src.config, "SERVER_PORT", 8000)
        monkeypatch.setattr(src.config, "SERVER_HOST", "127.0.0.1")

        assert src.config.get_server_url() == "http://127.0.0.1:8000"
