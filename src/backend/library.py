"""Local copy of your playlists as music files.

- The downloaded playlists (Settings > Playlists to download) are all your playlists and
  Liked Songs, or the ones you choose. Sorting has no effect on what is downloaded.
- Each song is downloaded once, into <music_dir>/<layout folder>/ following Settings >
  File layout (album artist / album by default). A song in several playlists has one file.
- Every downloaded playlist is written as an .m3u8 file in <layout folder>/Playlists/.
- The playlists are the reference: a song no longer in any downloaded playlist is kept,
  moved to the removed folder or deleted. Changing the layout moves the files at the next
  Sync, they are never downloaded again.

The playlists come from catalog.py (the Spotify API, or an imported file). Audio comes
from YouTube Music through spotdl, using the metadata we already have (spotdl's own
Spotify access is never used).
"""
import json
import os
import re
import shlex
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import catalog as catalog_store
import config_store
import sort_state
from errors import AppError, log
from config_store import DATA_DIR

LIBRARY_PATH = DATA_DIR / 'library.json'
IMPORTED_PATH = DATA_DIR / 'playlists-import.json'  # changes found by the last playlists file import
PLAN_PATH = DATA_DIR / 'library-plan.json'
PLAYLISTS_FOLDER = 'Playlists'
LIKED_PLAYLIST_ID = catalog_store.LIKED_ID
LIKED_PLAYLIST_NAME = catalog_store.LIKED_NAME
VARIOUS_ARTISTS = 'Various Artists'
FILE_TEMPLATE = '{artists} - {title}.{output-ext}'
FILE_TEMPLATE_WITH_ALBUM = '{artists} - {title} ({album}).{output-ext}'
INVISIBLE = catalog_store.INVISIBLE
LAYOUTS = ('artist_album', 'artist', 'one_folder', 'first_playlist')


def music_root(config):
    return Path(os.path.expanduser(config['music_dir']))


WINDOWS_RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
MAX_NAME = 120  # characters per folder or file name, to stay far from the 260 characters of a Windows path


