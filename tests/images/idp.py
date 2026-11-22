"""Serve the existing signed OIDC fixture over HTTPS to the real admin app."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import ssl
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, "/oidc")
from fake_idp import FakeIdP

issuer = os.environ["OIDC_PROVIDER_INFO_URL"]
callback = "https://mail.example.org" + os.environ["WEB_BASE_PATH"] + "/sso/login/oidc"
idp = FakeIdP(issuer=issuer)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == "/authorize":
            args = parse_qs(path.query)
            assert args["redirect_uri"] == [callback], args
            assert args["client_id"] == ["mailu"] and args["response_type"] == ["code"], args
            idp.nonce = args["nonce"][0]
            query = urlencode({"code": "valid-code", "state": args["state"][0]})
            self.send_response(302)
            self.send_header("Location", callback + "?" + query)
            self.end_headers()
        elif path.path == "/checked":
            self.send_response(200 if any(path == "/introspect" for path, _ in idp.calls) else 409)
            self.end_headers()
        else:
            self.respond()

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        args = parse_qs(body)
        if self.path == "/token":
            assert args["code"] == ["valid-code"] and args["redirect_uri"] == [callback], args
        if self.path == "/introspect":
            assert args["token"] == ["access-1"], args
        self.respond(data=body)

    def respond(self, **kwargs):
        response = idp.request(self.command, issuer + self.path, **kwargs)
        self.send_response(response.status_code)
        self.send_header("Content-Type", response.headers["Content-Type"])
        self.end_headers()
        self.wfile.write(response.content)


httpd = HTTPServer(("", 8443), Handler)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain("/fixture-tls/cert.pem", "/fixture-tls/key.pem")
httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
httpd.serve_forever()
