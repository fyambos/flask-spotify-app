"""Local copy of your playlists: their songs, names and owners.

Everything else (downloads, sorting, Apple Music) reads this copy, so the app works the
same with the Spotify API (Premium) or with a file:
- Spotify API: read again at each Check, Sync or sort (playlist contents are cached by
  snapshot id, see spotify_client).
- TuneMyMusic CSV export (any streaming service), or the Spotify data export (zip).

Saved in data/catalog.json, the previous version in data/catalog-previous.json.

Tracks keep the shape of the Spotify API tracks (id, name, artists, album...). Tracks
from a file have what the file gives: no artist ids, no duration, no cover.
Playlists from a file have no id: the id of the playlist with the same name in the
previous catalog or the config is reused, else one is made from the name.
"""
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import config_store
from errors import AppError
from config_store import DATA_DIR

CATALOG_PATH = DATA_DIR / 'catalog.json'
PREVIOUS_PATH = DATA_DIR / 'catalog-previous.json'
LIKED_ID = 'liked'
SPOTIFY_ID = re.compile(r'[A-Za-z0-9]{22}')
LIKED_NAME = 'Liked Songs'
INVISIBLE = '⠀ㅤ​'
# TuneMyMusic exports 500 songs max from playlists of other users.
OTHER_USER_CAP = 500

TUNEMYMUSIC_HEADER = ['Track name', 'Artist name', 'Album', 'Playlist name', 'Type']
TUNEMYMUSIC_LIKED = 'Favorite'
EXPORTIFY_HEADER = ['Track URI', 'Track Name', 'Artist Name(s)', 'Duration (ms)']
FILE_SOURCES = ('tunemymusic', 'spotify-export', 'exportify')


def empty():
    return {'source': None, 'updated_at': None, 'file': None, 'playlists': {}, 'tracks': {}}


_loaded = {'stamp': None, 'data': None}  # 3.4 MB read by every page and the Downloads watch: once per change


def load():
    """The catalog, read again only when the file changed. Shared: change it only to save it with _save."""
    try:
        stat = CATALOG_PATH.stat()
    except OSError:
        return empty()
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _loaded['stamp'] != stamp:
        _loaded.update(stamp=stamp, data=json.loads(CATALOG_PATH.read_text(encoding='utf-8')))
    return _loaded['data']


def _unescape_names(track):
    """Some releases come with HTML entities in their names ('it&#039;s'): written as they read."""
    import html
    album = track.get('album') or {}
    for item in [track, album] + list(track.get('artists') or []) + list(album.get('artists') or []):
        if isinstance(item.get('name'), str) and '&' in item['name']:
            item['name'] = html.unescape(item['name'])


def _save(catalog, keep_previous):
    for track in catalog.get('tracks', {}).values():
        _unescape_names(track)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if keep_previous and CATALOG_PATH.exists():
        CATALOG_PATH.replace(PREVIOUS_PATH)
    tmp = CATALOG_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
    tmp.replace(CATALOG_PATH)
    stat = CATALOG_PATH.stat()
    _loaded.update(stamp=(stat.st_mtime_ns, stat.st_size), data=catalog)


def follows_spotify(catalog):
    """True when Spotify is read for these playlists as soon as it is connected: always, except for a
    file imported from another service (Deezer, Apple Music...), whose songs have no Spotify id."""
    if catalog.get('source') in (None, 'spotify'):
        return True
    ids = list(catalog.get('tracks', {}))
    return bool(ids) and sum(bool(SPOTIFY_ID.fullmatch(t)) for t in ids) * 2 >= len(ids)


def clean_name(name):
    return (name or '').strip(f' \t{INVISIBLE}') or name or ''


def tracks_of(catalog, playlist_id):
    """The songs of a playlist, as track dicts, in playlist order."""
    playlist = catalog['playlists'].get(playlist_id)
    if not playlist:
        return []
    return [catalog['tracks'][t] for t in playlist['track_ids'] if t in catalog['tracks']]


