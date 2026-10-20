"""Spotify access, adapted to the February 2026 Web API changes.

- playlist contents use /playlists/{id}/items and the `item` field (formerly /tracks and `track`)
- batch fetches (GET /artists?ids=...) are gone, artists are fetched one by one

Development mode apps have a daily request quota. To stay under it, playlist contents are
cached and only read again when the playlist's snapshot id changes, and Liked Songs are
only read again when they changed.
"""
import json
import os
import threading
import time

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from urllib3.util.retry import Retry

from config_store import DATA_DIR

CACHE_PATH = DATA_DIR / 'cache' / 'spotify.json'
MAX_WAIT = 30          # seconds; a longer "Retry-After" means the daily quota is used up
SNAPSHOT_TTL = 300     # seconds the list of playlist snapshots is reused
_lock = threading.Lock()
_snapshots = {'at': 0, 'value': {}}


class SpotifyLimitError(RuntimeError):
    def __init__(self, retry_after):
        hours = retry_after / 3600
        when = f'{hours:.0f} h' if hours >= 1 else f'{retry_after / 60:.0f} min'
        super().__init__(f'Spotify request limit reached for today. Try again in about {when}.')
        self.retry_after = retry_after


class _LimitedRetry(Retry):
    """Waits for short rate limits, stops at once when Spotify asks to wait for hours."""

    def get_retry_after(self, response):
        retry_after = super().get_retry_after(response)
        if retry_after is not None and retry_after > MAX_WAIT:
            raise SpotifyLimitError(retry_after)
        return retry_after

SCOPE = ' '.join([
    'user-library-read',
    'user-library-modify',
    'playlist-read-private',
    'playlist-read-collaborative',
    'playlist-modify-private',
    'playlist-modify-public',
    'user-top-read',
    'user-read-recently-played',
])


def create_client():
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise RuntimeError(
            'SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are missing. '
            'Copy src/backend/.env.example to src/backend/.env and fill them in.'
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        # Spotify no longer accepts "localhost", only loopback IPs.
        redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback'),
        scope=SCOPE,
        cache_path=str(DATA_DIR / '.spotify-token'),
        open_browser=True,
    )
    sp = spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=5)
    retry = _LimitedRetry(total=5, connect=None, read=False, status=5, backoff_factor=0.5,
                          allowed_methods=frozenset(['GET', 'POST', 'PUT', 'DELETE']),
                          status_forcelist=(429, 500, 502, 503, 504))
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    sp._session.mount('https://', adapter)
    sp._session.mount('http://', adapter)
    return sp


def _load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        except ValueError:
            pass
    return {'playlists': {}, 'liked': None}


def _save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    tmp.replace(CACHE_PATH)


def _compact(track):
    """Only the fields the app uses, to keep the cache small."""
    album = track.get('album') or {}
    return {
        'id': track['id'], 'name': track['name'],
        'artists': [{'id': a.get('id'), 'name': a.get('name')} for a in track.get('artists', [])],
        'album': {
            'id': album.get('id'), 'name': album.get('name'), 'images': album.get('images') or [],
            'release_date': album.get('release_date'), 'total_tracks': album.get('total_tracks'),
            'album_type': album.get('album_type'),
            'artists': [{'id': a.get('id'), 'name': a.get('name')} for a in album.get('artists', [])],
        },
        'duration_ms': track.get('duration_ms'), 'track_number': track.get('track_number'),
        'disc_number': track.get('disc_number'), 'explicit': track.get('explicit'),
        'external_urls': track.get('external_urls') or {}, 'external_ids': track.get('external_ids') or {},
    }


def _paginate(sp, page):
    items = list(page['items'])
    while page.get('next'):
        page = sp.next(page)
        items.extend(page['items'])
    return items


def _track_of(entry):
    # Playlist entries now carry `item`; saved tracks still carry `track`.
    return entry.get('item') or entry.get('track')