def safe_name(name):
    """A name usable as a file or folder name on macOS, Windows and Android."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', ' ', name or '')
    name = re.sub(r'\s+', ' ', name)[:MAX_NAME]
    # Windows drops trailing dots and spaces ("R.E.M." would become "R.E.M").
    name = name.strip(f' .\t{INVISIBLE}') or 'Untitled'
    if name.split('.')[0].strip().lower() in WINDOWS_RESERVED:
        name = f'{name}_'
    return name


def load_library():
    if LIBRARY_PATH.exists():
        library = json.loads(LIBRARY_PATH.read_text(encoding='utf-8'))
    else:
        library = {'tracks': {}, 'playlists': {}}
    for record in library['tracks'].values():
        if record.get('error') and ' ' in record['error']:
            record['error'] = _legacy_error(record['error'])
    if 'root' not in library:
        # Paths are relative to the music folder they were downloaded to. Saved right away, so a
        # change of the music folder in Settings can't be taken for the folder the files are in.
        library['root'] = str(music_root(config_store.load_config()))
        if LIBRARY_PATH.exists():
            save_library(library)
    return library


def _legacy_error(text):
    """Not found reasons saved as sentences before they were codes."""
    text = text.lower()
    for words, code in (('not found on youtube', 'not_found'), ("doesn't give this video", 'unavailable'),
                        ('did not respond', 'not_reached'), ('wrong version', 'wrong_version'),
                        ('file not found', 'file_missing')):
        if words in text:
            return code
    return 'download_failed'


def save_library(library):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIBRARY_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(library, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(LIBRARY_PATH)


def load_plan():
    if PLAN_PATH.exists():
        return json.loads(PLAN_PATH.read_text(encoding='utf-8'))
    return None


def _track_info(track):
    return {
        'title': track['name'],
        'artists': [a['name'] for a in track['artists']],
        'album': (track.get('album') or {}).get('name', ''),
        'duration': round((track.get('duration_ms') or 0) / 1000),
        'image_url': ((track.get('album') or {}).get('images') or [{}])[-1].get('url'),
        'artist_id': track['artists'][0].get('id') if track['artists'] else None,
    }


# --- Which playlists, and where each file goes ---

def downloaded_playlists(config, catalog):
    """Ids of the downloaded playlists, in catalog order."""
    download = config['download']
    if download['mode'] == 'all':
        # Playlists of other users are left out (unknown owner, from a file: included).
        return [pid for pid, p in catalog['playlists'].items() if p.get('owned') is not False]
    chosen = set(download.get('playlists') or [])
    return [pid for pid in catalog['playlists'] if pid in chosen]


def layout_base(config):
    return safe_name(config['layout'].get('folder') or 'Music Sorter')


def album_artist(track):
    album = track.get('album') or {}
    if album.get('album_type') == 'compilation':
        return VARIOUS_ARTISTS
    artists = album.get('artists') or track.get('artists') or []
    return artists[0]['name'] if artists and artists[0].get('name') else 'Unknown Artist'


def track_folder(config, track, playlist_names):
    """Folder of a song, relative to the music folder. playlist_names: its downloaded playlists, in layout order."""
    base = layout_base(config)
    preset = config['layout'].get('preset')
    if preset == 'one_folder':
        return base
    if preset == 'first_playlist':
        return f'{base}/{safe_name(playlist_names[0])}' if playlist_names else base
    artist = safe_name(album_artist(track))
    if preset == 'artist':
        return f'{base}/{artist}'
    album = safe_name((track.get('album') or {}).get('name') or track['name'])
    return f'{base}/{artist}/{album}'


def _ordered(config, playlist_ids):
    """Playlists in the order of Settings > File layout (the others after, in catalog order)."""
    order = {pid: i for i, pid in enumerate(config['layout'].get('order') or [])}
    return sorted(playlist_ids, key=lambda pid: order.get(pid, len(order)))


def removed_folder(config):
    return f"{layout_base(config)}/{safe_name(config['removed']['folder'])}"


# --- The same song under several Spotify ids (single and album...) ---

TWIN_DURATION_GAP = 5  # seconds: the same recording released twice has the same length


# Words that make a different recording: a title part with one of them is never dropped.
VERSION_WORDS = re.compile(r'\b(live|remix|mix|acoustic|instrumental|inst|slowed|sped ?up|speed ?up|reverb|8d|nightcore|'
                           r'cover|demo|extended|karaoke|piano|orchestral|epic|lofi|lo-fi|bass ?boosted|ver|version|'
                           r'korean|chinese|japanese|english|spanish|french|edit)\b', re.IGNORECASE)
# Words that only name an edition of the same recording (and featured artists).
EDITION_WORDS = re.compile(r'\b(remaster(ed)?|deluxe|edition|album version|single version|original version|'
                           r'bonus( track)?|explicit|clean|mono|stereo|feat\.?|ft\.?|with)\b', re.IGNORECASE)


def edition_title(title):
    """The title without the parts that only name an edition: 'Lost - Remastered 2021' -> 'lost'."""
    def drop(match):
        part = match.group(0)
        return ' ' if EDITION_WORDS.search(part) and not VERSION_WORDS.search(part) else part
    text = re.sub(r'\([^)]*\)|\[[^\]]*\]', drop, (title or '').lower())
    text = re.sub(r'\s[-–]\s.*$', drop, text)
    return re.sub(r'[^\w]+', ' ', text).strip()


def song_key(artists, title):
    """The same song in every edition (single, album, deluxe, remaster, credited featuring...): same main
    artist and same title without edition words. Never a live, a remix, a cover or a translated version."""
    main = next((a for a in artists if a), '')
    return re.sub(r'\s+', ' ', main.strip().lower()), edition_title(title)


def same_recording(duration_a, duration_b):
    return not duration_a or not duration_b or abs(duration_a - duration_b) <= TWIN_DURATION_GAP


def _files_by_song(library, root):
    """{song key: [(track id, record)]} of the downloaded files that exist."""
    result = defaultdict(list)
    for tid, record in library['tracks'].items():
        if record['status'] == 'ok' and record.get('path') and (root / record['path']).exists():
            result[song_key(record.get('artists') or [], record.get('title'))].append((tid, record))
    return result


def _twin(files, info):
    """A downloaded file of the same song (another Spotify id), or None."""
    for tid, record in files.get(song_key(info['artists'], info['title']), []):
        if same_recording(record.get('duration'), info.get('duration')):
            return tid, record
    return None


def _bitrate(path):
    import mutagen
    try:
        return getattr(mutagen.File(path).info, 'bitrate', 0) or 0
    except Exception:
        return 0


def _same_file(path):
    import unicodedata
    return unicodedata.normalize('NFC', path).casefold()


def merge_duplicates(library, dry_run=False):
    """Several files of the same song (same title and artists, same length): the best one is kept, the
    others go to the Trash, and every song that used them points to the kept file. Their Apple Music and
    iTunes tracks are removed at the next update. Returns the number of files that are (or would be) removed."""
    root = Path(library['root'])
    tracks = library['tracks']
    by_song = defaultdict(lambda: defaultdict(list))  # song key -> path -> track ids
    spelling = {}  # macOS and Windows ignore case: two spellings of a path are one file
    for tid, record in tracks.items():
        if record['status'] == 'ok' and record.get('path') and (root / record['path']).exists():
            path = spelling.setdefault(_same_file(record['path']), record['path'])
            if path != record['path'] and not dry_run:
                record['path'] = path
            by_song[song_key(record.get('artists') or [], record.get('title'))][path].append(tid)
    removed = 0
    for paths in by_song.values():
        if len(paths) < 2:
            continue
        # Files of different lengths are different recordings (two live versions...): kept apart.
        lengths = sorted((_length(root / p), p) for p in paths)
        clusters, current = [], [lengths[0]]
        for item in lengths[1:]:
            if item[0] - current[0][0] <= TWIN_DURATION_GAP:
                current.append(item)
            else:
                clusters.append(current)
                current = [item]
        clusters.append(current)
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            files = [p for _, p in cluster]
            # Best quality first, then a name without " (2)".
            keep = max(files, key=lambda p: (_bitrate(root / p), not re.search(r' \(\d+\)\.\w+$', p), -len(p)))
            kept = tracks[paths[keep][0]]
            for path in files:
                if path == keep:
                    continue
                removed += 1
                if dry_run:
                    continue
                from send2trash import send2trash
                send2trash(str(root / path))
                for tid in paths[path]:
                    record = tracks[tid]
                    for key, store in (('apple_id', 'apple_remove'), ('itunes_id', 'itunes_remove')):
                        if record.get(key) and record[key] != kept.get(key):
                            library.setdefault(store, []).append(record[key])
                    record.update(path=kept['path'], folder=kept['folder'], shared_with=paths[keep][0],
                                  apple_id=kept.get('apple_id'), apple_path=kept.get('apple_path'),
                                  itunes_id=kept.get('itunes_id'))
    return removed


# --- Plan: what the local copy should look like ---

def current_catalog(sp, progress):
    """The playlists from Spotify when it is connected, else the last imported file."""
    from spotify_client import SpotifyLimitError, keys_present, logged_in

    stored = catalog_store.load()
    if not stored.get('source'):
        stored = catalog_store.from_last_check() or stored
    # An imported file is used only while Spotify can't be read (not connected, or blocked for now).
    if keys_present() and logged_in() and catalog_store.follows_spotify(stored):
        try:
            catalog = catalog_store.refresh_from_spotify(sp, progress)
        except SpotifyLimitError:
            if not stored.get('source'):
                raise
            catalog = stored  # Spotify blocks the app for now: the last copy is used
        else:
            # Spotify becomes the base of the sorting only after a complete read.
            if not catalog.get('partial') and sort_state.pending_count(catalog) == 0:
                sort_state.take_spotify_as_base(catalog)
            return sort_state.view(catalog)
    elif not stored.get('source'):
        raise AppError('no_playlists')
    return sort_state.view(stored)


def build_plan(sp, progress, catalog=None):
    config = config_store.load_config()
    root = music_root(config)
    library = load_library()
    catalog = catalog or current_catalog(sp, progress)

    progress(step='Checking your files')
    playlist_ids = _ordered(config, downloaded_playlists(config, catalog))
    in_playlists = defaultdict(list)
    for pid in playlist_ids:
        for tid in catalog['playlists'][pid]['track_ids']:
            if pid not in in_playlists[tid]:
                in_playlists[tid].append(pid)

    # macOS and Windows ignore case: "ABBA" and "Abba" are one folder, keep one spelling (the one on disk first).
    spelling = {r['folder'].lower(): r['folder'] for r in library['tracks'].values() if r.get('folder')}
    desired = {}
    ignored = library.get('ignored', {})
    for tid, pids in in_playlists.items():
        track = catalog['tracks'].get(tid)
        kept = (library['tracks'].get(tid) or {}).get('status') == 'ok'  # an ignored song keeps the file it has
        if track and track.get('name') and (tid not in ignored or kept):  # Spotify lists a few songs with no title and no artist: nothing to find
            folder = track_folder(config, track, [catalog['playlists'][p]['name'] for p in pids])
            desired[tid] = spelling.setdefault(folder.lower(), folder)

    old_root = Path(library['root'])
    files = _files_by_song(library, old_root)
    to_download, to_move, to_remove, wrong, shared = [], [], [], [], {}
    # A video chosen by hand in Library is never replaced by the length check.
    chosen = {tid for tid, entry in _Matches().data.items() if entry.get('chosen')}
    planned = defaultdict(list)  # songs to download in this sync, by song key
    for track_id, folder in desired.items():
        record = library['tracks'].get(track_id)
        twin = (record or {}).get('shared_with')
        twin_path = (library['tracks'].get(twin) or {}).get('path')
        if twin in desired and twin_path and (old_root / twin_path).exists():
            shared[track_id] = twin  # uses its twin's file, wherever the twin's folder is
            continue
        exists = record and record.get('path') and (old_root / record['path']).exists()
        if not exists:
            twin = _twin(files, _track_info(catalog['tracks'][track_id]))
            if twin:
                shared[track_id] = twin[0]  # same song under another Spotify id: its file is used
                continue
        expected = round((catalog['tracks'][track_id].get('duration_ms') or 0) / 1000) or (record or {}).get('duration') or 0
        if exists and expected and track_id not in chosen and track_id not in ignored and _wrong_length(expected, _length(old_root / record['path'])):
            # A file of another version (downloaded before the length check existed): downloaded again.
            wrong.append(track_id)
            exists = False
        if not exists:
            info = _track_info(catalog['tracks'][track_id])
            twin = _twin(planned, info)
            if twin:
                shared[track_id] = twin[0]  # the other id of this song is downloaded in this sync
                continue
            planned[song_key(info['artists'], info['title'])].append((track_id, {'duration': expected}))
            to_download.append(track_id)
        elif record['folder'] != folder or record['status'] != 'ok' or old_root != root:
            to_move.append(track_id)
    gone_folder = removed_folder(config)
    in_use = set(desired) | set(shared.values())
    for track_id, record in library['tracks'].items():
        if track_id in in_use or not record.get('path') or catalog.get('partial'):
            continue
        if record['status'] == 'ok':
            to_remove.append(track_id)
        elif record['status'] == 'removed' and config['removed']['mode'] == 'move' \
                and (record['folder'] != gone_folder or old_root != root) and (old_root / record['path']).exists():
            to_move.append(track_id)  # already removed, in the old removed folder

    contents = {pid: {'name': catalog['playlists'][pid]['name'], 'track_ids': catalog['playlists'][pid]['track_ids']}
                for pid in playlist_ids}
    plan = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'music_dir': str(root),
        'source': catalog.get('source'),
        'file': catalog.get('file'),
        'desired': desired,
        'to_download': to_download,
        'to_move': to_move,
        'to_remove': to_remove,
        'wrong_length': wrong,
        'shared': shared,
        'duplicates': merge_duplicates(library, dry_run=True),
        'unreadable': catalog.get('unreadable', []),  # playlists Spotify did not give at this read
        'playlists': contents,
        'meta': {tid: _song_data(catalog['tracks'][tid]) for tid in to_download},
        'info': {tid: _track_info(catalog['tracks'][tid]) for tid in desired},
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    _save_lengths()
    return plan


def _song_data(track):
    album = track.get('album') or {}
    images = album.get('images') or []
    release = album.get('release_date') or ''
    artists = [a['name'] for a in track['artists']] or ['']
    return {
        'name': track['name'],
        'artists': artists,
        'artist': artists[0],
        'genres': [],
        'disc_number': track.get('disc_number') or 1,
        'disc_count': 1,
        'album_name': album.get('name') or track['name'],
        'album_artist': album_artist(track) if album.get('artists') else artists[0],
        'duration': round((track.get('duration_ms') or 0) / 1000),
        'year': int(release[:4]) if release[:4].isdigit() else 0,
        'date': release,
        'track_number': track.get('track_number') or 1,
        'tracks_count': album.get('total_tracks') or 1,
        'song_id': track['id'],
        'explicit': bool(track.get('explicit')),
        'publisher': '',
        'url': (track.get('external_urls') or {}).get('spotify') or f"https://open.spotify.com/track/{track['id']}",
        'isrc': (track.get('external_ids') or {}).get('isrc'),
        'cover_url': max(images, key=lambda i: i.get('width') or 0)['url'] if images else None,
        'copyright_text': None,
        'download_url': None,
        'lyrics': None,
        'popularity': None,
        'album_id': album.get('id') or track['id'],
        'list_name': None,
        'list_url': None,
        'list_position': None,
        'list_length': None,
        'artist_id': track['artists'][0].get('id') or '' if track['artists'] else '',
        'album_type': album.get('album_type') or 'album',
    }


# --- Sync: apply the plan ---

def _restore_set_aside():
    """Files set aside as .old by a Sync that stopped halfway go back to their place."""
    library = load_library()
    root = Path(library['root'])
    restored = 0
    for record in library['tracks'].values():
        if record.get('path'):
            path = root / record['path']
            aside = path.with_name(path.name + '.old')
            if not path.exists() and aside.exists():
                aside.replace(path)
                restored += 1
            elif aside.exists():
                _to_trash(aside)  # its replacement was downloaded: the stop came just before the Trash
    return restored


def sync(sp, progress=None, apply=True, catalog=None):
    progress = progress or (lambda **kw: None)
    if apply:
        _restore_set_aside()
        library = load_library()
        progress(step='Removing duplicate files')
        if merge_duplicates(library):
            save_library(library)
    if catalog is None and apply and _fresh_plan():
        # Sync right after the check of its dialog: the playlists just read are used again.
        catalog = sort_state.view(catalog_store.load())
    catalog = catalog or current_catalog(sp, progress)
    plan = build_plan(sp, progress, catalog)
    if not apply:
        progress(step='Done')
        return plan

    config = config_store.load_config()
    root = music_root(config)
    root.mkdir(parents=True, exist_ok=True)
    library = load_library()
    old_root = first_root = Path(library['root'])
    tracks = library['tracks']
    left = set()  # folders files were moved out of, removed at the end if empty

    # The music folder changed: every path becomes relative to the new one before anything moves,
    # so the library stays right if the sync stops halfway.
    if old_root != root:
        for record in tracks.values():
            if record.get('path'):
                record['path'] = os.path.relpath(old_root / record['path'], root)
        library['root'] = str(root)
        save_library(library)

    gone_folder = removed_folder(config)
    moved = {}  # old path -> new path: two Spotify ids (single and album) can share one file
    for i, track_id in enumerate(plan['to_move'], 1):
        progress(step='Moving songs to their new folder', done=i, total=len(plan['to_move']))
        record = tracks[track_id]
        target = plan['desired'].get(track_id, gone_folder)
        src = os.path.normpath(root / record['path'])
        if src in moved:
            record['path'], record['folder'] = moved[src]
        elif Path(src).exists():
            left.add(Path(src).parent)
            _move(root, root, record, target)
            moved[src] = (record['path'], record['folder'])
        else:
            record.update(path=None, status='failed', error=FILE_MISSING)  # downloaded again next time
            continue
        if track_id in plan['desired']:
            record['status'] = 'ok'
            record.pop('removed_at', None)
        if i % 50 == 0:
            save_library(library)
    save_library(library)

    _point_twins(plan, tracks)
    save_library(library)

    # Files of another version: set aside, removed only once the right version is downloaded.
    replaced = {}
    for track_id in plan.get('wrong_length', []):
        record = tracks.get(track_id)
        if record and record.get('path') and (root / record['path']).exists():
            old = root / record['path']
            aside = old.with_name(old.name + '.old')
            old.replace(aside)
            replaced[track_id] = (dict(record), old, aside)
    _download_all(sp, root, config, plan, library, progress)
    _point_twins(plan, tracks)  # twins of the songs just downloaded
    for track_id, (record, old, aside) in replaced.items():
        if tracks.get(track_id, {}).get('status') == 'ok':
            _to_trash(aside)
            _keep_player_tracks(record, tracks[track_id])
        else:
            aside.replace(old)  # the right version was not found: the old file stays
            tracks[track_id] = record
    save_library(library)

    removed = config['removed']
    for i, track_id in enumerate(plan['to_remove'], 1):
        progress(step='Handling removed songs', done=i, total=len(plan['to_remove']))
        record = tracks[track_id]
        if removed['mode'] == 'delete':
            left.add((root / record['path']).parent)
            _to_trash(root / record['path'])  # to the Trash, so a song removed by mistake can come back
            del tracks[track_id]
            continue
        if removed['mode'] == 'move':
            left.add((root / record['path']).parent)
            _move(root, root, record, gone_folder)
        record['status'] = 'removed'
        record['removed_at'] = datetime.now().isoformat(timespec='seconds')
    # Songs that failed and are no longer in a chosen playlist: nothing left to download.
    for track_id in [t for t, r in tracks.items() if r['status'] == 'failed' and t not in plan['desired']
                     and t not in library.get('ignored', {})]:
        del tracks[track_id]
    save_library(library)
    _remove_empty(left, stop=root)
    if first_root != root:
        _remove_empty({d for d in left if first_root in d.parents}, stop=first_root)

    _drop_number_suffixes(library, root)
    progress(step='Writing playlists', current=[])
    write_playlists(root, plan['playlists'], library)
    save_library(library)

    import apple_music
    import itunes_windows
    if config.get('apple_music_auto'):
        # Apple Music on macOS, iTunes on Windows.
        if apple_music.available():
            apple_music.update(sp, progress)
        elif itunes_windows.available():
            itunes_windows.update(sp, progress)
    # What is left for the next sync, from the playlists already read (nothing is asked to Spotify).
    plan = build_plan(sp, progress, catalog)
    progress(step='Done')
    return plan


FRESH_PLAN = 120  # seconds


def _fresh_plan():
    plan = load_plan()
    stored = catalog_store.load()
    if not plan or not stored.get('updated_at'):
        return False
    age = datetime.now() - datetime.fromisoformat(plan['generated_at'])
    return age.total_seconds() < FRESH_PLAN and stored['updated_at'] <= plan['generated_at']


def _point_twins(plan, tracks):
    """Same song under another Spotify id: it points to the twin's file (and its Apple Music track)."""
    for track_id, twin_id in plan.get('shared', {}).items():
        twin = tracks.get(twin_id)
        if not (twin and twin.get('path') and twin['status'] == 'ok'):
            continue
        shared = {'path': twin['path'], 'folder': twin['folder'], 'status': 'ok', 'shared_with': twin_id,
                  'apple_id': twin.get('apple_id'), 'apple_path': twin.get('apple_path'), 'itunes_id': twin.get('itunes_id')}
        record = tracks.get(track_id) or {}
        if any(record.get(k) != v for k, v in shared.items()):
            # Only when the twin's file changed: the rest of the record (its date...) is kept.
            tracks[track_id] = {**record, **plan['info'].get(track_id, {}), **shared,
                                'downloaded_at': record.get('downloaded_at') or datetime.now().isoformat(timespec='seconds')}
            tracks[track_id].pop('error', None)