def read_playlist(sp, catalog, playlist_id):
    """Songs of a playlist, read from Spotify when the catalog only has its size (not downloaded nor sorted)."""
    playlist = catalog['playlists'].get(playlist_id) or {}
    if catalog.get('source') == 'spotify' and playlist.get('total', 0) > len(playlist.get('track_ids', [])):
        from spotify_client import playlist_tracks
        items = playlist_tracks(sp, playlist_id)
        for t in items:
            catalog['tracks'].setdefault(t['id'], t)
        playlist['track_ids'] = [t['id'] for t in items]
        stored = load()
        if playlist_id in stored['playlists']:
            stored['playlists'][playlist_id]['track_ids'] = playlist['track_ids']
            stored['tracks'].update({t['id']: t for t in items})
            _save(stored, keep_previous=False)
    return tracks_of(catalog, playlist_id)


def maybe_incomplete(playlist):
    """A playlist from a file with exactly 500 songs: probably cut by TuneMyMusic."""
    return playlist.get('owned') is None and len(playlist['track_ids']) == OTHER_USER_CAP


# --- From the Spotify API ---

def refresh_from_spotify(sp, progress=None):
    """Read Liked Songs and every playlist of your library. Returns the catalog."""
    from spotify_client import SpotifyLimitError, liked_tracks, my_playlists, playlist_tracks, remember_snapshots
    from spotify_client import me as spotify_me

    progress = progress or (lambda **kw: None)
    old = load()
    progress(step='Reading your Liked Songs')
    liked = liked_tracks(sp)
    tracks = {t['id']: _without_date(t) for t in liked}
    playlists = {LIKED_ID: {'name': LIKED_NAME, 'owned': True, 'track_ids': [t['id'] for t in liked],
                            'added': [t.get('added_at') for t in liked]}}

    me = spotify_me(sp)['id']
    listing = my_playlists(sp)
    remember_snapshots(listing)
    # Only the playlists that are downloaded or sorted are read song by song: the others only need
    # their name and size, which the listing gives (fewer requests, Spotify has a daily quota).
    config = config_store.load_config()
    all_mine = config['download']['mode'] == 'all'
    used = set(config['download'].get('playlists') or []) | set(config.get('sort_from') or []) \
        | {e.get('playlist_id') for e in config['playlists']}
    unreadable = []  # downloaded or sorted playlists Spotify did not give this time
    for i, p in enumerate(listing, 1):
        name = clean_name(p['name'])
        owned = (p.get('owner') or {}).get('id') == me or bool(p.get('collaborative'))
        if p['id'] not in used and not (all_mine and owned):
            items = tracks_of(old, p['id'])
            total = (p.get('items') or p.get('tracks') or {}).get('total', len(items))
        else:
            progress(step=f'Reading {name}', done=i, total=len(listing))
            try:
                items = playlist_tracks(sp, p['id'])
            except SpotifyLimitError:
                raise  # the last copy is used until the end of the block
            except Exception:
                # Not read this time (network, not allowed): what was read before is kept, and nothing
                # of it counts as removed (a playlist taken for empty would send its songs to _Removed).
                items = tracks_of(old, p['id'])
                unreadable.append(name)
            total = len(items)
        for t in items:
            tracks.setdefault(t['id'], _without_date(t))
        # When each song was added (Stats): from Spotify, else as read before.
        added = [t.get('added_at') for t in items] if any(t.get('added_at') for t in items) \
            else (old.get('playlists', {}).get(p['id']) or {}).get('added')
        images = p.get('images') or []
        playlists[p['id']] = {'name': name, 'owned': owned, 'track_ids': [t['id'] for t in items], 'added': added,
                              'owner': (p.get('owner') or {}).get('display_name'),
                              'image_url': images[0]['url'] if images else None, 'total': total}

    catalog = {'source': 'spotify', 'updated_at': _now(), 'file': None, 'playlists': playlists, 'tracks': tracks}
    if unreadable:
        catalog.update(partial=True, unreadable=unreadable)
    _save(catalog, keep_previous=old.get('source') != 'spotify')
    return catalog


