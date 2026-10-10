"""Trusted egress sidecar: the only route from a run to the public internet.

The agent container has no external route. It reaches this HTTP proxy over a
per-run internal network; every destination is resolved here and refused
unless all of its addresses are public. One JSON line per connection goes to
stdout for the controller. Paths, headers and bodies are never logged.
"""
import asyncio
import ipaddress
import json
import re
import socket
import sys
import time

PORTS = {80, 443}
HEAD_LIMIT = 16384
IDLE_SECONDS = 120
HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")
HOP_HEADERS = {"proxy-connection", "proxy-authorization", "connection", "keep-alive"}


def public_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    # is_global alone still accepts multicast ranges.
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_unspecified)


def parse_target(method, target):
    """Return (host, port, origin_path) for CONNECT host:port or an absolute http:// URI."""
    if method == "CONNECT":
        host, separator, port = target.rpartition(":")
        path = None
    else:
        if not target.lower().startswith("http://"):
            raise ValueError("Only absolute http:// requests and CONNECT are proxied.")
        authority, slash, rest = target[7:].partition("/")
        host, separator, port = authority.rpartition(":")
        if not separator:
            host, port = authority, "80"
        path = "/" + rest
    if not port.isascii() or not port.isdecimal() or int(port) not in PORTS:
        raise ValueError("Only ports 80 and 443 are permitted.")
    if "@" in host or not HOST.fullmatch(host):
        raise ValueError("Invalid destination host.")
    return host.lower(), int(port), path


async def resolve(host, port):
    loop = asyncio.get_running_loop()
    try:
        found = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("Destination could not be resolved.") from None
    addresses = [item[4][0] for item in found]
    # Refuse mixed answers too, so a name cannot pair a public address with a private one.
    if not addresses or not all(public_address(address) for address in addresses):
        raise ValueError("Destination is not a public address.")
    return addresses[0]


async def pipe(reader, writer, counter, key):
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), IDLE_SECONDS)
            if not chunk:
                break
            counter[key] += len(chunk)
            writer.write(chunk)
            await writer.drain()
    except (OSError, asyncio.TimeoutError):
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


async def handle(client_reader, client_writer):
    started = time.time()
    record = {"host": None, "port": None, "kind": None, "method": None, "allowed": False,
              "reason": None, "started_at": round(started, 3), "bytes_up": 0, "bytes_down": 0}
    upstream_writer = None
    try:
        try:
            head = await asyncio.wait_for(client_reader.readuntil(b"\r\n\r\n"), 10)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, OSError):
            record["reason"] = "invalid_request"
            return
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
            record["reason"] = "invalid_request"
            client_writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        method, target = parts[0].upper(), parts[1]
        record["method"], record["kind"] = method, "connect" if method == "CONNECT" else "http"
        try:
            host, port, path = parse_target(method, target)
            record["host"], record["port"] = host, port
            address = await resolve(host, port)
        except ValueError as exc:
            record["reason"] = str(exc)
            body = json.dumps({"error": "egress_denied", "detail": str(exc)}).encode()
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\nContent-Length: "
                                + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            return
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(address, port), 15)
        except (OSError, asyncio.TimeoutError):
            record["reason"] = "upstream_unreachable"
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        record["allowed"] = True
        if method == "CONNECT":
            client_writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            # One request per connection keeps every plain-HTTP destination re-checked.
            headers = [line for line in lines[1:] if line and line.split(":", 1)[0].strip().lower() not in HOP_HEADERS]
            request = "\r\n".join([f"{method} {path} {parts[2]}", *headers, "Connection: close"]) + "\r\n\r\n"
            upstream_writer.write(request.encode("latin-1"))
            record["bytes_up"] += len(request)
        await client_writer.drain()
        await asyncio.gather(pipe(client_reader, upstream_writer, record, "bytes_up"),
                             pipe(upstream_reader, client_writer, record, "bytes_down"))
    except OSError:
        record["reason"] = record["reason"] or "connection_error"
    finally:
        for writer in (client_writer, upstream_writer):
            if writer is not None:
                try:
                    await writer.drain()
                    writer.close()
                except OSError:
                    pass
        record["duration_ms"] = int((time.time() - started) * 1000)
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", 3128, limit=HEAD_LIMIT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
