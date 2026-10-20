"""Sort liked tracks into the genre playlists, following the rules in data/config.json.

For each liked track, in this order:
1. already in one of the genre playlists -> left as is
2. a choice remembered for its artist (artist_rules)
3. album / title keywords of a genre, in priority order
4. artist history: the genre playlist holding most of the tracks of its artists
   (featured artists and related names like "Selena Gomez & The Scene" count too)
5. genre keywords (Spotify + Last.fm) minus excluded genres; when several playlists
   match, the one whose tracks have the most similar genres wins (priority breaks ties)
6. otherwise -> review list, where you pick the genre yourself (with a suggestion)

Liked Songs are never modified. The preview is saved in data/likes-preview.json and
nothing is added to Spotify until it is applied.
"""
import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime

import config_store
from config_store import DATA_DIR
from genres import GenreResolver, matches_any, matching_playlists
from spotify_client import add_to_playlist, liked_tracks, playlist_tracks

PREVIEW_PATH = DATA_DIR / 'likes-preview.json'
FEATURED_WEIGHT = 0.5      # a featured artist counts half in the artist history
RELATED_NAME_MIN_LEN = 4   # shortest artist name used to link related names
PROFILE_SMOOTHING = 10     # keeps small playlists from looking more similar than they are
# What may follow an artist name in a variant of it: "X & The Band", "X feat. Y", "X (live)"...
RELATED_NAME_SEPARATOR = re.compile(r'\s*(&|and|x|,|feat\.?|ft\.?|with|\(|-)\s')


def _norm(name):
    return re.sub(r'\s+', ' ', name.strip().lower())


