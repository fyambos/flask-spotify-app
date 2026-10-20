"""Artist genre lookup: Spotify artist genres combined with Last.fm top tags.

Spotify genres are now often sparse (one genre or none for many artists), so both
sources are always used.

Results are cached per artist in data/cache/artist-genres.json, so each artist is
only looked up once (the Spotify batch endpoint no longer exists).
"""
import json
import os
import re
import time

import requests

from config_store import DATA_DIR

CACHE_PATH = DATA_DIR / 'cache' / 'artist-genres.json'
LASTFM_URL = 'https://ws.audioscrobbler.com/2.0/'

# Last.fm tags that describe the listener, not the music.
LASTFM_NOISE = {
    'seen live', 'favorites', 'favourite', 'favorite', 'love', 'awesome', 'beautiful',
    'my favorite', 'favourites', 'albums i own', 'spotify', 'under 2000 listeners',
    'male vocalists', 'female vocalists', 'all', 'cool', 'good', 'amazing',
}


NAME_PREFIX = 'name:'


def artist_key(artist):
    """The Spotify id of an artist, or 'name:<name>' for artists read from a file."""
    return artist.get('id') or NAME_PREFIX + re.sub(r'\s+', ' ', (artist.get('name') or '').strip().lower())


class GenreResolver:
    def __init__(self, sp, lastfm_api_key=None, min_tag_count=10, max_tags=10):
        self.sp = sp
        self.lastfm_api_key = lastfm_api_key or os.getenv('LASTFM_API_KEY')
        self.min_tag_count = min_tag_count
        self.max_tags = max_tags
        self.cache = json.loads(CACHE_PATH.read_text(encoding='utf-8')) if CACHE_PATH.exists() else {}
        self._dirty = 0
        self._spotify_failed = False

    def artist_genres(self, artist_id, artist_name):
        """Return the cache entry {'name', 'spotify': [...], 'lastfm': [...], 'genres': [...]}."""
        entry = self.cache.get(artist_id)
        if entry is not None and 'spotify' not in entry:
            entry = self._upgrade(entry)

        if entry is None or entry.get('spotify') is None:
            # Artists read from a file have no Spotify id, and without Spotify there are only Last.fm genres.
            spotify = None
            if not artist_id.startswith(NAME_PREFIX) and self._spotify_usable():
                try:
                    spotify = [g.lower() for g in (self.sp.artist(artist_id).get('genres') or [])]
                except Exception:
                    self._spotify_failed = True
            entry = {**(entry or {}), 'name': artist_name, 'spotify': spotify}
        if 'lastfm' not in entry and self.lastfm_api_key:
            entry['lastfm'] = self._lastfm_tags(artist_name)

        entry['genres'] = list(dict.fromkeys((entry['spotify'] or []) + entry.get('lastfm', [])))
        if self.cache.get(artist_id) != entry:
            self.cache[artist_id] = entry
            self._dirty += 1
            if self._dirty >= 25:
                self.save()
        return entry

    @staticmethod
    def _upgrade(old):
        """Convert a cache entry from the old format (Last.fm only when Spotify had nothing)."""
        if old['source'] == 'spotify':
            return {'name': old['name'], 'spotify': old['genres']}
        return {'name': old['name'], 'spotify': [], 'lastfm': old['genres']}

    def _spotify_usable(self):
        from spotify_client import blocked, keys_present, logged_in
        return not self._spotify_failed and keys_present() and logged_in() and not blocked()

    def track_genres(self, track):
        """Union of the genres of all the track's artists."""
        genres = []
        for artist in track.get('artists', []):
            if not artist.get('name') and not artist.get('id'):
                continue
            for g in self.artist_genres(artist_key(artist), artist['name'])['genres']:
                if g not in genres:
                    genres.append(g)
        return genres

    def _lastfm_tags(self, artist_name):
        params = {
            'method': 'artist.gettoptags',
            'artist': artist_name,
            'autocorrect': 1,
            'api_key': self.lastfm_api_key,
            'format': 'json',
        }
        for attempt in range(3):
            try:
                resp = requests.get(LASTFM_URL, params=params, timeout=15)
                if resp.status_code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                tags = resp.json().get('toptags', {}).get('tag', [])
                break
            except (requests.RequestException, ValueError):
                time.sleep(1)
        else:
            return []
        result = []
        for tag in tags:
            name = tag.get('name', '').strip().lower()
            if int(tag.get('count', 0)) < self.min_tag_count or not name or name in LASTFM_NOISE:
                continue
            result.append(name)
            if len(result) >= self.max_tags:
                break
        return result

    def save(self):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(CACHE_PATH)
        self._dirty = 0


def keyword_pattern(keyword):
    """A keyword matches whole words; `*` matches any letters (`k-*` matches `k-pop`, `k-rap`)."""
    body = r'\S*'.join(re.escape(part) for part in keyword.strip().lower().split('*'))
    return re.compile(rf'(?<![\w-]){body}(?![\w-])')


def matches_any(texts, keywords):
    """First keyword found in one of the texts, or None."""
    for keyword in keywords:
        if not keyword.strip():
            continue
        pattern = keyword_pattern(keyword)
        if any(pattern.search(t.lower()) for t in texts):
            return keyword
    return None


def matching_playlists(genres, playlists):
    """Configured playlists (in priority order) whose genre keywords match, skipping excluded ones."""
    return [
        p for p in playlists
        if matches_any(genres, p['genre_names']) and not matches_any(genres, p.get('exclude_genres', []))
    ]
