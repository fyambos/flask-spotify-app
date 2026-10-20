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
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

import config_store
from config_store import DATA_DIR

CATALOG_PATH = DATA_DIR / 'catalog.json'
PREVIOUS_PATH = DATA_DIR / 'catalog-previous.json'
LIKED_ID = 'liked'
LIKED_NAME = 'Liked Songs'
INVISIBLE = '⠀ㅤ​'
# TuneMyMusic exports 500 songs max from playlists of other users.
OTHER_USER_CAP = 500

TUNEMYMUSIC_HEADER = ['Track name', 'Artist name', 'Album', 'Playlist name', 'Type']
TUNEMYMUSIC_LIKED = 'Favorite'


def empty():
    return {'source': None, 'updated_at': None, 'file': None, 'playlists': {}, 'tracks': {}}


def load():
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    return empty()


def _save(catalog, keep_previous):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if keep_previous and CATALOG_PATH.exists():
        CATALOG_PATH.replace(PREVIOUS_PATH)
    tmp = CATALOG_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
    tmp.replace(CATALOG_PATH)


def clean_name(name):
    return (name or '').strip(f' \t{INVISIBLE}') or name or ''


def tracks_of(catalog, playlist_id):
    """The songs of a playlist, as track dicts, in playlist order."""
    playlist = catalog['playlists'].get(playlist_id)
    if not playlist:
        return []
    return [catalog['tracks'][t] for t in playlist['track_ids'] if t in catalog['tracks']]


def maybe_incomplete(playlist):
    """A playlist from a file with exactly 500 songs: probably cut by TuneMyMusic."""
    return playlist.get('owned') is None and len(playlist['track_ids']) == OTHER_USER_CAP


# --- From the Spotify API ---

def refresh_from_spotify(sp, progress=None):
    """Read Liked Songs and every playlist of your library. Returns the catalog."""
    from spotify_client import liked_tracks, my_playlists, playlist_tracks

    progress = progress or (lambda **kw: None)
    old = load()
    progress(step='Reading your Liked Songs')
    liked = liked_tracks(sp)
    tracks = {t['id']: t for t in liked}
    playlists = {LIKED_ID: {'name': LIKED_NAME, 'owned': True, 'track_ids': [t['id'] for t in liked]}}

    me = sp.me()['id']
    listing = my_playlists(sp)
    for i, p in enumerate(listing, 1):
        name = clean_name(p['name'])
        progress(step=f'Reading {name}', done=i, total=len(listing))
        owned = (p.get('owner') or {}).get('id') == me or bool(p.get('collaborative'))
        try:
            items = playlist_tracks(sp, p['id'])
        except Exception:
            # Unreadable (removed, or not allowed): keep what was read before.
            items = tracks_of(old, p['id'])
        for t in items:
            tracks.setdefault(t['id'], t)
        images = p.get('images') or []
        playlists[p['id']] = {'name': name, 'owned': owned, 'track_ids': [t['id'] for t in items],
                              'owner': (p.get('owner') or {}).get('display_name'),
                              'image_url': images[0]['url'] if images else None}

    catalog = {'source': 'spotify', 'updated_at': _now(), 'file': None, 'playlists': playlists, 'tracks': tracks}
    _save(catalog, keep_previous=old.get('source') != 'spotify')
    return catalog


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
    """'tunemymusic', 'spotify-export' or None."""
    path = Path(path)
    try:
        if path.suffix.lower() == '.csv':
            with open(path, encoding='utf-8-sig', newline='') as f:
                header = next(csv.reader(f), [])
            return 'tunemymusic' if all(h in header for h in TUNEMYMUSIC_HEADER) else None
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
            if any(n.endswith('YourLibrary.json') for n in names) or any(re.search(r'Playlist\d*\.json$', n) for n in names):
                return 'spotify-export'
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
    else:
        raise ValueError('This file is not a TuneMyMusic CSV export or a Spotify data export.')

    old = load()
    playlists = _reuse_ids(playlists, old)
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

    def add(key, name, owned, title, artist, album, uri):
        if not title:
            return
        tid = _track_id(_uri_id(uri), None, artist or '', title)
        tracks.setdefault(tid, _file_track(tid, title, artist or '', album or '', None))
        playlist = playlists.setdefault(key, {'name': name, 'owned': owned, 'track_ids': []})
        if tid not in playlist['track_ids']:
            playlist['track_ids'].append(tid)

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
                            t.get('albumName'), t.get('trackUri'))
    return playlists, tracks


def _reuse_ids(playlists, old):
    """Give each playlist read from a file the id it had before (same name)."""
    known = {}
    for pid, p in old.get('playlists', {}).items():
        known.setdefault(_name_key(p['name']), pid)
    for entry in config_store.load_config()['playlists']:
        if entry.get('playlist_id'):
            known.setdefault(_name_key(entry['name']), entry['playlist_id'])
    result = {}
    for key, playlist in playlists.items():
        if key == LIKED_ID:
            result[LIKED_ID] = playlist
            continue
        pid = known.get(_name_key(playlist['name'])) or 'file:' + hashlib.sha1(_name_key(playlist['name']).encode()).hexdigest()[:12]
        if pid in result:  # two playlists with the same name
            pid = f'{pid}-{len(result)}'
        if pid in old.get('playlists', {}) and old['playlists'][pid].get('owned') is not None:
            playlist['owned'] = old['playlists'][pid]['owned']
        result[pid] = playlist
    return result


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
            {'id': pid, 'name': p['name'], 'owned': p.get('owned'), 'track_count': len(p['track_ids']),
             'image_url': p.get('image_url'), 'maybe_incomplete': maybe_incomplete(p)}
            for pid, p in catalog['playlists'].items()
        ],
    }
