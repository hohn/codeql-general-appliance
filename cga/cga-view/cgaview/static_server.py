"""Loopback static-file server for the live CGA dashboard."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
from urllib.parse import urlsplit


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Serve dashboard assets without browser or intermediary caching."""

    def __init__(self, *args, config: Path | None = None, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)

    def send_head(self):
        if self.config and urlsplit(self.path).path == "/" + self.config.name:
            try:
                data = self.config.read_bytes()
            except OSError as error:
                self.send_error(500, str(error))
                return None
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return io.BytesIO(data)
        return super().send_head()

    def log_message(self, *_args: object) -> None:
        pass

    def end_headers(self) -> None:
        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def serve(port: int, directory: Path, config: Path | None = None) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("port must be 1..65535")
    root = directory.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"dashboard directory not found: {root}")
    if config:
        config = config.expanduser().resolve()
        if not config.is_file():
            raise ValueError(f"dashboard configuration not found: {config}")
    handler = partial(NoCacheHandler, directory=str(root), config=config)
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(
            f"cga dashboard: http://127.0.0.1:{server.server_port}/ "
            f"(root {root}, caching disabled)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="runtime-local dashboard configuration JS")
    args = parser.parse_args(arguments)
    serve(args.port, args.directory, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
