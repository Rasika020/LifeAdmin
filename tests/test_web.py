import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from lifeadmin_mcp.web import LifeAdminHandler


@pytest.fixture
def web_server(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEADMIN_DB_PATH", str(tmp_path / "web.sqlite3"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), LifeAdminHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request_json(url, method="GET", body=None, headers=None):
    request_headers = {"Content-Type": "application/json"} if body is not None else {}
    request_headers.update(headers or {})
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=request_headers,
        method=method,
    )
    with urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_web_ui_serves_and_reminder_crud_uses_local_storage(web_server):
    with urlopen(f"{web_server}/") as response:
        assert response.status == 200
        assert b"LifeAdmin" in response.read()
    for path, marker in (("/app.js", b"localDate"), ("/styles.css", b"--lime")):
        with urlopen(f"{web_server}{path}") as response:
            assert response.status == 200
            assert marker in response.read()

    status, date = request_json(f"{web_server}/api/date")
    assert status == 200
    assert date["current_date"]
    assert date["timezone"]

    status, listing = request_json(f"{web_server}/api/reminders?status=all")
    assert status == 200
    assert listing["reminders"] == []

    status, created = request_json(
        f"{web_server}/api/reminders",
        "POST",
        {
            "title": "Renew insurance",
            "due_date": "2030-11-10",
            "due_time": "09:30",
            "category": "Documents",
            "notes": "Compare providers",
        },
    )
    reminder = created["reminder"]
    assert status == 201
    assert reminder["title"] == "Renew insurance"
    assert reminder["status"] == "open"

    status, updated = request_json(
        f"{web_server}/api/reminders/{reminder['id']}",
        "PATCH",
        {
            "title": "Renew car insurance",
            "due_time": None,
            "clear_due_time": True,
        },
    )
    assert status == 200
    assert updated["reminder"]["title"] == "Renew car insurance"
    assert updated["reminder"]["due_time"] is None
    assert updated["reminder"]["category"] == "Documents"

    status, completed = request_json(
        f"{web_server}/api/reminders/{reminder['id']}/complete",
        "POST",
        {},
    )
    assert status == 200
    assert completed["reminder"]["status"] == "completed"

    status, listing = request_json(f"{web_server}/api/reminders?status=completed")
    assert status == 200
    assert [item["id"] for item in listing["reminders"]] == [reminder["id"]]


@pytest.mark.parametrize(
    ("path", "method", "body", "expected_status"),
    [
        ("/api/reminders", "POST", {"title": "", "due_date": "2030-11-10"}, 400),
        ("/api/reminders", "POST", {"title": "Task"}, 400),
        ("/api/reminders?status=unsupported", "GET", None, 400),
        ("/api/reminders/not-a-uuid", "PATCH", {"title": "Changed"}, 400),
    ],
)
def test_web_api_reports_invalid_requests(
    web_server, path, method, body, expected_status
):
    request = Request(
        f"{web_server}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request)
    assert error.value.code == expected_status
    assert json.loads(error.value.read())["error"]


def test_web_api_rejects_non_local_host(web_server):
    for host in ("example.com", "[::bad"):
        request = Request(
            f"{web_server}/api/date",
            headers={"Host": host},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