def _move(old_root, root, record, folder):
    src = old_root / record['path']
    dst_dir = root / folder
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst != src:
        n = 2
        # macOS and Windows ignore case: 'FAMOUS/x.mp3' -> 'Famous/x.mp3' is the same file, not a name taken.
        while dst.exists() and not os.path.samefile(dst, src):
            dst = dst_dir / f'{src.stem} ({n}){src.suffix}'
            n += 1
        if dst.exists():
            # Only the case changes: through another name, as a rename to the same file does nothing.
            step = src.with_name(src.name + '.moving')
            src.rename(step)
            src = step
        shutil.move(str(src), str(dst))
    record['path'] = str(dst.relative_to(root))
    record['folder'] = folder


NUMBER_SUFFIX = re.compile(r' \((\d+)\)(\.\w+)$')


def _drop_number_suffixes(library, root):
    """'Song (2).mp3' got its number when another file had its name; once that one is gone (a duplicate
    sent to the Trash, a song removed), it takes its name back."""
    by_path = defaultdict(list)
    for record in library['tracks'].values():
        if record.get('path'):
            by_path[record['path']].append(record)
    for path, records in by_path.items():
        match = NUMBER_SUFFIX.search(path)
        if not match:
            continue
        clean = path[:match.start()] + match.group(2)
        src, dst = root / path, root / clean
        if clean in by_path or dst.exists() or not src.exists():
            continue
        shutil.move(str(src), str(dst))
        for record in records:
            record['path'] = clean


def _remove_empty(folders, stop):
    """Remove the folders files were moved out of when nothing is left in them (and their empty parents)."""
    for folder in sorted(folders, key=lambda d: len(d.parts), reverse=True):
        while folder != stop and stop in folder.parents and folder.is_dir():
            if any(f for f in folder.iterdir() if f.name != '.DS_Store'):
                break
            shutil.rmtree(folder, ignore_errors=True)
            folder = folder.parent