class Classifier:
    def __init__(self, sp, config, resolver, progress=None):
        self.sp = sp
        self.config = config
        self.playlists = config['playlists']
        self.by_id = {p['id']: p for p in self.playlists}
        self.resolver = resolver
        self.track_index = {}
        self.artist_counts = defaultdict(Counter)
        self.artist_ids_by_name = defaultdict(set)
        self.genre_profile = defaultdict(Counter)
        self.playlist_sizes = Counter()
        self.genre_totals = Counter()
        self.progress = progress or (lambda **kw: None)

    def build_index(self):
        for i, entry in enumerate(self.playlists, 1):
            self.progress(step=f"Reading genre playlist {entry['name']} ({i}/{len(self.playlists)})")
            for track in playlist_tracks(self.sp, entry['playlist_id']):
                self.add_track(entry['id'], track)

    def add_track(self, entry_id, track, sign=1):
        """Count a track of a genre playlist in the index (sign=-1 removes it again)."""
        if sign > 0:
            self.track_index.setdefault(track['id'], entry_id)
        for position, artist in enumerate(track['artists']):
            if not artist.get('id'):
                continue
            self.artist_counts[artist['id']][entry_id] += sign * (1 if position == 0 else FEATURED_WEIGHT)
            self.artist_ids_by_name[_norm(artist['name'])].add(artist['id'])
        track_genres = set(self.resolver.track_genres(track))
        for genre in track_genres:
            self.genre_profile[entry_id][genre] += sign
            self.genre_totals[genre] += sign
        self.playlist_sizes[entry_id] += sign

    def _related_artist_ids(self, name):
        """Indexed artists that are a variant of this name: "Selena Gomez" <-> "Selena Gomez & The Scene"."""
        name = _norm(name)
        related = set()
        for other, ids in self.artist_ids_by_name.items():
            if other == name:
                continue
            short, long = (other, name) if len(other) < len(name) else (name, other)
            if len(short) >= RELATED_NAME_MIN_LEN and RELATED_NAME_SEPARATOR.match(long[len(short):]) \
                    and long.startswith(short):
                related |= ids
        return related

    def artist_history(self, track, genres=()):
        """(entry id, reason) of the playlist holding most of the track's artists, or None.

        Playlists that exclude one of the song's genres are left out.
        """
        history = self.config['artist_history']
        if not history.get('enabled'):
            return None
        excluded = {p['id'] for p in self.playlists if matches_any(genres, p['exclude_genres'])}
        counts, sources = Counter(), []
        for position, artist in enumerate(track['artists']):
            weight = 1 if position == 0 else FEATURED_WEIGHT
            ids = {artist.get('id')} | self._related_artist_ids(artist['name'])
            for artist_id in ids:
                for entry_id, n in self.artist_counts.get(artist_id, {}).items():
                    if n > 0 and entry_id not in excluded:
                        counts[entry_id] += n * weight
                        sources.append(artist_id)
        if not counts:
            return None
        entry_id, count = counts.most_common(1)[0]
        total = sum(counts.values())
        if count / total < history.get('min_share', 0.6):
            return None
        names = {self.resolver.cache.get(a, {}).get('name') for a in sources} - {None}
        via = f" via {', '.join(sorted(names))}" if names else ''
        return entry_id, f"artist history ({count:g}/{total:g} in {self.by_id[entry_id]['name']}{via})"

    def similarity(self, entry_id, genres):
        """How characteristic the track's genres are of a genre playlist.

        Average lift: share of the playlist's tracks with the genre, divided by the share
        of all sorted tracks with it. A common genre like "pop" weighs little, a specific
        one like "electronic" or "phonk" weighs a lot.
        """
        size = self.playlist_sizes[entry_id] + PROFILE_SMOOTHING
        total_size = sum(self.playlist_sizes.values()) or 1
        profile = self.genre_profile[entry_id]
        lifts = [
            (profile[g] / size) / (self.genre_totals[g] / total_size)
            for g in genres if self.genre_totals[g]
        ]
        return sum(lifts) / len(lifts) if lifts else 0.0

    def best_by_similarity(self, candidates, genres):
        # max() keeps the first of equal scores, so the priority order breaks ties.
        return max(candidates, key=lambda entry: self.similarity(entry['id'], genres))

    def classify(self, track, evaluating=False):
        """Classify a track. evaluating=True ignores the track's current place (to measure the rules)."""
        artist = track['artists'][0]
        album = (track.get('album') or {}).get('name', '')
        result = {
            'track_id': track['id'],
            'name': track['name'],
            'artists': [a['name'] for a in track['artists']],
            'artist_id': artist.get('id'),
            'album': album,
            'image_url': ((track.get('album') or {}).get('images') or [{}])[-1].get('url'),
            'genres': [],
            'playlist': None,
            'also': [],
            'suggestion': None,
            'status': 'review',
            'reason': 'no rule matched',
        }

        if not evaluating and track['id'] in self.track_index:
            return {**result, 'playlist': self.track_index[track['id']], 'status': 'already',
                    'reason': 'already in a genre playlist'}

        rule = self.config['artist_rules'].get(artist.get('id'))
        if rule and rule['playlist'] in self.by_id:
            return {**result, 'playlist': rule['playlist'], 'status': 'auto', 'reason': 'remembered artist choice'}

        genres = self.resolver.track_genres(track)
        result['genres'] = genres

        keyword_matches = []
        for entry in self.playlists:
            if matches_any(genres, entry['exclude_genres']):
                continue
            keyword = matches_any([album], entry['album_keywords'])
            if keyword:
                keyword_matches.append((entry['id'], f'album keyword "{keyword}"'))
                continue
            keyword = matches_any([track['name']], entry['title_keywords'])
            if keyword:
                keyword_matches.append((entry['id'], f'title keyword "{keyword}"'))
        multi = self.config.get('multi_playlist', False)
        if keyword_matches and not multi:
            return {**result, 'playlist': keyword_matches[0][0], 'status': 'auto', 'reason': keyword_matches[0][1]}

        style = self._style_playlist(track, genres)
        # Several playlists allowed: every keyword match, plus the style playlist.
        places = keyword_matches + ([style] if style and style[0] not in {k for k, _ in keyword_matches} else [])
        if places:
            order = {p['id']: i for i, p in enumerate(self.playlists)}
            places.sort(key=lambda place: order[place[0]])
            return {**result, 'playlist': places[0][0], 'also': [p for p, _ in places[1:]], 'status': 'auto',
                    'reason': ' + '.join(reason for _, reason in places)}

        allowed = [p for p in self.playlists if not matches_any(genres, p['exclude_genres'])]
        if genres and allowed:
            best = self.best_by_similarity(allowed, genres)
            if self.similarity(best['id'], genres) > 0:
                result['suggestion'] = best['id']
        return result

    def _style_playlist(self, track, genres):
        """(entry id, reason) from the artist history, else from the genres, or None."""
        history = self.artist_history(track, genres)
        if history:
            return history
        matches = matching_playlists(genres, self.playlists)
        if matches:
            best = self.best_by_similarity(matches, genres)
            keyword = matches_any(genres, best['genre_names'])
            others = f", closest of {', '.join(m['name'] for m in matches)}" if len(matches) > 1 else ''
            return best['id'], f'genre "{keyword}"{others}'
        return None