def _without_date(track):
    """A song as the catalog keeps it: its date of addition belongs to each playlist ('added')."""
    return {k: v for k, v in track.items() if k != 'added_at'}


def from_last_check():
    """First catalog from what was read before it existed (last library check + Spotify cache), without
    sending anything to Spotify. Returns None when there is nothing to start from."""
    plan_path, cache_path = DATA_DIR / 'library-plan.json', DATA_DIR / 'cache' / 'spotify.json'
    if CATALOG_PATH.exists() or not plan_path.exists():
        return None
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    tracks = {}
    for t in (cache.get('liked') or {}).get('tracks', []):
        tracks[t['id']] = t
    for entry in cache.get('playlists', {}).values():
        for t in entry.get('tracks', []):
            tracks.setdefault(t['id'], t)
    # Without the cache: the songs the last check described (read again from Spotify at the next check).
    for tid, info in plan.get('info', {}).items():
        if tid not in tracks:
            artists = [{'id': info.get('artist_id') if i == 0 else None, 'name': a} for i, a in enumerate(info['artists'])]
            tracks[tid] = {
                'id': tid, 'name': info['title'], 'artists': artists,
                'album': {'id': None, 'name': info.get('album'), 'images': [{'url': info['image_url']}] if info.get('image_url') else [],
                          'release_date': None, 'total_tracks': None, 'album_type': None, 'artists': []},
                'duration_ms': (info.get('duration') or 0) * 1000, 'track_number': None, 'disc_number': None,
                'explicit': None, 'external_urls': {}, 'external_ids': {},
            }
    playlists = {}
    for pid, p in plan.get('playlists', {}).items():
        ids = [t for t in p['track_ids'] if t in tracks]
        playlists[pid] = {'name': clean_name(p['name']), 'owned': True, 'track_ids': ids}
    # partial: some songs may be missing, so nothing is treated as removed until Spotify is read again.
    catalog = {'source': 'spotify', 'updated_at': plan.get('generated_at') or _now(), 'file': None,
               'playlists': playlists, 'tracks': tracks, 'partial': True}
    _save(catalog, keep_previous=False)
    return catalog


# --- From a file ---

def detect(path):
    """'tunemymusic', 'spotify-export', 'exportify' or None."""
    path = Path(path)
    try:
        if path.suffix.lower() == '.csv':
            with open(path, encoding='utf-8-sig', newline='') as f:
                header = next(csv.reader(f), [])
            if all(h in header for h in TUNEMYMUSIC_HEADER):
                return 'tunemymusic'
            return 'exportify' if all(h in header for h in EXPORTIFY_HEADER) else None
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if any(n.endswith('YourLibrary.json') for n in names) or any(re.search(r'Playlist\d*\.json$', n) for n in names):
                    return 'spotify-export'
                csvs = [n for n in names if n.lower().endswith('.csv')]
                if csvs:
                    with z.open(csvs[0]) as f:
                        header = next(csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig')), [])
                    return 'exportify' if all(h in header for h in EXPORTIFY_HEADER) else None
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, csv.Error):
        return None
    return None


def import_file(path):
    """Replace the catalog with the playlists of an exported file. Returns a summary of the changes."""
    kind = detect(path)
    if kind == 'tunemymusic':
        playlists, tracks = _read_tunemymusic(path)
    elif kind == 'spotify-export':
        playlists, tracks = _read_spotify_export(path)
    elif kind == 'exportify':
        playlists, tracks = _read_exportify(path)
    else:
        raise AppError('not_an_export')

    old = load()
    playlists = _reuse_ids(playlists, old)
    save_extras(tracks)
    tracks = _known_details(tracks, old)
    catalog = {'source': kind, 'updated_at': _now(), 'file': Path(path).name, 'playlists': playlists, 'tracks': tracks}
    _save(catalog, keep_previous=True)
    return {'kind': kind, 'file': Path(path).name, **compare(old, catalog)}