DOWNLOAD_WORKERS = 3
DOWNLOAD_ATTEMPTS = 3  # YouTube Music sometimes drops the connection when several songs download at once
MATCHES_PATH = DATA_DIR / 'cache' / 'youtube-music.json'
ABSENT_RETRY_DAYS = 7  # a song not on YouTube Music is searched again after this many days

# Outcome of a YouTube Music search. "unreachable" is a network failure: retried, never taken for "absent".
FOUND, ABSENT, UNREACHABLE = 'found', 'absent', 'unreachable'
# Why a song is in Not found: codes, written as text by the page (src/app/services/errors.ts).
NOT_FOUND = 'not_found'
UNAVAILABLE = 'unavailable'
NOT_REACHED = 'not_reached'
WRONG_VERSION = 'wrong_version'
DOWNLOAD_FAILED = 'download_failed'
FILE_MISSING = 'file_missing'


class _Matches:
    """YouTube Music matches of songs that come without a duration (imported files), kept between syncs."""

    def __init__(self):
        import threading
        self.lock = threading.Lock()
        try:
            self.data = json.loads(MATCHES_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.data = {}

    def get(self, track_id):
        entry = self.data.get(track_id)
        if not entry:
            return None
        if entry['outcome'] == ABSENT:
            age = datetime.now() - datetime.fromisoformat(entry['at'])
            if age.days >= ABSENT_RETRY_DAYS:
                return None
        return entry

    def put(self, track_id, outcome, fields=None, final=False):
        """final: neither spotdl nor our search found the song, it is not searched again for a while."""
        with self.lock:
            self.data[track_id] = {'outcome': outcome, 'fields': fields or {}, 'final': final,
                                   'at': datetime.now().isoformat(timespec='seconds')}

    def not_found(self, track_id):
        entry = self.get(track_id)
        return bool(entry and entry['outcome'] == ABSENT and entry.get('final'))

    def save(self):
        with self.lock:
            MATCHES_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = MATCHES_PATH.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
            tmp.replace(MATCHES_PATH)


MATCH_FIELDS = ('duration', 'cover_url', 'album_name', 'year', 'date', 'artists', 'artist', 'album_artist', 'download_url')


def _download_all(sp, root, config, plan, library, progress):
    """Download songs on a few workers. Progress is pushed at every song (done, current, last)."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from spotdl.download.downloader import Downloader
    from spotdl.types.song import Song
    from spotdl.utils.formatter import create_file_name

    ids = [tid for tid in plan['to_download'] if tid in plan['meta']]
    if not ids:
        return
    from genres import GenreResolver
    resolver = GenreResolver(sp)

    ext = config['audio_format']
    settings = {
        'output': FILE_TEMPLATE,
        'format': ext,
        # Keep the bitrate of the source (YouTube Music without Premium: about 130 kbps).
        'bitrate': 'auto',
        'audio_providers': ['youtube-music', 'youtube'],
        'lyrics_providers': [],
        'threads': 1,
        'overwrite': 'skip',
        'simple_tui': True,
        'print_errors': False,
        'log_level': 'CRITICAL',
        # With YouTube Music Premium cookies, the 256 kbps AAC source becomes available.
        'cookie_file': os.path.expanduser(config['youtube_cookies']) if config.get('youtube_cookies') else None,
        'ffmpeg': ffmpeg_path() or 'ffmpeg',
        'yt_dlp_args': ' '.join(f'--js-runtimes {name}:{shlex.quote(r["path"])}' for name, r in js_runtimes().items()),
    }
    tracks = library['tracks']
    local = threading.local()
    lock = threading.Lock()
    state = {'done': 0, 'current': [], 'last': None}
    failed_folders = set()
    matches = _Matches()
    # spotdl creates its temp folders on first use: create them once, before the workers race for them.
    from spotdl.utils.config import get_spotdl_path
    for name in ('temp', 'errors'):
        (Path(get_spotdl_path()) / name).mkdir(parents=True, exist_ok=True)

    # Genres first (the resolver and its cache are not thread-safe). A duration already known
    # (a file of another version being replaced) is reused instead of searched.
    songs_data = {}
    for i, tid in enumerate(ids, 1):
        if i % 25 == 0 or i == len(ids):
            progress(step='Reading genres', done=i, total=len(ids))
        data = dict(plan['meta'][tid])
        data['genres'] = [artist_genre(resolver, data['artist_id'], data['artist'])]
        data['duration'] = data['duration'] or (tracks.get(tid) or {}).get('duration') or 0
        songs_data[tid] = data
    resolver.save()

    def label(tid):
        info = plan['info'].get(tid, {})
        return f"{', '.join(a for a in info.get('artists', []) if a)} - {info.get('title', '')}"

    def report():
        progress(step='Downloading songs', done=state['done'], total=len(ids),
                 current=list(state['current']), last=state['last'])

    def youtube_music():
        if not hasattr(local, 'youtube_music'):
            from ytmusicapi import YTMusic
            local.youtube_music = YTMusic()
        return local.youtube_music

    def lookup(tid, data):
        """Our own YouTube Music match for a song: FOUND (data completed), ABSENT or UNREACHABLE."""
        cached = matches.get(tid)
        if cached:
            data.update({k: v for k, v in cached['fields'].items() if v})
            return cached['outcome']
        try:
            outcome = _complete_from_youtube_music(youtube_music(), data)
        except Exception:
            outcome = UNREACHABLE  # creating the client failed: network
        if outcome != UNREACHABLE:
            matches.put(tid, outcome, {k: data.get(k) for k in MATCH_FIELDS})
        return outcome

    def spotdl_outcome():
        """Why spotdl's last download failed, from its error: (outcome, message for the user)."""
        error = local.downloader.errors[-1] if local.downloader.errors else ''
        if 'LookupError' in error:
            return ABSENT, NOT_FOUND
        if re.search(r'not available|unavailable|blocked|private video|sign in|removed|requested format', error, re.I):
            return 'unavailable', UNAVAILABLE
        if re.search(r'timed? ?out|connection|remote ?disconnected|ssl|temporar|network|resolve|reset by peer', error, re.I):
            return UNREACHABLE, NOT_REACHED
        if 'YT-DLP download error' in error:
            # spotdl hides YouTube's reason: ask YouTube for it.
            reason = _youtube_refusal(error.rsplit(' - ', 1)[-1])
            if reason and re.search(r'not available|sign in|private|age', reason, re.I):
                return 'unavailable', UNAVAILABLE
        log.warning('Download failed: %s', error.split(' - ', 1)[-1][:300] if error else 'no reason given')
        return 'error', DOWNLOAD_FAILED

    def work(tid):
        if not hasattr(local, 'downloader'):
            local.downloader = Downloader(dict(settings))
        data = songs_data[tid]
        if matches.not_found(tid) and not (matches.data.get(tid) or {}).get('chosen'):
            # Searched less than ABSENT_RETRY_DAYS ago, by spotdl and by us: not on YouTube Music.
            with lock:
                tracks[tid] = {**plan['info'].get(tid, {}), 'path': None, 'folder': plan['desired'][tid],
                               'status': 'failed', 'error': NOT_FOUND}
                state['done'] += 1
                report()
            return
        with lock:
            state['current'].append(label(tid))
            report()
        searched = None
        chosen = (matches.data.get(tid) or {}).get('chosen')
        if chosen:
            data.update({k: v for k, v in matches.data[tid]['fields'].items() if v})
            searched = FOUND
        elif not data['duration']:
            # Songs read from a file: duration, cover and year come from YouTube Music.
            searched = lookup(tid, data)
        song = Song.from_dict(data)
        folder = plan['desired'][tid]
        folder_dir = root / folder
        folder_dir.mkdir(parents=True, exist_ok=True)
        with lock:
            # Two different songs with the same artist and title: add the album to the name.
            owners = {r.get('path'): t for t, r in tracks.items()}
            rel = str((folder_dir / create_file_name(song, FILE_TEMPLATE, ext)).relative_to(root))
            template = FILE_TEMPLATE_WITH_ALBUM if owners.get(rel) not in (None, tid) else FILE_TEMPLATE
        local.downloader.settings['output'] = str(folder_dir / template)

        path, error = None, None
        expected = song.duration or 0
        others, picked = None, None  # YouTube results searched as a person would, tried last
        attempt = 0
        while attempt < DOWNLOAD_ATTEMPTS:  # only lost connections count; each other video is tried once
            local.downloader.errors.clear()
            try:
                _, path = local.downloader.download_song(song)
            except Exception:
                path = None
            if not path and local.downloader.errors and 'MetadataError' in local.downloader.errors[-1]:
                # The audio is there, only spotdl's tags failed (a song without artist): kept, tagged below.
                written = folder_dir / create_file_name(song, template, ext)
                if written.exists():
                    path = str(written)
            if path and expected and _wrong_length(expected, _length(Path(path))):
                # Another version (a medley, a 1-hour loop...): not kept.
                Path(path).unlink(missing_ok=True)
                path, error = None, WRONG_VERSION
                if searched is None:
                    searched = lookup(tid, data)
                    if searched == FOUND and data.get('download_url') != song.download_url:
                        song.download_url = data['download_url']
                        continue
                break
            if path:
                error = None
                if picked == song.download_url:
                    # Found among the YouTube results: used again at the next syncs.
                    matches.put(tid, FOUND, {'download_url': picked, 'duration': round(_length(Path(path)) or 0)})
                break
            outcome, message = spotdl_outcome()
            if outcome in (ABSENT, 'unavailable'):
                tried = song.download_url
                if searched is None:
                    # spotdl found nothing, or a video that can't be played: try our own search.
                    searched = lookup(tid, data)
                if searched == FOUND and data.get('download_url') and data['download_url'] != tried:
                    song.download_url = data['download_url']
                    continue
                if searched != UNREACHABLE and not chosen:
                    if others is None:
                        try:
                            others = sure_candidates(youtube_music(), plan['info'].get(tid) or {},
                                                     data.get('isrc'), [tried, data.get('download_url')])
                        except Exception:
                            others = []
                    if others:
                        song.download_url = picked = others.pop(0)
                        continue
                error = NOT_REACHED if searched == UNREACHABLE else message
                if error == NOT_FOUND:
                    matches.put(tid, ABSENT, final=True)
                break
            if outcome == 'error':
                error = message
                break
            error = NOT_REACHED
            attempt += 1
            # Failsafe backoff: YouTube Music dropped the connection, try again a little later.
            time.sleep(3 * attempt)

        info = {**plan['info'].get(tid, {})}
        info['duration'] = info.get('duration') or round(song.duration or 0)
        if not any(info.get('artists') or []):
            info['artists'] = [a for a in song.artists if a]  # songs without artist in the file: the matched one
        with lock:
            if path and Path(path).exists():
                tag_file(Path(path), spotify_id=tid, title=song.name, artist=', '.join(info['artists']),
                         album=song.album_name)
                tracks[tid] = {**info, 'path': str(Path(path).relative_to(root)), 'folder': folder,
                               'status': 'ok', 'source_url': song.download_url,
                               'downloaded_at': datetime.now().isoformat(timespec='seconds')}
                state['last'] = label(tid)
            else:
                tracks[tid] = {**info, 'path': None, 'folder': folder, 'status': 'failed',
                               'error': error or NOT_REACHED}
                # Removed at the end: another worker may be writing a song of the same album there.
                failed_folders.add(folder_dir)
            state['current'].remove(label(tid))
            state['done'] += 1
            report()
            if state['done'] % 10 == 0:
                save_library(library)
                matches.save()

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        list(pool.map(work, ids))
    _remove_empty(failed_folders, stop=root)
    matches.save()
    save_library(library)


def js_runtimes():
    """JavaScript runtimes for yt-dlp, which needs one to solve the script YouTube puts in front of each
    video (without it, many videos fail as if YouTube refused them). Deno comes with the app (pip 'deno')."""
    found = {name: {'path': path} for name in ('deno', 'node', 'bun') if (path := shutil.which(name))}
    if 'deno' not in found:
        try:
            import deno
            found['deno'] = {'path': deno.find_deno_bin()}
        except Exception:
            pass
    return found


def ffmpeg_path():
    """ffmpeg converts the downloads to MP3: the one on the computer, else the one that comes with the app."""
    path = shutil.which('ffmpeg')
    if not path:
        try:
            import imageio_ffmpeg
            path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            path = None
    return path


def _youtube_refusal(url):
    """YouTube's own message for a video it does not give (None if it gives it)."""
    if not YOUTUBE_ID.search(url or ''):
        return None
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                               'js_runtimes': js_runtimes()}) as ydl:
            ydl.extract_info(url, download=False)
        return None
    except Exception as e:
        return str(e)


