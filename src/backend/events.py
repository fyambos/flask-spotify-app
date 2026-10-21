"""Changes pushed to the pages (Server-Sent Events), so they never poll the backend.

Topics:
- a job name ('library', 'likes', 'import'...): the job state, at every step and every song
- 'status': what the app can do changed (Spotify login, playlists imported, songs sorted)

Each page opens one stream (GET /events) and receives every event as JSON:
{"topic": "library", "data": {...}}.
"""
import json
import queue
import threading

_subscribers = set()
_lock = threading.Lock()
# Failsafe only: a comment line is sent when nothing happened for this long, so proxies and
# browsers don't close an idle stream. It is not used to send state.
KEEPALIVE = 25


def publish(topic, data=None):
    message = json.dumps({'topic': topic, 'data': data})
    with _lock:
        for q in list(_subscribers):
            q.put(message)


def stream():
    """Generator for the Flask response: one SSE message per event, until the page closes it."""
    q = queue.Queue()
    with _lock:
        _subscribers.add(q)
    try:
        yield ': connected\n\n'
        while True:
            try:
                message = q.get(timeout=KEEPALIVE)
            except queue.Empty:
                yield ': keepalive\n\n'
                continue
            yield f'data: {message}\n\n'
    finally:
        with _lock:
            _subscribers.discard(q)
