"""Watch the Downloads folder for an exported playlists file and import it.

Watches while the import guide is open (for an hour), and always when the playlists come
from a file. Only files saved after the watch started, or after the last import, are taken.
After the import, the library is checked, and synced when no file has to be moved or removed
(those wait for a confirmation on the Library page).
"""
import threading
import time
from datetime import datetime
from pathlib import Path

import catalog as catalog_store

DOWNLOADS = Path.home() / 'Downloads'
INTERVAL = 3          # seconds between two looks
GUIDE_WATCH = 3600    # seconds the guide keeps the watch on
SETTLE = 2            # seconds a file must stay the same size (still downloading otherwise)

state = {'watching_until': 0, 'last': None, 'error': None, 'started_at': time.time()}
_thread = None
_on_file = None


def start(on_file):
    """Start the watch thread once. on_file(path) runs the import."""
    global _thread, _on_file
    _on_file = on_file
    if _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()


def watch_for_guide():
    state['watching_until'] = time.time() + GUIDE_WATCH
    state['guide_started_at'] = time.time()


def active():
    source = catalog_store.load().get('source')
    return time.time() < state['watching_until'] or source in ('tunemymusic', 'spotify-export')


def _since():
    catalog = catalog_store.load()
    last_import = 0
    if catalog.get('updated_at') and catalog.get('source') in ('tunemymusic', 'spotify-export'):
        last_import = datetime.fromisoformat(catalog['updated_at']).timestamp()
    if time.time() < state['watching_until']:
        return max(last_import, state.get('guide_started_at', 0) - 60)
    return max(last_import, state['started_at'])


def _candidates():
    since = _since()
    if not DOWNLOADS.is_dir():
        return []
    files = []
    for path in DOWNLOADS.iterdir():
        try:
            if path.suffix.lower() in ('.csv', '.zip') and path.stat().st_mtime > since:
                files.append(path)
        except OSError:
            continue
    return sorted(files, key=lambda p: p.stat().st_mtime)


def _loop():
    seen = set()
    while True:
        time.sleep(INTERVAL)
        if not active() or _on_file is None:
            continue
        for path in _candidates():
            key = (str(path), path.stat().st_mtime)
            if key in seen:
                continue
            size = path.stat().st_size
            time.sleep(SETTLE)
            if not path.exists() or path.stat().st_size != size:
                continue
            seen.add(key)
            if catalog_store.detect(path):
                try:
                    _on_file(path)
                    state.update(last=str(path), error=None)
                except Exception as e:  # shown in the guide
                    state.update(last=str(path), error=str(e))