def _search_youtube_music(client, query):
    """Search results, [] when there is none, None when YouTube Music could not be reached."""
    import time
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            return client.search(query, filter='songs', limit=5)
        except Exception:
            # Failsafe backoff for a dropped connection.
            time.sleep(2 * (attempt + 1))
    return None


def _loose_artist(name):
    """'Ke$ha' = 'Kesha', 'The Black Eyed Peas' = 'Black Eyed Peas', 'Hiroyuki Sawano' = 'Sawano Hiroyuki'."""
    import unicodedata
    text = unicodedata.normalize('NFKC', name or '').lower().replace('$', 's')
    text = re.sub(r'^the\s+', '', text.strip())
    return frozenset(w for w in re.findall(r'\w+', text) if w)


def _artists_match(ours, theirs):
    def letters(name):  # 'U-KISS' = 'UKISS'
        return re.sub(r'\W+', '', _simplified(name or '').lower().replace('$', 's'))

    def names(name):  # '유키스(U-KISS)': the name and the one in brackets
        inner = re.findall(r'\(([^)]*)\)', name or '')
        return [name, re.sub(r'\([^)]*\)', '', name or '').strip()] + inner
    ours = [n for o in ours for n in names(o)]
    theirs = [n for t in theirs for n in names(t)]
    for o in ours:
        for t in theirs:
            a, b = _loose_artist(o), _loose_artist(t)
            if a and b and (a == b or a <= b or b <= a):
                return True
            if letters(o) and letters(o) == letters(t):
                return True
    return False


def _simplified(text):
    """Traditional Chinese written as simplified Chinese ('齊天' -> '齐天'), the two spellings of one title."""
    try:
        import zhconv
        return zhconv.convert(text, 'zh-hans')
    except ImportError:
        return text


def _title_words(text):
    """Title words compared loosely: simplified Chinese, 'ver.' = 'version', '0330' = '330'."""
    words = _norm(_simplified(text or '')).split()
    words = ['version' if w == 'ver' else w for w in words]
    return ' '.join(w.lstrip('0') or '0' if w.isdigit() else w for w in words)


def _latin(text):
    return bool(re.search(r'[a-z]', (text or '').lower()))


def _titles_match(ours, theirs):
    """Same title, or ours inside theirs: YouTube Music often adds a translation before or after,
    '신선놀음 DIVINE', '進撃vc-pf20130218巨人 - Shingeki Vc - Pf 20130218 Kyojin'."""
    # A live, a remix, a slowed... is another recording: both titles must say it.
    kinds = re.compile(r'\b(live|remix|slowed|sped ?up|acoustic|instrumental|inst|8d|nightcore|reverb|cover|karaoke)\b')
    if set(kinds.findall((ours or '').lower())) != set(kinds.findall((theirs or '').lower())):
        return False
    a, b = _title_words(ours), _title_words(theirs)
    if not a or not b:
        return False
    return a == b or f' {a} ' in f' {b} ' or f' {b} ' in f' {a} '


def _complete_from_youtube_music(client, data):
    """Fill the duration, cover, album and year of a song from its YouTube Music match, and use that
    match for the download. Searched by ISRC first (the recording's code, whatever the language of the
    title), then by artist and title. Returns FOUND, ABSENT or UNREACHABLE."""
    ours_artists = [a for a in (data.get('artists') or [data['artist']]) if a]
    queries = []
    if data.get('isrc'):
        queries.append(('isrc', data['isrc']))
    if data['artist']:
        queries.append(('text', f"{data['artist']} {data['name']}"))
    else:
        queries += [('text', f"{data['name']} {data.get('album_name') or ''}".strip()), ('text', data['name'])]

    reached = False
    for kind, query in queries:
        results = _search_youtube_music(client, query)
        if results is None:
            continue
        reached = True
        match = None
        for rank, r in enumerate(results):
            theirs = [a.get('name') or '' for a in r.get('artists') or []]
            artist_ok = _artists_match(ours_artists, theirs) if ours_artists else True
            title_ok = _titles_match(data['name'], r.get('title'))
            # An artist written in another alphabet ('Hua Chen Yu' / '华晨宇') can't be compared.
            other_script = ours_artists and theirs and (_latin(' '.join(ours_artists)) != _latin(' '.join(theirs)))
            if kind == 'isrc':
                # YouTube Music answers an unknown ISRC with unrelated songs: one of the two must agree.
                ok = rank == 0 and (artist_ok or title_ok)
            else:
                ok = title_ok and (artist_ok or (other_script and rank == 0))
            if ok:
                match = r
                break
        if not match:
            continue
        r = match
        data['duration'] = r.get('duration_seconds') or data['duration']
        thumbnails = r.get('thumbnails') or []
        if thumbnails and not data.get('cover_url'):
            data['cover_url'] = re.sub(r'=w\d+-h\d+', '=w544-h544', thumbnails[-1]['url'])
        if r.get('album') and not data.get('album_name'):
            data['album_name'] = r['album'].get('name') or data['album_name']
        if str(r.get('year') or '').isdigit() and not data.get('year'):
            data['year'] = int(r['year'])
            data['date'] = str(r['year'])
        if not data['artist'] and r.get('artists'):
            data['artists'] = [a['name'] for a in r['artists'] if a.get('name')]
            data['artist'] = data['album_artist'] = data['artists'][0]
        if r.get('videoId'):
            data['download_url'] = f"https://music.youtube.com/watch?v={r['videoId']}"
        return FOUND
    return ABSENT if reached else UNREACHABLE


