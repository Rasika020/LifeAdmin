"""Loopback-only HTTP server for the LifeAdmin browser application."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from lifeadmin_mcp import storage

_WEB_ROOT = Path(__file__).with_name("web_static")
_MAX_REQUEST_BYTES = 16_384
_ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
_LOG = logging.getLogger("lifeadmin.web")


class LifeAdminHandler(BaseHTTPRequestHandler):
    server_version = "LifeAdmin"

    def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message})

    def _check_host(self) -> bool:
        try:
            host = urlsplit(f"//{self.headers.get('Host', '')}").hostname
        except ValueError:
            host = None
        host = host.lower() if host else ""
        if host in _ALLOWED_HOSTS:
            return True
        self._send_error_json(HTTPStatus.FORBIDDEN, "Use the local LifeAdmin address.")
        return False

    def _read_json(self) -> dict[str, object]:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ValueError("A valid Content-Length is required") from error
        if not 0 < length <= _MAX_REQUEST_BYTES:
            raise ValueError(f"Request body must be between 1 and {_MAX_REQUEST_BYTES} bytes")
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must contain valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _handle_api_error(self, error: Exception) -> None:
        if isinstance(error, ValueError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        else:
            _LOG.exception("LifeAdmin request failed", exc_info=error)
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "The local reminder store could not complete the request.",
            )

    def do_GET(self) -> None:
        if not self._check_host():
            return
        request = urlsplit(self.path)
        if request.path == "/":
            self._serve_static("index.html")
        elif request.path in ("/app.js", "/styles.css"):
            self._serve_static(request.path[1:])
        elif request.path == "/api/date":
            self._send_json(HTTPStatus.OK, storage.get_current_date())
        elif request.path == "/api/reminders":
            query = parse_qs(request.query)
            status = query.get("status", ["all"])[0]
            try:
                reminders = storage.list_reminders(status, limit=100)
                self._send_json(HTTPStatus.OK, {"reminders": reminders})
            except (ValueError, OSError, sqlite3.Error) as error:
                self._handle_api_error(error)
        else:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Page or endpoint not found.")

    def do_POST(self) -> None:
        if not self._check_host():
            return
        request_path = urlsplit(self.path).path
        try:
            payload = self._read_json()
            if request_path == "/api/reminders":
                allowed_fields = {"title", "due_date", "due_time", "category", "notes"}
                unknown_fields = payload.keys() - allowed_fields
                if unknown_fields:
                    raise ValueError(f"Unknown field: {sorted(unknown_fields)[0]}")
                reminder = storage.add_reminder(
                    title=self._string_field(payload, "title"),
                    due_date=self._string_field(payload, "due_date"),
                    due_time=self._optional_string_field(payload, "due_time"),
                    category=self._optional_string_field(payload, "category"),
                    notes=self._optional_string_field(payload, "notes"),
                )
                self._send_json(HTTPStatus.CREATED, {"reminder": reminder})
                return
            reminder_id = self._reminder_id_from_path(request_path, "/complete")
            if reminder_id is not None:
                reminder = storage.mark_completed(reminder_id=reminder_id)
                self._send_json(HTTPStatus.OK, {"reminder": reminder})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except (ValueError, OSError, sqlite3.Error) as error:
            self._handle_api_error(error)

    def do_PATCH(self) -> None:
        if not self._check_host():
            return
        request_path = urlsplit(self.path).path
        try:
            reminder_id = self._reminder_id_from_path(request_path)
            if reminder_id is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found.")
                return
            payload = self._read_json()
            allowed_fields = {
                "title",
                "due_date",
                "due_time",
                "category",
                "notes",
                "clear_due_time",
            }
            unknown_fields = payload.keys() - allowed_fields
            if unknown_fields:
                raise ValueError(f"Unknown field: {sorted(unknown_fields)[0]}")
            clear_due_time = payload.get("clear_due_time", False)
            if not isinstance(clear_due_time, bool):
                raise ValueError("clear_due_time must be a boolean")
            reminder = storage.update_reminder(
                reminder_id=reminder_id,
                title=self._optional_string_field(payload, "title"),
                due_date=self._optional_string_field(payload, "due_date"),
                due_time=self._optional_string_field(payload, "due_time"),
                category=self._optional_string_field(payload, "category"),
                notes=self._optional_string_field(payload, "notes"),
                clear_due_time=clear_due_time,
            )
            self._send_json(HTTPStatus.OK, {"reminder": reminder})
        except (ValueError, OSError, sqlite3.Error) as error:
            self._handle_api_error(error)

    def _serve_static(self, name: str) -> None:
        path = _WEB_ROOT / name
        try:
            body = path.read_bytes()
        except OSError:
            _LOG.exception("Unable to serve LifeAdmin UI asset: %s", name)
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "The LifeAdmin UI asset could not be loaded.",
            )
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript",):
            content_type += "; charset=utf-8"
        self._send_bytes(HTTPStatus.OK, body, content_type)

    @staticmethod
    def _string_field(payload: dict[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        return value

    @classmethod
    def _optional_string_field(cls, payload: dict[str, object], name: str) -> str | None:
        if name not in payload or payload[name] is None:
            return None
        return cls._string_field(payload, name)

    @staticmethod
    def _reminder_id_from_path(path: str, suffix: str = "") -> str | None:
        prefix = "/api/reminders/"
        if not path.startswith(prefix) or (suffix and not path.endswith(suffix)):
            return None
        value = path[len(prefix) : -len(suffix) if suffix else None]
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("Reminder ID must be a valid UUID") from error

    def log_message(self, format: str, *args: object) -> None:
        _LOG.info("%s - %s", self.address_string(), format % args)


class _LifeAdminHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lifeadmin-web",
        description="Run the local LifeAdmin reminder web application.",
    )
    parser.add_argument("--host", choices=sorted(_ALLOWED_HOSTS), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    server = _LifeAdminHTTPServer((args.host, args.port), LifeAdminHandler)
    print(f"LifeAdmin is available at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LifeAdmin.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
