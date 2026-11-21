"""An isolated, bounded gateway for viewer integration tests."""

import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

COLLECTION = Path(__file__).resolve().parents[1]


def start_gateway(test, ports):
    if not shutil.which("go"):
        test.skipTest("gateway integration requires Go")
    temporary = tempfile.TemporaryDirectory(prefix="cga-gateway-test-")
    test.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    binary = root / "gateway"
    subprocess.run(
        ["go", "build", "-o", str(binary), "."],
        cwd=COLLECTION / "cgagateway", check=True, capture_output=True)
    config = root / "ports.json"
    config.write_text(json.dumps(ports))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log = (root / "gateway.log").open("w+")
    test.addCleanup(log.close)
    process = subprocess.Popen(
        [str(binary), "--port", str(port), "--config", str(config),
         "--docs-root", str(COLLECTION.parent)],
        stdout=log, stderr=subprocess.STDOUT)

    def stop():
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
    test.addCleanup(stop)
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    opener = build_opener(ProxyHandler({}))
    while True:
        if process.poll() is not None:
            log.seek(0)
            test.fail("gateway exited before becoming ready: " + log.read())
        try:
            with opener.open(origin + "/healthz", timeout=1):
                return origin
        except OSError:
            if time.monotonic() > deadline:
                test.fail("gateway failed to become ready")
            time.sleep(.05)