YOUTUBE_ID = re.compile(r'(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})')


def youtube_candidates(track_id):
    """Results for a song not found, to choose by hand: YouTube Music songs first, then YouTube videos
    (other uploads, 8D or slowed versions on their own channels...)."""
    from ytmusicapi import YTMusic
    plan = load_plan() or {}
    info = (plan.get('info') or {}).get(track_id) or load_library()['tracks'].get(track_id) or {}
    meta = (plan.get('meta') or {}).get(track_id) or {}
    # The video that already failed is not offered again.
    tried = ((_Matches().data.get(track_id) or {}).get('fields') or {}).get('download_url') or ''
    return _candidates(YTMusic(), info, meta.get('isrc'), [tried])


def _same_title(ours, theirs):
    """Stricter than _titles_match, to pick a video without the user: one part of the video's title
    ('Glass Animals - Heat Waves (Lyrics) | 8D Audio') is exactly the song's title, same version."""
    kinds = re.compile(r'\b(live|en vivo|en directo|concert|remix|slowed|sped ?up|acoustic|instrumental|inst|8d|'
                       r'nightcore|reverb|cover|karaoke|alternate)\b')
    if set(kinds.findall((ours or '').lower())) != set(kinds.findall((theirs or '').lower())):
        return False
    brackets = re.compile(r'[(\[【「『][^)\]】」』]*[)\]】」』]')
    # The version is compared above: 'Desire - Slowed' = 'DESIRE (Slowed)'.
    title = _title_words(kinds.sub(' ', brackets.sub(' ', ours or '').lower()))
    parts = re.split(r'\s[-–—|:•]\s|\|', kinds.sub(' ', brackets.sub(' ', theirs or '').lower()))
    return bool(title) and any(_title_words(part) == title for part in parts + [' '.join(parts)])


def sure_candidates(client, info, isrc, tried):
    """The results a person would take without hesitating: same title, same version, right artist."""
    ours = [a for a in info.get('artists') or [] if a]
    expected = info.get('duration') or 0
    return [r['url'] for r in _candidates(client, info, isrc, tried)
            if _same_title(info.get('title'), r['title']) and ours
            and not (expected and _wrong_length(expected, _seconds(r['duration'])))
            and (_artists_match(ours, r['artists'])
                 or any(f' {_title_words(a)} ' in f' {_title_words(r["title"])} ' for a in ours))]


def _candidates(client, info, isrc, tried):
    text = f"{' '.join(a for a in info.get('artists') or [] if a)} {info.get('title', '')}".strip()
    seen, results = {m.group(1) for m in (YOUTUBE_ID.search(u or '') for u in tried) if m}, []

    def add(video_id, title, artists, album, duration, thumbnail, kind):
        if video_id and video_id not in seen:
            seen.add(video_id)
            results.append({'url': f'https://music.youtube.com/watch?v={video_id}', 'title': title or '',
                            'artists': [a for a in artists if a], 'album': album, 'duration': duration or '',
                            'thumbnail': thumbnail, 'kind': kind})

    for query, kind in ([(isrc, 'songs')] if isrc else []) + [(text, 'songs'), (text, 'videos')]:
        try:
            found = client.search(query, filter=kind, limit=5)
        except Exception:
            continue
        for r in found[:5]:
            theirs = [a.get('name') or '' for a in r.get('artists') or []]
            if query == isrc and not (_artists_match(info.get('artists') or [], theirs)
                                                  or _titles_match(info.get('title'), r.get('title'))):
                continue  # YouTube Music answers an unknown ISRC with unrelated songs
            thumbnails = r.get('thumbnails') or []
            add(r.get('videoId'), r.get('title'), [a.get('name') for a in r.get('artists') or []],
                (r.get('album') or {}).get('name'), r.get('duration'), thumbnails[0]['url'] if thumbnails else None,
                'song' if kind == 'songs' else 'video')
    # Regular YouTube, as a person would search it.
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True, 'skip_download': True,
                               'js_runtimes': js_runtimes()}) as ydl:
            for e in ydl.extract_info(f'ytsearch5:{text}', download=False).get('entries') or []:
                seconds = int(e.get('duration') or 0)
                add(e.get('id'), e.get('title'), [e.get('channel') or e.get('uploader') or ''], None,
                    f'{seconds // 60}:{seconds % 60:02d}' if seconds else '',
                    (e.get('thumbnails') or [{}])[-1].get('url'), 'video')
    except Exception:
        pass

    def score(r):  # the right title, then YouTube Music songs, then the right artist
        ours = info.get('artists') or []
        title = _titles_match(info.get('title'), r['title'])
        # A video often has 'Artist - Title' as its title.
        artist = _artists_match(ours, r['artists']) or any(_titles_match(a, r['title']) for a in ours if a)
        return title, title and r['kind'] == 'song', artist
    scored = sorted(results, key=score, reverse=True)
    relevant = [r for r in scored if any(score(r))]
    return (relevant or scored)[:12]


def ignore(track_id, ignored=True):
    """A song left out of the downloads (Not found, nothing right on YouTube), or taken back."""
    library = load_library()
    plan = load_plan() or {}
    if ignored:
        info = (plan.get('info') or {}).get(track_id) or library['tracks'].get(track_id) or {}
        library.setdefault('ignored', {})[track_id] = {k: info.get(k) for k in ('title', 'artists', 'album', 'image_url')}
    else:
        library.get('ignored', {}).pop(track_id, None)
    save_library(library)
    if plan:
        _plan_one(plan, library, track_id, wanted=not ignored)


def _plan_one(plan, library, track_id, wanted):
    """Next sync with one song added or left out, without checking every file again."""
    if not plan:
        return  # no Check yet: the next one counts it
    for key in ('to_download', 'wrong_length'):
        if track_id in plan.get(key, []):
            plan[key].remove(track_id)
    kept = (library['tracks'].get(track_id) or {}).get('status') == 'ok'
    for key in ('meta', 'shared') + (() if kept else ('desired',)):
        plan.get(key, {}).pop(track_id, None)
    if wanted:
        config = config_store.load_config()
        catalog = sort_state.view(catalog_store.load())
        track = catalog['tracks'].get(track_id)
        downloaded = set(downloaded_playlists(config, catalog))
        names = [p['name'] for pid, p in catalog['playlists'].items() if pid in downloaded and track_id in p['track_ids']]
        if track and names:
            plan['desired'][track_id] = track_folder(config, track, names)
            plan['info'][track_id] = _track_info(track)
            record = library['tracks'].get(track_id) or {}
            if not (record.get('status') == 'ok' and record.get('path') and (Path(library['root']) / record['path']).exists()):
                plan['to_download'].append(track_id)
                plan['meta'][track_id] = _song_data(track)
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')


def choose_match(track_id, url):
    """The song chosen by hand: used for its download, at once and at every next Sync."""
    match = YOUTUBE_ID.search(url or '')
    if not match:
        raise AppError('not_youtube_link')
    video_id = match.group(1)
    fields = {'download_url': f'https://music.youtube.com/watch?v={video_id}'}
    try:  # the cover and length, as for a song found by our search
        from ytmusicapi import YTMusic
        details = YTMusic().get_song(video_id).get('videoDetails') or {}
        thumbnails = (details.get('thumbnail') or {}).get('thumbnails') or []
        if thumbnails:
            fields['cover_url'] = re.sub(r'=w\d+-h\d+', '=w544-h544', thumbnails[-1]['url'])
        if str(details.get('lengthSeconds') or '').isdigit():
            fields['duration'] = int(details['lengthSeconds'])
    except Exception:
        pass
    matches = _Matches()
    matches.put(track_id, FOUND, fields, final=True)
    matches.data[track_id]['chosen'] = True
    matches.save()


