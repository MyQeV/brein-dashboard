"""Settings API: the log viewer's bounds."""


class TestLogView:
    def test_422_outside_the_line_bounds(self, client):
        for lines in (0, 501):
            r = client.get(f"/api/settings/logs/view?lines={lines}")
            assert r.status_code == 422, lines

    def test_200_within_bounds_for_a_missing_rotation(self, client):
        from brein import logging_setup

        missing = f"{logging_setup.get_log_file()}.2000-01-01"
        r = client.get(f"/api/settings/logs/view?lines=500&file={missing}")
        assert r.status_code == 200
        assert r.json() == {"lines": [], "file": missing}

    def test_400_for_a_file_outside_the_log_directory(self, client):
        r = client.get("/api/settings/logs/view?file=../etc/passwd")
        assert r.status_code == 400

    def test_403_for_a_viewer(self, viewer_client):
        r = viewer_client.get("/api/settings/logs/view?lines=5")
        assert r.status_code == 403
