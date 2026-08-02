"""Static server for dist/ plus POST /shot to save canvas captures."""
import base64
import json
import pathlib
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).parent
DIST = ROOT / "dist"
SHOTS = ROOT / "shots"
SHOTS.mkdir(exist_ok=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_POST(self):
        if self.path != "/shot":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        data_url = payload["data"]
        name = re.sub(r"[^a-zA-Z0-9_-]", "", payload.get("name", "shot"))[:60] or "shot"
        m = re.match(r"data:image/(png|jpeg);base64,(.*)", data_url, re.S)
        ext = m.group(1).replace("jpeg", "jpg")
        out = SHOTS / f"{name}.{ext}"
        out.write_bytes(base64.b64decode(m.group(2)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"saved": out.name}).encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8735), Handler).serve_forever()