def load_preview():
    if PREVIEW_PATH.exists():
        return json.loads(PREVIEW_PATH.read_text(encoding='utf-8'))
    return None


def save_preview(preview):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PREVIEW_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(preview, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(PREVIEW_PATH)


def build_preview(sp, progress=None):
    progress = progress or (lambda **kw: None)
    config = config_store.load_config()
    resolver = GenreResolver(sp)
    classifier = Classifier(sp, config, resolver, progress)
    classifier.build_index()

    progress(step='Reading liked songs')
    tracks = liked_tracks(sp)
    items = []
    for i, track in enumerate(tracks, 1):
        items.append(classifier.classify(track))
        if i % 10 == 0 or i == len(tracks):
            progress(step='Classifying liked songs', done=i, total=len(tracks))
    resolver.save()

    preview = {'generated_at': datetime.now().isoformat(timespec='seconds'), 'items': items}
    save_preview(preview)
    return preview


def resolve_review(track_id, entry_id, remember_artist):
    """Choose the genre of a track by hand (from the review list or to override a rule)."""
    preview = load_preview()
    for item in preview['items']:
        if item['track_id'] == track_id:
            item.update({'playlist': entry_id, 'also': [], 'status': 'manual', 'reason': 'chosen by hand'})
            if remember_artist and item['artist_id']:
                config_store.set_artist_rule(item['artist_id'], item['artists'][0], entry_id)
                # Apply the remembered choice to the artist's other pending tracks.
                for other in preview['items']:
                    if other['artist_id'] == item['artist_id'] and other['status'] == 'review':
                        other.update({'playlist': entry_id, 'status': 'auto', 'reason': 'remembered artist choice'})
            save_preview(preview)
            return item
    raise KeyError(track_id)


def apply_preview(sp):
    """Add every classified (auto or manual) track to its genre playlist(s)."""
    preview = load_preview()
    playlists = {p['id']: p for p in config_store.load_config()['playlists']}
    to_add = defaultdict(list)
    for item in preview['items']:
        if item['status'] in ('auto', 'manual'):
            for entry_id in [item['playlist'], *item.get('also', [])]:
                if entry_id in playlists:
                    to_add[entry_id].append(item)

    added = {}
    for entry_id, items in to_add.items():
        add_to_playlist(sp, playlists[entry_id]['playlist_id'], [i['track_id'] for i in items])
        for item in items:
            item['status'] = 'applied'
        added[playlists[entry_id]['name']] = len(items)
        save_preview(preview)
    return added


class Job:
    """Runs one task at a time in a background thread, with progress for the UI."""

    def __init__(self, target):
        self.target = target
        self.lock = threading.Lock()
        self.state = {'running': False}

    def start(self, sp, **kwargs):
        with self.lock:
            if self.state.get('running'):
                return False
            self.state = {'running': True, 'step': 'Starting', 'done': 0, 'total': 0, 'error': None}
        threading.Thread(target=self._run, args=(sp,), kwargs=kwargs, daemon=True).start()
        return True

    def _progress(self, **kw):
        self.state.update(kw)

    def _run(self, sp, **kwargs):
        try:
            self.target(sp, self._progress, **kwargs)
        except Exception as e:  # reported to the UI
            import requests
            if isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
                self.state['error'] = 'Spotify did not respond. Try again in a moment.'
            else:
                self.state['error'] = str(e)
        finally:
            self.state['running'] = False