def download_chosen(sp, progress, track_id):
    """Download one song chosen by hand (its playlists and Apple Music are updated at the next Sync)."""
    plan = load_plan()
    if not plan or track_id not in plan['desired']:
        raise AppError('sync_first')
    if track_id not in plan['meta']:
        raise AppError('not_in_not_found')
    config = config_store.load_config()
    library = load_library()
    root = Path(library['root'])
    record = dict(library['tracks'].get(track_id) or {})
    old = root / record['path'] if record.get('status') == 'ok' and record.get('path') else None
    aside = None
    if old and old.exists():
        # A file of another length is replaced: set aside, put back if the chosen video fails.
        aside = old.with_name(old.name + '.old')
        old.replace(aside)
    _download_all(sp, root, config, {**plan, 'to_download': [track_id]}, library, progress)
    if aside:
        if library['tracks'].get(track_id, {}).get('status') == 'ok':
            _to_trash(aside)
            _keep_player_tracks(record, library['tracks'][track_id])
            save_library(library)
        else:
            aside.replace(old)
            library['tracks'][track_id] = record
            save_library(library)
    if library['tracks'].get(track_id, {}).get('status') == 'ok':
        _plan_one(load_plan(), library, track_id, wanted=True)  # no longer to download or correct
    progress(step='Done')


def artist_genre(resolver, artist_id, artist_name):
    """The genre tag, as spotdl wrote it before: the artist's first Spotify genre (Last.fm if none)."""
    if not artist_id and not artist_name:
        return ''
    from genres import artist_key
    entry = resolver.artist_genres(artist_id or artist_key({'name': artist_name}), artist_name)
    genres = entry.get('spotify') or entry.get('lastfm') or []  # spotify is None without Spotify
    return genres[0] if genres else ''


LENGTHS_PATH = DATA_DIR / 'cache' / 'lengths.json'
_lengths = {'data': None, 'changed': False}
_lengths_lock = __import__('threading').Lock()


