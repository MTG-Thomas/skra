"""Stub Garage Admin API v1 for garage-init.sh harness tests (stdlib only).

Implements just the endpoints scripts/garage-init.sh uses, with in-memory
state. Usage: stub_garage_admin.py <port> <request-log> <expected-token>
State (keys, perms) lives only for the process lifetime; each test starts
a fresh stub unless it explicitly reuses one (rerun/rotation tests).
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(sys.argv[1])
LOG = sys.argv[2]
EXPECTED_TOKEN = sys.argv[3]

KEYS = {}
PERMS = {}
COUNTER = [0]
BUCKET_ID = "b1"


def log(line):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def mint(name):
    COUNTER[0] += 1
    kid = "GK%024x" % COUNTER[0]
    secret = "%064x" % (COUNTER[0] * 7919 + 13)
    KEYS[kid] = {"name": name, "secret": secret}
    PERMS[kid] = {"read": False, "write": False, "owner": False}
    return kid, secret


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        # indent=2: real Garage pretty-prints multi-line JSON (id and name
        # land on separate lines), which naive same-line parsers mishandle.
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        return self.headers.get("Authorization") == "Bearer " + EXPECTED_TOKEN

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode() or "{}")
        except ValueError:
            return {}

    def _route(self, is_post):
        if not self._auth_ok():
            return self._send({"error": "unauthorized"}, 401)
        u = urlparse(self.path)
        # keep_blank_values: real callers send bare flags like ?list.
        q = parse_qs(u.query, keep_blank_values=True)
        log(("POST " if is_post else "GET ") + self.path)
        if u.path == "/v1/health":
            return self._send({})
        if u.path == "/v1/status":
            return self._send({"node": "abc123def456"})
        if u.path == "/v1/layout":
            return self._send({})
        if u.path == "/v1/layout/apply":
            return self._send({})
        if u.path == "/v1/bucket" and is_post:
            return self._send({"id": BUCKET_ID})
        if u.path == "/v1/bucket" and not is_post:
            keys = [
                {
                    "accessKeyId": kid,
                    "name": KEYS[kid]["name"],
                    "read": PERMS[kid]["read"],
                    "write": PERMS[kid]["write"],
                    "owner": PERMS[kid]["owner"],
                }
                for kid in KEYS
            ]
            return self._send({"id": BUCKET_ID, "keys": keys, "objects": 0})
        if u.path == "/v1/key" and not is_post and "list" in q:
            return self._send([{"id": k, "name": v["name"]} for k, v in KEYS.items()])
        if u.path == "/v1/key" and not is_post and "id" in q:
            kid = q["id"][0]
            if kid not in KEYS:
                return self._send({"error": "not found"}, 404)
            info = {
                "name": KEYS[kid]["name"],
                "accessKeyId": kid,
                "permissions": PERMS[kid],
                "buckets": [],
            }
            if q.get("showSecretKey") == ["true"]:
                info["secretAccessKey"] = KEYS[kid]["secret"]
            return self._send(info)
        if u.path == "/v1/key" and is_post and not q:
            name = self._body().get("name", "")
            kid, secret = mint(name)
            return self._send({"name": name, "accessKeyId": kid,
                               "secretAccessKey": secret})
        if u.path == "/v1/key/import" and is_post:
            b = self._body()
            kid, secret, name = b["accessKeyId"], b["secretAccessKey"], b.get("name", "")
            KEYS[kid] = {"name": name, "secret": secret}
            PERMS[kid] = {"read": False, "write": False, "owner": False}
            return self._send({"name": name, "accessKeyId": kid})
        if u.path == "/v1/bucket/allow" and is_post:
            b = self._body()
            PERMS[b["accessKeyId"]] = {
                "read": True, "write": True, "owner": True}
            return self._send({})
        if u.path == "/v1/bucket/deny" and is_post:
            b = self._body()
            p = b.get("permissions", {})
            cur = PERMS[b["accessKeyId"]]
            for k in ("read", "write", "owner"):
                if p.get(k) is True:
                    cur[k] = False
            return self._send({})
        return self._send({"error": "not found"}, 404)

    def do_GET(self):
        self._route(False)

    def do_POST(self):
        self._route(True)

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
