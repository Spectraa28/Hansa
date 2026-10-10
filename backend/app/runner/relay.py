"""Trusted, networkless sidecar: loopback HTTP to the gateway Unix socket."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/broker/gateway.sock")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/gateway/v1/chat/completions":
            self.send_error(404)
            return
        length = self.headers.get("Content-Length", "")
        if (not length.isascii() or not length.isdecimal() or not 0 < int(length) <= 1024 * 1024
                or self.headers.get("Transfer-Encoding")):
            self.send_error(413)
            return
        self.connection.settimeout(70)
        connection = UnixConnection("localhost", timeout=70)
        try:
            body = self.rfile.read(int(length))
            if len(body) != int(length):
                self.send_error(400)
                return
            connection.request("POST", self.path, body=body,
                headers={"Content-Type": "application/json", "Authorization": self.headers.get("Authorization", "")})
            response = connection.getresponse()
            content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                self.send_error(502)
                return
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (OSError, http.client.HTTPException):
            self.send_error(502)
        finally:
            connection.close()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    server.daemon_threads = True
    server.serve_forever()