def _length(path):
    """Length of an audio file in seconds (0 if unreadable). Read once per file: kept with its size and date."""
    import mutagen
    try:
        stat = os.stat(path)
    except OSError:
        return 0
    key, stamp = str(path), [stat.st_size, stat.st_mtime]
    with _lengths_lock:
        if _lengths['data'] is None:
            try:
                _lengths['data'] = json.loads(LENGTHS_PATH.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                _lengths['data'] = {}
        known = _lengths['data'].get(key)
    if known and known[:2] == stamp:
        return known[2]
    try:
        length = getattr(mutagen.File(path).info, 'length', 0) or 0
    except Exception:
        length = 0
    with _lengths_lock:
        _lengths['data'][key] = stamp + [length]
        _lengths['changed'] = True
    return length


def _save_lengths():
    with _lengths_lock:
        if _lengths['changed'] and _lengths['data'] is not None:
            LENGTHS_PATH.parent.mkdir(parents=True, exist_ok=True)
            LENGTHS_PATH.write_text(json.dumps(_lengths['data'], ensure_ascii=False), encoding='utf-8')
            _lengths['changed'] = False


def _keep_player_tracks(old, new):
    """A file replaced by another version: Apple Music and iTunes keep their track (in the same playlists)
    and are told where the new file is, instead of keeping a track of the old file, which they followed
    to the Trash when it was set aside."""
    for key in ('apple_id', 'itunes_id'):
        if old.get(key):
            new[key] = old[key]
    for key in ('apple_path', 'apple_file', 'itunes_file'):
        new.pop(key, None)  # the place is set again at the next update


def _to_trash(path):
    """A replaced file goes to the Trash, so it can still be put back by hand."""
    if path.exists():
        from send2trash import send2trash
        send2trash(str(path))


def _clock(seconds):
    seconds = round(seconds or 0)
    return f'{seconds // 60}:{seconds % 60:02d}'


def _seconds(duration):
    """'3:21' or '1:28:01' in seconds (0 when unknown)."""
    parts = (duration or '').split(':')
    return sum(int(p) * 60 ** i for i, p in enumerate(reversed(parts))) if all(p.isdigit() for p in parts) else 0


def _wrong_length(expected, actual):
    """A file much longer or shorter than the song: another version."""
    return bool(actual) and abs(actual - expected) > max(60, expected * 0.5)


def tag_file(path, genre=None, spotify_id=None, title=None, artist=None, album=None):
    """Write the genre and the Spotify id into the file's tags, and the title, artist and album when
    they are missing (spotdl can't write them for songs without an artist)."""
    from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TCON, TIT2, TPE1, TXXX
    from mutagen.mp4 import MP4, MP4FreeForm

    try:
        if path.suffix.lower() == '.mp3':
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            for frame, value in (('TIT2', title), ('TPE1', artist), ('TALB', album)):
                if value and not tags.getall(frame):
                    tags.add({'TIT2': TIT2, 'TPE1': TPE1, 'TALB': TALB}[frame](encoding=3, text=[value]))
            if genre:
                tags.setall('TCON', [TCON(encoding=3, text=[genre])])
            if spotify_id:
                tags.setall('TXXX:SPOTIFY_ID', [TXXX(encoding=3, desc='SPOTIFY_ID', text=[spotify_id])])
            tags.save(path)
        elif path.suffix.lower() in ('.m4a', '.mp4'):
            audio = MP4(path)
            for key, value in (('\xa9nam', title), ('\xa9ART', artist), ('\xa9alb', album)):
                if value and key not in audio:
                    audio[key] = [value]
            if genre:
                audio['\xa9gen'] = [genre]
            if spotify_id:
                audio['----:com.apple.iTunes:SPOTIFY_ID'] = [MP4FreeForm(spotify_id.encode())]
            audio.save()
    except Exception:
        pass  # tags are a bonus, the file is still usable


def write_playlists(root, contents, library):
    """One .m3u8 per playlist in <layout folder>/Playlists/<folder>/, with paths relative to that folder."""
    config = config_store.load_config()
    folders = config.get('playlist_folders') or {}
    default = config.get('default_folder') or ''
    base_dir = root / layout_base(config) / PLAYLISTS_FOLDER
    base_dir.mkdir(parents=True, exist_ok=True)
    tracks = library['tracks']
    previous = library.get('playlists', {})
    previous_dir = Path(library.get('playlists_dir') or root / PLAYLISTS_FOLDER)
    written, used = {}, set()

    for playlist_id, info in contents.items():
        sub = safe_name(folders.get(playlist_id) or default) if (folders.get(playlist_id) or default) else ''
        folder = base_dir / sub if sub else base_dir
        folder.mkdir(parents=True, exist_ok=True)
        base = safe_name(info['name'])
        name, n = base, 2
        while f'{sub}/{name}'.lower() in used:
            name = f'{base} ({n})'
            n += 1
        used.add(f'{sub}/{name}'.lower())
        filename = f'{sub}/{name}.m3u8' if sub else f'{name}.m3u8'

        lines = ['#EXTM3U', f'#PLAYLIST:{info["name"].strip(INVISIBLE + " ")}']
        listed = set()  # the same song twice in a playlist (or two editions sharing one file): listed once
        for track_id in info['track_ids']:
            record = tracks.get(track_id)
            if not record or record['status'] != 'ok' or not record.get('path') or record['path'] in listed:
                continue
            listed.add(record['path'])
            rel = os.path.relpath(root / record['path'], folder).replace(os.sep, '/')
            artists = ', '.join(a for a in record.get('artists', []) if a)
            label = f"{artists} - {record.get('title', '')}" if artists else record.get('title', '')
            lines.append(f"#EXTINF:{record.get('duration', -1)},{label}")
            lines.append(rel)
        if len(lines) == 2:
            continue  # no downloaded song: no playlist file (an old one is removed below)
        (base_dir / filename).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        written[playlist_id] = filename

    for playlist_id, old in previous.items():
        if previous_dir / old != base_dir / written.get(playlist_id, ''):
            if previous_dir != base_dir or old not in written.values():
                (previous_dir / old).unlink(missing_ok=True)
    for directory in {base_dir, previous_dir}:
        if directory.is_dir():
            for sub in directory.iterdir():
                if sub.is_dir() and not any(f for f in sub.iterdir() if f.name != '.DS_Store'):
                    shutil.rmtree(sub, ignore_errors=True)
    if previous_dir != base_dir and previous_dir.is_dir() and not any(f for f in previous_dir.iterdir() if f.name != '.DS_Store'):
        shutil.rmtree(previous_dir, ignore_errors=True)
    library['playlists'] = written
    library['playlists_dir'] = str(base_dir)


# --- Summary for the app ---

def summary():
    config = config_store.load_config()
    library = load_library()
    plan = load_plan()
    root = music_root(config)

    failed, removed, downloaded = [], [], 0
    for track_id, record in library['tracks'].items():
        if record['status'] == 'ok':
            downloaded += 1
        elif record['status'] == 'failed' and (not plan or track_id in plan['desired']):
            failed.append({'track_id': track_id, **record})
        elif record['status'] == 'removed':
            removed.append({'track_id': track_id, **record})
    # Files of another version kept because the right length was not found: in Not found too, to choose by hand.
    for track_id in (plan or {}).get('wrong_length', []):
        record = library['tracks'].get(track_id) or {}
        actual = _length(Path(library['root']) / record['path']) if record.get('path') else 0
        if actual:  # no file for now: set aside while its replacement downloads
            expected = ((plan.get('info') or {}).get(track_id) or {}).get('duration') or 0
            failed.append({'track_id': track_id, **record, 'status': 'failed', 'error': 'wrong_length',
                           'error_params': {'actual': _clock(actual), 'expected': _clock(expected)}})

    pending = None
    if plan:
        pending = {
            'generated_at': plan['generated_at'],
            'source': plan.get('source'),
            'file': plan.get('file'),
            'to_download': len(plan['to_download']),
            'to_move': len(plan['to_move']),
            'to_remove': len(plan['to_remove']),
            'wrong_length': len(plan.get('wrong_length', [])),
            'duplicates': plan.get('duplicates', 0),
            'unreadable': plan.get('unreadable', []),
            'playlists': len(plan['playlists']),
            'moves_folder': Path(library['root']) != root,
        }
    # The folders the playlists go to in Apple Music and iTunes, to say what to check when syncing an iPhone.
    folder_of = config.get('playlist_folders') or {}
    default = config.get('default_folder') or ''
    folders = sorted({folder_of.get(pid) or default for pid in (plan or {}).get('playlists', {})} - {''}, key=str.lower)
    return {
        'music_dir': str(root / layout_base(config)),
        'player_folders': folders,
        'downloaded': downloaded,
        'failed': failed,
        'removed': removed,
        'ignored': [{'track_id': tid, **info, 'status': 'ignored'} for tid, info in library.get('ignored', {}).items()],
        'playlists': len(library.get('playlists', {})),
        'plan': pending,
    }


# --- Import files downloaded before (another computer, an old spotdl run...) ---

IMPORT_RESULT_PATH = DATA_DIR / 'import-result.json'
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.mp4', '.aac', '.opus', '.ogg', '.flac', '.wav'}
SPOTIFY_TRACK_URL = re.compile(r'open\.spotify\.com/track/([A-Za-z0-9]{22})')


def _norm(text):
    text = text.lower()
    # Keep the words that make a different recording: "Done For Me (Instrumental)".
    text = re.sub(r'[\(\[-]\s*(instrumental|inst\.?|acoustic|live|remix)\b[^\)\]]*[\)\]]?', r' \1 ', text)
    text = re.sub(r'\(.*?\)|\[.*?\]', ' ', text)            # (feat. x), [Remastered]
    text = re.sub(r'\s-\s.*(remaster|version|edit|mix|live).*$', ' ', text)
    text = re.sub(r'\b(feat|ft)\.?\s.*$', ' ', text)
    return re.sub(r'[^\w]+', ' ', text).strip()


def _read_file_tags(path):
    """(spotify_id, title, artist, duration) from a file's tags, or from its name."""
    import mutagen

    spotify_id = title = artist = None
    duration = None
    try:
        audio = mutagen.File(path)
        if audio is not None:
            duration = getattr(audio.info, 'length', None)
            for value in (audio.tags or {}).values():
                text = str(getattr(value, 'url', '') or value)
                match = SPOTIFY_TRACK_URL.search(text)
                if match:
                    spotify_id = match.group(1)
                elif 'SPOTIFY_ID' in str(getattr(value, 'desc', '')) or 'SPOTIFY_ID' in text[:40]:
                    spotify_id = spotify_id or str(value.text[0] if hasattr(value, 'text') else value)
        easy = mutagen.File(path, easy=True)
        if easy is not None and easy.tags:
            title = (easy.tags.get('title') or [None])[0]
            artist = (easy.tags.get('artist') or [None])[0]
    except Exception:
        pass
    if not title and ' - ' in path.stem:
        artist, title = path.stem.split(' - ', 1)
    return spotify_id, title or path.stem, artist or '', duration


def _artist_key(name):
    """'Hwa Sa' and 'HWASA' are the same artist."""
    return _norm(name).replace(' ', '')


MAX_DURATION_GAP = 45  # YouTube versions often have a longer intro or ending


def _pick_by_duration(candidates, duration, info):
    """The candidate whose duration is the closest, if close enough (or the only one when unknown)."""
    if not candidates:
        return None
    if not duration or not any(info[c]['duration'] for c in candidates):
        # Unknown duration (songs read from a file have none): only a single candidate is safe.
        return candidates[0] if len(candidates) == 1 else None
    gaps = sorted((abs(info[c]['duration'] - duration), c) for c in candidates)
    if gaps[0][0] > MAX_DURATION_GAP:
        return None
    # Same artist and title: the same song released twice (single and album), take the closest.
    return gaps[0][1]


def import_files(sp, progress=None, source='', mode='copy'):
    """Put already downloaded files where the current playlists say they belong."""
    progress = progress or (lambda **kw: None)
    source = Path(os.path.expanduser(source))
    if not source.is_dir():
        raise AppError('folder_not_found', folder=str(source))

    plan = build_plan(sp, progress)
    config = config_store.load_config()
    root = music_root(config)
    library = load_library()
    if Path(library['root']) != root:
        raise AppError('music_folder_changed')
    tracks = library['tracks']

    by_name = defaultdict(list)
    for track_id, info in plan['info'].items():
        artists = [a for a in info['artists'] if a]
        for artist in artists[:1] + [', '.join(artists)]:
            by_name[(_artist_key(artist), _norm(info['title'] or ''))].append(track_id)

    files = [p for p in source.rglob('*') if p.suffix.lower() in AUDIO_EXTENSIONS and p.is_file()]
    matched, already, unmatched = 0, 0, []
    emptied = set()  # folders files were moved out of
    for i, path in enumerate(files, 1):
        if i % 10 == 0 or i == len(files):
            progress(step='Matching your files', done=i, total=len(files))
        spotify_id, title, artist, duration = _read_file_tags(path)
        track_id = spotify_id if spotify_id in plan['desired'] else None
        if not track_id:
            first_artist = re.split(r'\s*(?:,|/|;|&| feat\.? | ft\.? )\s*', artist)[0] if artist else ''
            candidates = (by_name.get((_artist_key(artist), _norm(title)), [])
                          or by_name.get((_artist_key(first_artist), _norm(title)), []))
            track_id = _pick_by_duration(list(dict.fromkeys(candidates)), duration, plan['info'])
        if not track_id:
            unmatched.append(str(path.relative_to(source)))
            continue
        record = tracks.get(track_id)
        if record and record['status'] == 'ok' and record.get('path') and (root / record['path']).exists():
            already += 1
            continue

        folder = plan['desired'][track_id]
        dest_dir = root / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        info = plan['info'][track_id]
        name = safe_name(f"{', '.join(a for a in info['artists'] if a)} - {info['title']}") + path.suffix.lower()
        dest, n = dest_dir / name, 2
        while dest.exists() and dest.resolve() != path.resolve():
            dest = dest_dir / f'{Path(name).stem} ({n}){path.suffix.lower()}'
            n += 1
        # Files already inside the music folder are moved, never duplicated.
        inside = root.resolve() in path.resolve().parents
        if dest.resolve() != path.resolve():
            (shutil.move if mode == 'move' or inside else shutil.copy2)(str(path), str(dest))
            if mode == 'move' or inside:
                emptied.add(path.parent)
        tag_file(dest, spotify_id=track_id)
        tracks[track_id] = {**info, 'path': str(dest.relative_to(root)), 'folder': folder, 'status': 'ok',
                            'source_url': None, 'imported_from': str(path),
                            'downloaded_at': datetime.now().isoformat(timespec='seconds')}
        matched += 1
        if matched % 25 == 0:
            save_library(library)

    save_library(library)
    # Folders left empty by the moves are removed (a copy leaves the source as it was).
    _remove_empty({d for d in emptied if d.name != PLAYLISTS_FOLDER}, stop=source)
    progress(step='Writing playlists')
    write_playlists(root, plan['playlists'], library)
    save_library(library)
    result = {'finished_at': datetime.now().isoformat(timespec='seconds'), 'source': str(source), 'mode': mode,
              'files': len(files), 'matched': matched, 'already': already, 'unmatched': unmatched}
    IMPORT_RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    progress(step='Done')
    return result


def load_imported():
    if IMPORTED_PATH.exists():
        return json.loads(IMPORTED_PATH.read_text(encoding='utf-8'))
    return None


def load_import_result():
    if IMPORT_RESULT_PATH.exists():
        return json.loads(IMPORT_RESULT_PATH.read_text(encoding='utf-8'))
    return None
