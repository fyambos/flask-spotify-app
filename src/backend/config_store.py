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

DEFAULT_CONFIG = {
    # The system Music folder (~/Music on macOS, C:\\Users\\<name>\\Music on Windows).
    'music_dir': '~/Music',
    'audio_format': 'mp3',
    # Which playlists are downloaded: 'all' (your playlists and Liked Songs) or 'selected'
    # (the ids in 'playlists'). 'seen': playlists already shown, the others are "New".
    'download': {'mode': 'all', 'playlists': [], 'seen': []},
    # Where files go, inside <music_dir>/<folder>/:
    # 'artist_album' <album artist>/<album>/, 'artist' <album artist>/, 'one_folder' (all together),
    # 'first_playlist' <first playlist of the song in 'order'>/.
    'layout': {'preset': 'artist_album', 'folder': 'Music Sorter', 'order': []},
    # Downloaded songs that are no longer in any downloaded playlist: keep, move or delete.
    'removed': {'mode': 'move', 'folder': '_Removed'},
    # Playlists sorted into the "sort into" playlists ('liked' is Liked Songs).
    'sort_from': ['liked'],
    # Without Spotify: show a reminder when the last import is more than a week old.
    'import_reminder': True,
    # cookies.txt exported from a browser logged in to YouTube Music Premium (256 kbps audio).
    'youtube_cookies': '',
    # macOS: update Apple Music at the end of each library sync.
    'apple_music_auto': True,
    # Folder of each playlist ({spotify playlist id: folder name}), used for Apple Music and
    # for the .m3u8 files. The Spotify Web API does not give playlist folders, so they are set here.
    'playlist_folders': {},
    # Folder of the playlists that have none.
    'default_folder': 'Music Sorter',
    # Folders in display order (also keeps folders that have no playlist yet).
    'folders': [],
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

def _new_id():
    return uuid.uuid4().hex[:12]


def _normalize(config):
    if 'apple_folders' in config:  # renamed
        config.setdefault('playlist_folders', config.pop('apple_folders'))
    if 'download' not in config and 'enabled' in config.get('non_liked', {}):  # replaced by 'download'
        config['download'] = {'mode': 'all' if config['non_liked']['enabled'] else 'selected', 'playlists': []}
    non_liked = config.pop('non_liked', None)
    download = config.get('download')
    if download and download.get('mode') == 'liked':  # "Liked Songs only" is gone
        download.update(mode='selected', playlists=['liked'])
    elif download and download.get('mode') == 'selected' and non_liked is not None:
        # The sorting playlists used to be always downloaded: keep them checked.
        ids = [p['playlist_id'] for p in config.get('playlists', []) if p.get('playlist_id')]
        download['playlists'] = list(dict.fromkeys(ids + ['liked'] + download.get('playlists', [])))
    if download is not None:
        download.setdefault('seen', [])
    config = {**DEFAULT_CONFIG, **config}
    config['layout'] = {**DEFAULT_CONFIG['layout'], **config['layout']}
    for entry in config['playlists']:
        for field in RULE_FIELDS:
            entry.setdefault(field, [])
    return config


def load_config():
    if CONFIG_PATH.exists():
        return _normalize(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))

    config = _normalize(dict(DEFAULT_CONFIG))
    save_config(config)
    return config


def save_config(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(CONFIG_PATH)


def add_playlist(name, playlist_id, genre_names, **rules):
    """A "sort into" playlist. playlist_id None: a playlist that only exists in the app for now."""
    config = load_config()
    if playlist_id and any(p['playlist_id'] == playlist_id for p in config['playlists']):
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
    for key in ('music_dir', 'audio_format', 'fallback_genre', 'artist_history', 'multi_playlist', 'download', 'layout',
                'removed', 'sort_from', 'import_reminder', 'youtube_cookies', 'apple_music_auto', 'playlist_folders',
                'default_folder', 'folders'):
        if key in changes:
            config[key] = changes[key]
    save_config(config)
    return config
