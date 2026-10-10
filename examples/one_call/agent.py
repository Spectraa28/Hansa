"""JSON stdin/stdout demo; uses only Python's standard library."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def denied(address, port):
    try:
        with socket.create_connection((address, port), timeout=0.15):
            return False
    except OSError:
        return True


def main():
    task = json.load(sys.stdin)
    if task.get("mode") == "timeout":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        print("Injected timeout with a sleeping child process.", file=sys.stderr, flush=True)
        time.sleep(600)
        return
    if task.get("mode") == "overflow":
        while True:
            print("x" * 65536, flush=True)
    if task.get("mode") == "invalid_json":
        print("not json")
        return
    if task.get("mode") == "exit":
        print(json.dumps({"partial": True}))
        print("Intentional nonzero exit.", file=sys.stderr)
        sys.exit(7)
    checks = {"non_root": os.getuid() != 0,
              "no_docker_socket": not Path("/var/run/docker.sock").exists(),
              "metadata_blocked": denied("169.254.169.254", 80),
              "private_10_blocked": denied("10.0.0.1", 80),
              "private_172_blocked": denied("172.16.0.1", 80),
              "private_192_blocked": denied("192.168.0.1", 80),
              "public_egress_blocked": denied("1.1.1.1", 443),
              "host_env_absent": "LITELLM_API_KEY" not in os.environ and "AUTH_SECRET_KEY" not in os.environ}
    try:
        Path("/snapshot/cannot_write").write_text("test")
        checks["snapshot_read_only"] = False
    except OSError:
        checks["snapshot_read_only"] = True
    Path("/scratch/test").write_text("scratch works")
    checks["scratch_writable"] = True
    if task.get("mode") == "isolation":
        print(json.dumps({"isolation": checks}))
        return
    request = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/chat/completions",
        data=json.dumps({"model": "claude-haiku", "messages": [{"role": "user", "content": task["prompt"]}],
                         "max_tokens": 32}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
    with urllib.request.urlopen(request, timeout=65) as response:
        result = json.load(response)
        status = response.status
    print(json.dumps({"http_status": status, "answer": result["choices"][0]["message"]["content"],
                      "usage": result["usage"], "isolation": checks}))


if __name__ == "__main__":
    main()