def _track_id(spotify_id, isrc, artist, title):
    if spotify_id:
        return spotify_id
    if isrc:
        return f'isrc:{isrc.upper()}'
    key = f'{artist.lower().strip()}|{title.lower().strip()}'
    return 'local:' + hashlib.sha1(key.encode()).hexdigest()[:16]


def _file_track(track_id, title, artist, album, isrc):
    return {
        'id': track_id, 'name': title,
        'artists': [{'id': None, 'name': artist}] if artist else [],
        'album': {'id': None, 'name': album, 'images': [], 'release_date': None, 'total_tracks': None,
                  'album_type': None, 'artists': []},
        'duration_ms': None, 'track_number': None, 'disc_number': None, 'explicit': None,
        'external_urls': {'spotify': f'https://open.spotify.com/track/{track_id}'} if ':' not in track_id else {},
        'external_ids': {'isrc': isrc} if isrc else {},
    }


def _read_tunemymusic(path):
    playlists, tracks = {}, {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            kind = row.get('Type') or ''
            if kind not in ('Playlist', TUNEMYMUSIC_LIKED):
                continue  # 'Artist': followed artists
            title, artist = row.get('Track name') or '', row.get('Artist name') or ''
            if not title:
                continue
            spotify_id = (row.get('Spotify - id') or '').strip()
            isrc = (row.get('ISRC') or '').strip()
            tid = _track_id(spotify_id, isrc, artist, title)
            tracks.setdefault(tid, _file_track(tid, title, artist, row.get('Album') or '', isrc))
            key = LIKED_ID if kind == TUNEMYMUSIC_LIKED else 'name:' + clean_name(row.get('Playlist name') or '')
            name = LIKED_NAME if kind == TUNEMYMUSIC_LIKED else clean_name(row.get('Playlist name') or '')
            playlist = playlists.setdefault(key, {'name': name, 'owned': True if key == LIKED_ID else None, 'track_ids': []})
            if tid not in playlist['track_ids']:
                playlist['track_ids'].append(tid)
    return playlists, tracks


def _uri_id(uri):
    match = re.match(r'spotify:track:([A-Za-z0-9]{22})$', uri or '')
    return match.group(1) if match else None


def _read_spotify_export(path):
    playlists, tracks = {}, {}

    def add(key, name, owned, title, artist, album, uri, added=None):
        if not title:
            return
        tid = _track_id(_uri_id(uri), None, artist or '', title)
        tracks.setdefault(tid, _file_track(tid, title, artist or '', album or '', None))
        playlist = playlists.setdefault(key, {'name': name, 'owned': owned, 'track_ids': [], 'added': []})
        if tid not in playlist['track_ids']:
            playlist['track_ids'].append(tid)
            playlist['added'].append(added)

    listened = []  # the listening history the export may include (Stats)

    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            base = member.rsplit('/', 1)[-1]
            if base == 'YourLibrary.json':
                data = json.loads(z.read(member).decode('utf-8'))
                for t in data.get('tracks', []):
                    add(LIKED_ID, LIKED_NAME, True, t.get('track'), t.get('artist'), t.get('album'), t.get('uri'))
            elif re.match(r'Playlist\d*\.json$', base):
                data = json.loads(z.read(member).decode('utf-8'))
                for p in data.get('playlists', []):
                    name = clean_name(p.get('name') or '')
                    for item in p.get('items', []):
                        t = item.get('track') or {}
                        add('name:' + name, name, True, t.get('trackName'), t.get('artistName'),
                            t.get('albumName'), t.get('trackUri'), item.get('addedDate'))
            elif re.match(r'(Streaming_History_Audio|StreamingHistory_music|StreamingHistory)\S*\.json$', base):
                for e in json.loads(z.read(member).decode('utf-8')):
                    # Account data: endTime, artistName, trackName, msPlayed. Extended history: ts,
                    # master_metadata_album_artist_name, master_metadata_track_name, ms_played.
                    artist = e.get('artistName') or e.get('master_metadata_album_artist_name')
                    title = e.get('trackName') or e.get('master_metadata_track_name')
                    if artist and title:
                        listened.append({'at': e.get('endTime') or e.get('ts'), 'artist': artist, 'title': title,
                                         'ms': e.get('msPlayed') or e.get('ms_played') or 0})
    if listened:
        LISTENING_PATH.write_text(json.dumps(listened, ensure_ascii=False), encoding='utf-8')
    return playlists, tracks


def _known_details(tracks, old):
    """Songs already read from Spotify keep what the file lacks (album artist, length, cover): their
    files stay in the same folder whether the playlists come from Spotify or from a file."""
    from spotify_client import CACHE_PATH
    known = {t: v for t, v in old.get('tracks', {}).items() if (v.get('album') or {}).get('artists')}
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    for entry in [cache.get('liked') or {}] + list((cache.get('playlists') or {}).values()):
        for t in entry.get('tracks') or []:
            if (t.get('album') or {}).get('artists'):
                known.setdefault(t['id'], t)
    kept = ('popularity', 'genres', 'features')  # what a file can have that Spotify no longer gives
    return {tid: {**known[tid], **{k: track[k] for k in kept if track.get(k)}} if tid in known else track
            for tid, track in tracks.items()}


def _read_exportify(path):
    """Exportify: one CSV per playlist (a zip of them, or one CSV), named after the playlist."""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            files = {n: z.read(n).decode('utf-8-sig') for n in z.namelist() if n.lower().endswith('.csv')}
    else:
        files = {path.name: path.read_text(encoding='utf-8-sig')}
    rows = {n: list(csv.DictReader(io.StringIO(text))) for n, text in files.items()}
    # Liked Songs are all added by you: that gives your account, to know the playlists of other users.
    me = Counter(r.get('Added By') for r in rows.get('Liked_Songs.csv', []) if r.get('Added By')).most_common(1)
    me = me[0][0] if me else None
    playlists, tracks = {}, {}
    for name, items in rows.items():
        if name == 'Saved_Albums.csv':
            continue  # albums, not a playlist
        title = Path(name).stem.replace('_', ' ')
        key = LIKED_ID if name == 'Liked_Songs.csv' else 'name:' + clean_name(title)
        added_by = {r.get('Added By') for r in items if r.get('Added By')}
        owned = True if key == LIKED_ID or (me and me in added_by) else (False if me and added_by else None)
        playlist = playlists.setdefault(key, {'name': LIKED_NAME if key == LIKED_ID else clean_name(title),
                                              'owned': owned, 'track_ids': [], 'added': []})
        for r in items:
            tid = _uri_id(r.get('Track URI'))
            if not tid or not r.get('Track Name'):
                continue  # episodes and local files
            artists = [a for a in (r.get('Artist Name(s)') or '').split(';') if a]
            track = _file_track(tid, r['Track Name'], artists[0] if artists else '', r.get('Album Name') or '',
                                r.get('ISRC') or None)
            track['artists'] = [{'id': None, 'name': a} for a in artists]
            track['duration_ms'] = int(r['Duration (ms)']) if (r.get('Duration (ms)') or '').isdigit() else None
            track['album']['release_date'] = r.get('Release Date') or None
            # For Stats: Exportify still has what Spotify no longer gives to new apps.
            track['popularity'] = int(r['Popularity']) if (r.get('Popularity') or '').isdigit() else None
            track['genres'] = [g for g in (r.get('Genres') or '').split(',') if g]
            track['features'] = _features(r)
            tracks.setdefault(tid, track)
            playlist['track_ids'].append(tid)  # a song twice in a playlist stays twice, as on Spotify
            playlist['added'].append(r.get('Added At') or None)
    return playlists, tracks


EXTRAS_PATH = DATA_DIR / 'track-extras.json'
LISTENING_PATH = DATA_DIR / 'listening-history.json'  # from the Spotify data export, when it has it


def save_extras(tracks):
    """Genres, mood and popularity from an export (Exportify), kept apart: Stats uses them even when the
    playlists are read from Spotify again, which no longer gives them."""
    extras = load_extras()
    for tid, track in tracks.items():
        found = {k: track[k] for k in ('popularity', 'genres', 'features') if track.get(k)}
        if found:
            extras[tid] = {**extras.get(tid, {}), **found}
    if extras:
        EXTRAS_PATH.write_text(json.dumps(extras, ensure_ascii=False), encoding='utf-8')


def load_extras():
    try:
        return json.loads(EXTRAS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


FEATURES = {'danceability': 'Danceability', 'energy': 'Energy', 'valence': 'Valence', 'tempo': 'Tempo',
            'acousticness': 'Acousticness', 'instrumentalness': 'Instrumentalness', 'mode': 'Mode', 'key': 'Key'}


def _features(row):
    """Spotify's audio features of a song (mood, energy, tempo...) from an Exportify row, None without them."""
    values = {}
    for key, column in FEATURES.items():
        try:
            values[key] = float(row[column])
        except (KeyError, TypeError, ValueError):
            pass
    return values or None


def _reuse_ids(playlists, old):
    """Give each playlist read from a file the id it had before (same name)."""
    known, loose = {}, {}
    for pid, p in old.get('playlists', {}).items():
        known.setdefault(_name_key(p['name']), pid)
        loose.setdefault(_loose_key(p['name']), (pid, p['name']))
    for entry in config_store.load_config()['playlists']:
        if entry.get('playlist_id'):
            known.setdefault(_name_key(entry['name']), entry['playlist_id'])
    result = {}
    for key, playlist in playlists.items():
        if key == LIKED_ID:
            result[LIKED_ID] = playlist
            continue
        pid = known.get(_name_key(playlist['name']))
        if not pid and _loose_key(playlist['name']) in loose:
            # 'Lofi Girl - beats to relaxstudy to' (file name) = 'Lofi Girl - beats to relax/study to'
            pid, playlist['name'] = loose[_loose_key(playlist['name'])]
        pid = pid or 'file:' + hashlib.sha1(_name_key(playlist['name']).encode()).hexdigest()[:12]
        if pid in result:  # two playlists with the same name: the second is '<id>-2' at every import
            n = 2
            while f'{pid}-{n}' in result:
                n += 1
            pid = f'{pid}-{n}'
        if pid in old.get('playlists', {}) and old['playlists'][pid].get('owned') is not None:
            playlist['owned'] = old['playlists'][pid]['owned']
        result[pid] = playlist
    return result


def _loose_key(name):
    return re.sub(r'[\W_]+', '', clean_name(name).lower())


def _name_key(name):
    return re.sub(r'\s+', ' ', clean_name(name).lower())


def compare(old, new):
    """Songs added and removed, and playlists added and removed, between two catalogs."""
    old_ids = {t for p in old.get('playlists', {}).values() for t in p['track_ids']}
    new_ids = {t for p in new['playlists'].values() for t in p['track_ids']}
    return {
        'songs': len(new_ids),
        'playlists': len(new['playlists']),
        'songs_added': len(new_ids - old_ids) if old.get('source') else 0,
        'songs_removed': len(old_ids - new_ids) if old.get('source') else 0,
        'playlists_added': [new['playlists'][p]['name'] for p in new['playlists'].keys() - old.get('playlists', {}).keys()]
        if old.get('source') else [],
    }


def _now():
    return datetime.now().isoformat(timespec='seconds')


def summary(catalog=None):
    catalog = catalog or load()
    return {
        'source': catalog['source'],
        'updated_at': catalog['updated_at'],
        'file': catalog['file'],
        'playlists': [
            {'id': pid, 'name': p['name'], 'owned': p.get('owned'), 'track_count': p.get('total') or len(p['track_ids']),
             'image_url': p.get('image_url'), 'maybe_incomplete': maybe_incomplete(p)}
            for pid, p in catalog['playlists'].items()
        ],
    }
