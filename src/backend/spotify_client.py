"""Spotify access, adapted to the February 2026 Web API changes.

- playlist contents use /playlists/{id}/items and the `item` field (formerly /tracks and `track`)
- batch fetches (GET /artists?ids=...) are gone, artists are fetched one by one
"""
import os

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config_store import DATA_DIR

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
    return spotipy.Spotify(auth_manager=auth, requests_timeout=20, retries=5)


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
    page = sp.current_user_saved_tracks(limit=50)
    return [t for t in (_track_of(e) for e in _paginate(sp, page)) if t and t.get('id')]


def playlist_tracks(sp, playlist_id):
    page = sp._get(f'playlists/{playlist_id}/items', limit=50)
    return [t for t in (_track_of(e) for e in _paginate(sp, page)) if t and t.get('id')]


def add_to_playlist(sp, playlist_id, track_ids):
    uris = [f'spotify:track:{tid}' for tid in track_ids]
    for i in range(0, len(uris), 100):
        sp._post(f'playlists/{playlist_id}/items', payload={'uris': uris[i:i + 100]})


def remove_from_playlist(sp, playlist_id, track_ids):
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
