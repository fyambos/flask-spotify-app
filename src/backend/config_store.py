"""Local configuration storage (replaces Firestore).

The config lives in src/backend/data/config.json (ignored by git, one per machine).
Override the location with the SPOTSORT_DATA_DIR environment variable.
"""
import json
import os
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv('SPOTSORT_DATA_DIR', BACKEND_DIR / 'data')).expanduser()
CONFIG_PATH = DATA_DIR / 'config.json'
FIRESTORE_EXPORT_PATH = BACKEND_DIR / 'firestore-export.json'

DEFAULT_CONFIG = {
    'music_dir': '~/Music/Spotify',
    'audio_format': 'mp3',
    # Songs from your other playlists that are not in your Liked Songs.
    'non_liked': {'enabled': False, 'folder': 'Non-Liked Songs'},
    # Downloaded songs that are no longer in any synced playlist: keep, move or delete.
    'removed': {'mode': 'move', 'folder': '_Removed'},
    # cookies.txt exported from a browser logged in to YouTube Music Premium (256 kbps audio).
    'youtube_cookies': '',
    # Genre that unmatched tracks go to once you review them (must be one of the playlists).
    'fallback_genre': 'Other',
    # Use the genre playlists a track's artist is already in.
    'artist_history': {'enabled': True, 'min_share': 0.6},
    # Allow a song in several playlists: every playlist whose album/title keywords match,
    # plus its style playlist (artist history or genres). Downloads use the first one.
    'multi_playlist': False,
    # Manual choices remembered per artist: {artist_id: {'name': ..., 'playlist': entry id}}.
    'artist_rules': {},
    # Each entry: a local genre (folder name) linked to a Spotify playlist, with its rules.
    # The order of the list is the priority order.
    'playlists': [],
}

RULE_FIELDS = ('genre_names', 'exclude_genres', 'album_keywords', 'title_keywords')

# Local genre name for each Firestore document, recognised by its first keyword.
FIRESTORE_GENRE_NAMES = {
    'k-': 'Kr',
    'j-': 'Anime',
    'pop': 'BOP',
    'r&b': 'RnB & Indie',
    'video game music': 'Scorecore',
    'phonk': 'Phonk',
    'metal': 'Symphonic',
}


def _new_id():
    return uuid.uuid4().hex[:12]


def _migrate_from_firestore():
    export = json.loads(FIRESTORE_EXPORT_PATH.read_text(encoding='utf-8'))
    playlists = []
    for doc_id, doc in export.get('playlists', {}).items():
        data = doc['data']
        keywords = data.get('genre_names', [])
        name = FIRESTORE_GENRE_NAMES.get(keywords[0] if keywords else '', '')
        playlists.append({
            'id': doc_id,
            'name': name,
            'playlist_id': data['playlist_id'],
            'genre_names': keywords,
        })
    return playlists


def _normalize(config):
    config = {**DEFAULT_CONFIG, **config}
    for entry in config['playlists']:
        for field in RULE_FIELDS:
            entry.setdefault(field, [])
    return config


def load_config():
    if CONFIG_PATH.exists():
        return _normalize(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))

    config = dict(DEFAULT_CONFIG)
    if FIRESTORE_EXPORT_PATH.exists():
        config['playlists'] = _migrate_from_firestore()
    config = _normalize(config)
    save_config(config)
    return config


def save_config(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(CONFIG_PATH)


def add_playlist(name, playlist_id, genre_names, **rules):
    config = load_config()
    if any(p['playlist_id'] == playlist_id for p in config['playlists']):
        raise ValueError('This playlist has already been added!')
    entry = {'id': _new_id(), 'name': name, 'playlist_id': playlist_id, 'genre_names': genre_names}
    entry.update({f: rules.get(f, []) for f in RULE_FIELDS if f != 'genre_names'})
    config['playlists'].append(entry)
    save_config(config)
    return entry


def update_playlist(entry_id, changes):
    config = load_config()
    for entry in config['playlists']:
        if entry['id'] == entry_id:
            entry.update({k: v for k, v in changes.items() if k == 'name' or k in RULE_FIELDS})
            save_config(config)
            return entry
    raise KeyError(entry_id)


def delete_playlist(entry_id):
    config = load_config()
    config['playlists'] = [p for p in config['playlists'] if p['id'] != entry_id]
    save_config(config)


def reorder_playlists(entry_ids):
    config = load_config()
    by_id = {p['id']: p for p in config['playlists']}
    ordered = [by_id.pop(i) for i in entry_ids if i in by_id]
    config['playlists'] = ordered + list(by_id.values())
    save_config(config)
    return config


def set_artist_rule(artist_id, artist_name, entry_id):
    config = load_config()
    if entry_id:
        config['artist_rules'][artist_id] = {'name': artist_name, 'playlist': entry_id}
    else:
        config['artist_rules'].pop(artist_id, None)
    save_config(config)


def update_settings(changes):
    config = load_config()
    for key in ('music_dir', 'audio_format', 'fallback_genre', 'artist_history', 'multi_playlist', 'non_liked', 'removed', 'youtube_cookies'):
        if key in changes:
            config[key] = changes[key]
    save_config(config)
    return config
