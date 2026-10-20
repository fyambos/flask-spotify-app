"""What the app sorted, kept on this computer, and how it is matched with Spotify.

For each "sort into" playlist (data/sort-state.json):
- added: songs the app sorted into it that are not on Spotify yet
- base: the songs Spotify had at the last sync (None before the first one)
- removed_by_hand: songs removed on Spotify by hand, never sorted into it again

The playlist, as the app sees it, is what Spotify (or the last imported file) has, plus
`added`. Without Spotify (no Premium, quota used up, imported file), sorting still works
for downloads, .m3u8 files and Apple Music, and `added` waits.

When Spotify can be written again, `plan_sync` compares the three states of each playlist:
- removed on Spotify since the last sync -> removed in the app too (the change by hand wins)
- added on Spotify by hand -> taken as is
- sorted in the app and not on Spotify -> to add on Spotify
Nothing is written before `push` (the "Sync with Spotify" screen). Without a base (first
connection), Spotify is the reference and what the app sorted is offered as additions.
"""
import json

import catalog as catalog_store
import config_store
from config_store import DATA_DIR

STATE_PATH = DATA_DIR / 'sort-state.json'
# Present while sorted songs wait for the "Sync with Spotify" screen.
WAITING_PATH = DATA_DIR / 'sort-waiting'
APP_PREFIX = 'app:'


def waiting():
    return WAITING_PATH.exists()


def set_waiting(value):
    if value:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        WAITING_PATH.touch()
    else:
        WAITING_PATH.unlink(missing_ok=True)


def load():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding='utf-8'))
    return {}


def save(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(STATE_PATH)


def _entry_state(state, entry_id):
    return state.setdefault(entry_id, {'added': [], 'base': None, 'removed_by_hand': []})


def playlist_key(entry):
    """The catalog id of a "sort into" playlist (app-only ones get app:<entry id>)."""
    return entry.get('playlist_id') or APP_PREFIX + entry['id']


def view(catalog, config=None, state=None):
    """The catalog with the songs sorted in the app, and the app-only playlists."""
    config = config or config_store.load_config()
    state = load() if state is None else state
    playlists = dict(catalog['playlists'])
    for entry in config['playlists']:
        key = playlist_key(entry)
        s = state.get(entry['id']) or {}
        remote = list((playlists.get(key) or {}).get('track_ids', []))
        added = [t for t in s.get('added', []) if t not in set(remote) and t in catalog['tracks']]
        if key in playlists or added or not entry.get('playlist_id'):
            playlists[key] = {**(playlists.get(key) or {'owned': True}), 'name': entry['name'],
                              'track_ids': remote + added}
    return {**catalog, 'playlists': playlists}


def record_sorted(items):
    """Remember sorted songs: items are (entry id, track id)."""
    state = load()
    for entry_id, track_id in items:
        s = _entry_state(state, entry_id)
        if track_id not in s['added']:
            s['added'].append(track_id)
        if track_id in s['removed_by_hand']:
            s['removed_by_hand'].remove(track_id)
    save(state)


def removed_by_hand(state=None):
    """{track id: [entry ids]} of the songs removed on Spotify by hand."""
    result = {}
    for entry_id, s in (load() if state is None else state).items():
        for track_id in s.get('removed_by_hand', []):
            result.setdefault(track_id, []).append(entry_id)
    return result


def plan_sync(catalog, config=None):
    """What a sync with Spotify would do, per playlist. Uses the playlists as Spotify has them now."""
    config = config or config_store.load_config()
    state = load()
    changes = []
    for entry in config['playlists']:
        s = state.get(entry['id']) or {}
        remote = set((catalog['playlists'].get(entry.get('playlist_id') or '') or {}).get('track_ids', []))
        base = set(s['base']) if s.get('base') is not None else None
        removed = sorted(base - remote) if base is not None else []
        to_add = [t for t in s.get('added', []) if t not in remote and t not in removed]
        create = not entry.get('playlist_id')
        if to_add or removed or (create and s.get('added')):
            changes.append({'entry_id': entry['id'], 'name': entry['name'], 'create': create,
                            'to_add': to_add, 'removed_on_spotify': removed})
    return changes


def pending_count(catalog, config=None):
    """Songs sorted in the app and not on Spotify yet."""
    return sum(len(c['to_add']) for c in plan_sync(catalog, config))


def push(sp, catalog, progress=None):
    """Write the sorted songs on Spotify (creating app-only playlists), then take Spotify as the new base."""
    from spotify_client import add_to_playlist, create_playlist

    progress = progress or (lambda **kw: None)
    config = config_store.load_config()
    state = load()
    changes = {c['entry_id']: c for c in plan_sync(catalog, config)}
    for i, entry in enumerate(config['playlists'], 1):
        s = _entry_state(state, entry['id'])
        change = changes.get(entry['id'])
        remote = list((catalog['playlists'].get(entry.get('playlist_id') or '') or {}).get('track_ids', []))
        if change:
            progress(step=f"Writing {entry['name']} on Spotify", done=i, total=len(config['playlists']))
            if change['create']:
                new_id = create_playlist(sp, entry['name'])
                _rename_playlist_id(config, entry, new_id)
            if change['to_add']:
                add_to_playlist(sp, entry['playlist_id'], change['to_add'])
            s['removed_by_hand'] = sorted(set(s['removed_by_hand']) | set(change['removed_on_spotify']))
            remote += change['to_add']
        s['added'] = []
        s['base'] = remote
        save(state)
    return list(changes.values())


def take_spotify_as_base(catalog, config=None):
    """After reading Spotify with nothing waiting: Spotify is the new base."""
    config = config or config_store.load_config()
    state = load()
    for entry in config['playlists']:
        if not entry.get('playlist_id') or entry['playlist_id'] not in catalog['playlists']:
            continue
        s = _entry_state(state, entry['id'])
        remote = catalog['playlists'][entry['playlist_id']]['track_ids']
        if s['base'] is not None:
            s['removed_by_hand'] = sorted(set(s['removed_by_hand']) | (set(s['base']) - set(remote)))
        s['base'] = list(remote)
    save(state)


def _rename_playlist_id(config, entry, new_id):
    """An app-only playlist now exists on Spotify: use its Spotify id everywhere."""
    old = playlist_key(entry)
    entry['playlist_id'] = new_id
    download = config['download']
    download['playlists'] = [new_id if p == old else p for p in download['playlists']]
    download['seen'] = [new_id if p == old else p for p in download.get('seen', [])]
    config['sort_from'] = [new_id if p == old else p for p in config.get('sort_from', [])]
    config['layout']['order'] = [new_id if p == old else p for p in config['layout'].get('order', [])]
    folders = config.get('playlist_folders') or {}
    if old in folders:
        folders[new_id] = folders.pop(old)
    config_store.save_config(config)


def catalog_view():
    return view(catalog_store.load())
