"""Shared fixtures: a real temporary HTTP server and SQLite database per test class."""
import http.cookiejar
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_server, connect  # noqa: E402


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ""

    def request(self, path, method="GET", data=None, headers=None):
        request = urllib.request.Request(self.base + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf, **(headers or {})})
        try:
            response = self.opener.open(request)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        is_json = "application/json" in response.headers.get("Content-Type", "")
        return response.status, json.loads(raw) if is_json else raw, response.headers

    def login(self, email, password="demo2026"):
        if "@" not in email:
            email += "@atu.kz"
        status, body, _ = self.request("/api/login", "POST", {"email": email, "password": password})
        assert status == 200, body
        status, data, _ = self.request("/api/me")
        assert status == 200, data
        self.csrf, self.user = data["csrf"], data["user"]
        return self

    def get(self, path):
        return self.request(path)

    def post(self, path, data=None):
        return self.request(path, "POST", data if data is not None else {})

    def put(self, path, data):
        return self.request(path, "PUT", data)


class ServerCase(unittest.TestCase):
    ROLES = ("operator", "reviewer", "manager", "admin")

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.temp.name) / "test.sqlite3")
        cls.server = create_server(port=0, db_path=cls.db_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        for role in cls.ROLES:
            setattr(cls, role, Client(cls.base).login(role))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def db(self):
        return connect(self.db_path)

    def ok(self, result, status=200):
        self.assertEqual(result[0], status, result[1])
        return result[1]