def liked_tracks(sp):
    """Liked Songs, newest first. Read again only when the count or the newest song changed."""
    first = sp.current_user_saved_tracks(limit=50)
    newest = _track_of(first['items'][0])['id'] if first['items'] else None
    signature = [first.get('total'), newest]
    with _lock:
        cache = _load_cache()
        if cache.get('liked') and cache['liked']['signature'] == signature:
            return cache['liked']['tracks']
    tracks = [_compact(t) for t in (_track_of(e) for e in _paginate(sp, first)) if t and t.get('id')]
    with _lock:
        cache = _load_cache()
        cache['liked'] = {'signature': signature, 'tracks': tracks}
        _save_cache(cache)
    return tracks


def _snapshot(sp, playlist_id):
    """Current snapshot id of one of your playlists (from one cached listing of all of them)."""
    with _lock:
        fresh = time.time() - _snapshots['at'] < SNAPSHOT_TTL
    if not fresh or playlist_id not in _snapshots['value']:
        listing = {p['id']: p.get('snapshot_id') for p in my_playlists(sp)}
        with _lock:
            _snapshots.update(at=time.time(), value=listing)
    return _snapshots['value'].get(playlist_id)


def playlist_tracks(sp, playlist_id):
    """Songs of a playlist. Read again only when its snapshot id changed."""
    snapshot = _snapshot(sp, playlist_id)
    with _lock:
        cached = _load_cache()['playlists'].get(playlist_id)
    if snapshot and cached and cached['snapshot'] == snapshot:
        return cached['tracks']
    page = sp._get(f'playlists/{playlist_id}/items', limit=50)
    tracks = [_compact(t) for t in (_track_of(e) for e in _paginate(sp, page)) if t and t.get('id')]
    if snapshot:
        with _lock:
            cache = _load_cache()
            cache['playlists'][playlist_id] = {'snapshot': snapshot, 'tracks': tracks}
            _save_cache(cache)
    return tracks


def _forget_snapshots():
    with _lock:
        _snapshots['at'] = 0


def add_to_playlist(sp, playlist_id, track_ids):
    _forget_snapshots()
    uris = [f'spotify:track:{tid}' for tid in track_ids]
    for i in range(0, len(uris), 100):
        sp._post(f'playlists/{playlist_id}/items', payload={'uris': uris[i:i + 100]})


def remove_from_playlist(sp, playlist_id, track_ids):
    _forget_snapshots()
    uris = [{'uri': f'spotify:track:{tid}'} for tid in track_ids]
    for i in range(0, len(uris), 100):
        sp._delete(f'playlists/{playlist_id}/items', payload={'items': uris[i:i + 100]})


def like_tracks(sp, track_ids):
    """Save tracks to Liked Songs (PUT /me/library, which replaced PUT /me/tracks in 2026)."""
    uris = [f'spotify:track:{tid}' for tid in track_ids]
    for i in range(0, len(uris), 40):
        sp._put('me/library', uris=','.join(uris[i:i + 40]))


def unlike_tracks(sp, track_ids):
    """Remove tracks from Liked Songs (DELETE /me/library)."""
    uris = [f'spotify:track:{tid}' for tid in track_ids]
    for i in range(0, len(uris), 40):
        sp._delete('me/library', uris=','.join(uris[i:i + 40]))


def my_playlists(sp):
    return _paginate(sp, sp.current_user_playlists(limit=50))


def playlist_meta(sp, playlist_id):
    playlist = sp.playlist(playlist_id, fields='id,name,description,images,items(total),tracks(total)')
    total = (playlist.get('items') or playlist.get('tracks') or {}).get('total', 0)
    images = playlist.get('images') or []
    return {
        'id': playlist['id'],
        'name': playlist['name'],
        'description': playlist.get('description') or '',
        'track_count': total,
        'image_url': images[0]['url'] if images else '/assets/default-cover-image.jpg',
    }
