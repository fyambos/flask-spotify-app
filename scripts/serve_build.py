"""Serve the built frontend (dist/spotify-app). Unknown paths get index.html, so reloading /home works."""
import http.server
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'dist' / 'spotify-app'


class Handler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        if not (ROOT / self.path.split('?')[0].lstrip('/')).is_file():
            self.path = '/index.html'
        return super().send_head()


port = int(sys.argv[1]) if len(sys.argv) > 1 else 4300
http.server.ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(ROOT))).serve_forever()
