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
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import catalog as catalog_store
import config_store
import sort_state
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
    if 'root' not in library:
        # Paths are relative to the music folder they were downloaded to.
        library['root'] = str(music_root(config_store.load_config()))
    return library


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


# --- Plan: what the local copy should look like ---

def current_catalog(sp, progress):
    """The playlists from Spotify when it is connected, else the last imported file."""
    from spotify_client import SpotifyLimitError, keys_present, logged_in

    stored = catalog_store.load()
    if not stored.get('source'):
        stored = catalog_store.from_last_check() or stored
    if keys_present() and logged_in() and stored.get('source') in (None, 'spotify'):
        try:
            catalog = catalog_store.refresh_from_spotify(sp, progress)
        except SpotifyLimitError:
            if not stored.get('source'):
                raise
            catalog = stored  # Spotify blocks the app for now: the last copy is used
        else:
            if sort_state.pending_count(catalog) == 0:
                sort_state.take_spotify_as_base(catalog)
            return sort_state.view(catalog)
    elif not stored.get('source'):
        raise RuntimeError('No playlists yet. Connect Spotify or import your playlists first.')
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
    for tid, pids in in_playlists.items():
        track = catalog['tracks'].get(tid)
        if track:
            folder = track_folder(config, track, [catalog['playlists'][p]['name'] for p in pids])
            desired[tid] = spelling.setdefault(folder.lower(), folder)

    old_root = Path(library['root'])
    to_download, to_move, to_remove = [], [], []
    for track_id, folder in desired.items():
        record = library['tracks'].get(track_id)
        exists = record and record.get('path') and (old_root / record['path']).exists()
        if not exists:
            to_download.append(track_id)
        elif record['folder'] != folder or record['status'] != 'ok' or old_root != root:
            to_move.append(track_id)
    gone_folder = removed_folder(config)
    for track_id, record in library['tracks'].items():
        if track_id in desired or not record.get('path') or catalog.get('partial'):
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
        'desired': desired,
        'to_download': to_download,
        'to_move': to_move,
        'to_remove': to_remove,
        'playlists': contents,
        'meta': {tid: _song_data(catalog['tracks'][tid]) for tid in to_download},
        'info': {tid: _track_info(catalog['tracks'][tid]) for tid in desired},
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
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

def sync(sp, progress=None, apply=True, catalog=None):
    progress = progress or (lambda **kw: None)
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

    gone_folder = removed_folder(config)
    for i, track_id in enumerate(plan['to_move'], 1):
        progress(step='Moving songs to their new folder', done=i, total=len(plan['to_move']))
        record = tracks[track_id]
        target = plan['desired'].get(track_id, gone_folder)
        left.add((old_root / record['path']).parent)
        _move(old_root, root, record, target)
        if track_id in plan['desired']:
            record['status'] = 'ok'
            record.pop('removed_at', None)
        if i % 50 == 0:
            save_library(library)
    # Every path is now relative to the current music folder.
    if old_root != root:
        for record in tracks.values():
            if record.get('path') and not (root / record['path']).exists() and (old_root / record['path']).exists():
                record['path'] = os.path.relpath(old_root / record['path'], root)
        library['root'] = str(root)
        old_root = root
    save_library(library)

    _download_all(sp, root, config, plan, library, progress)

    removed = config['removed']
    for i, track_id in enumerate(plan['to_remove'], 1):
        progress(step='Handling removed songs', done=i, total=len(plan['to_remove']))
        record = tracks[track_id]
        if removed['mode'] == 'delete':
            left.add((root / record['path']).parent)
            (root / record['path']).unlink(missing_ok=True)
            del tracks[track_id]
            continue
        if removed['mode'] == 'move':
            left.add((root / record['path']).parent)
            _move(root, root, record, gone_folder)
        record['status'] = 'removed'
        record['removed_at'] = datetime.now().isoformat(timespec='seconds')
    save_library(library)
    _remove_empty(left, stop=root)
    if first_root != root:
        _remove_empty({d for d in left if first_root in d.parents}, stop=first_root)

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
    progress(step='Done')
    return plan


def _move(old_root, root, record, folder):
    src = old_root / record['path']
    dst_dir = root / folder
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst != src:
        n = 2
        while dst.exists():
            dst = dst_dir / f'{src.stem} ({n}){src.suffix}'
            n += 1
        shutil.move(str(src), str(dst))
    record['path'] = str(dst.relative_to(root))
    record['folder'] = folder


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


def _download_all(sp, root, config, plan, library, progress):
    """Download songs one by one on a few workers, so progress moves at every song."""
    import threading
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
    }
    tracks = library['tracks']
    local = threading.local()
    lock = threading.Lock()
    state = {'done': 0, 'current': []}
    failed_folders = set()
    # spotdl creates its temp folders on first use: create them once, before the workers race for them.
    from spotdl.utils.config import get_spotdl_path
    for name in ('temp', 'errors'):
        (Path(get_spotdl_path()) / name).mkdir(parents=True, exist_ok=True)

    # Genres are looked up before starting (the resolver and its cache are not thread-safe).
    songs = {}
    youtube_music = None
    for i, tid in enumerate(ids, 1):
        data = dict(plan['meta'][tid])
        data['genres'] = [artist_genre(resolver, data['artist_id'], data['artist'])]
        if not data['duration']:
            # Songs read from a file: duration, cover and year come from YouTube Music.
            progress(step='Looking up songs on YouTube Music', done=i, total=len(ids))
            if youtube_music is None:
                from ytmusicapi import YTMusic
                youtube_music = YTMusic()
            _complete_from_youtube_music(youtube_music, data)
        songs[tid] = Song.from_dict(data)
    resolver.save()

    def label(tid):
        info = plan['info'].get(tid, {})
        return f"{', '.join(a for a in info.get('artists', []) if a)} - {info.get('title', '')}"

    def report():
        progress(step='Downloading songs', done=state['done'], total=len(ids), current=list(state['current']))

    def work(tid):
        if not hasattr(local, 'downloader'):
            local.downloader = Downloader(dict(settings))
        folder = plan['desired'][tid]
        folder_dir = root / folder
        folder_dir.mkdir(parents=True, exist_ok=True)
        song = songs[tid]
        with lock:
            state['current'].append(label(tid))
            report()
            # Two different songs with the same artist and title: add the album to the name.
            owners = {r.get('path'): t for t, r in tracks.items()}
            rel = str((folder_dir / create_file_name(song, FILE_TEMPLATE, ext)).relative_to(root))
            template = FILE_TEMPLATE_WITH_ALBUM if owners.get(rel) not in (None, tid) else FILE_TEMPLATE
        local.downloader.settings['output'] = str(folder_dir / template)
        path = None
        for attempt in range(DOWNLOAD_ATTEMPTS):
            try:
                _, path = local.downloader.download_song(song)
            except Exception:
                path = None
            if path:
                break
            if not song.download_url:
                # spotdl found nothing: try our own search (it accepts titles with a translation added).
                _use_youtube_music_match(local, song)
                if not song.download_url:
                    break  # not on YouTube Music, retrying won't help
            import time
            time.sleep(3 * (attempt + 1))
        info = {**plan['info'].get(tid, {})}
        info['duration'] = info.get('duration') or round(song.duration or 0)
        with lock:
            if path and Path(path).exists():
                tag_file(Path(path), spotify_id=tid)
                tracks[tid] = {**info, 'path': str(Path(path).relative_to(root)), 'folder': folder,
                               'status': 'ok', 'source_url': song.download_url,
                               'downloaded_at': datetime.now().isoformat(timespec='seconds')}
            else:
                tracks[tid] = {**info, 'path': None, 'folder': folder, 'status': 'failed',
                               'error': 'Not found on YouTube Music' if not song.download_url else 'Could not be downloaded'}
                # Removed at the end: another worker may be writing a song of the same album there.
                failed_folders.add(folder_dir)
            state['current'].remove(label(tid))
            state['done'] += 1
            report()
            if state['done'] % 10 == 0:
                save_library(library)

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        list(pool.map(work, ids))
    _remove_empty(failed_folders, stop=root)
    save_library(library)


def _use_youtube_music_match(local, song):
    """Set song.download_url from our own YouTube Music search (one client per worker thread)."""
    if not hasattr(local, 'youtube_music'):
        from ytmusicapi import YTMusic
        local.youtube_music = YTMusic()
    data = {'name': song.name, 'artist': song.artist, 'artists': list(song.artists), 'isrc': song.isrc,
            'duration': song.duration, 'album_name': song.album_name, 'year': song.year, 'cover_url': song.cover_url}
    _complete_from_youtube_music(local.youtube_music, data)
    if data.get('download_url'):
        song.download_url = data['download_url']


def _search_youtube_music(client, query):
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            return client.search(query, filter='songs', limit=5)
        except Exception:
            import time
            time.sleep(2 * (attempt + 1))
    return []


def _complete_from_youtube_music(client, data):
    """Fill the duration, cover, album and year of a song from its YouTube Music match, and use that
    match for the download. Songs without an artist (in some exported files) are searched by title and album."""
    title, artist = _norm(data['name']), _artist_key(data['artist'])
    if data['artist']:
        queries = ([data['isrc']] if data.get('isrc') else []) + [f"{data['artist']} {data['name']}"]
    else:
        queries = [f"{data['name']} {data.get('album_name') or ''}".strip(), data['name']]
    def same_title(found):
        # YouTube Music titles often add a translation: "Burnin’ Tires (창빈 & 아이엔) Burnin’ Tires (Changbin & I.N)".
        found = _norm(found or '')
        return found == title or found.startswith(title + ' ') or (found and title.startswith(found + ' '))

    for query in queries:
        results = _search_youtube_music(client, query)
        candidates = []
        for r in results:
            artists = [_artist_key(a.get('name') or '') for a in r.get('artists') or []]
            if (artist in artists or not artist) and same_title(r.get('title')):
                exact = _norm(r.get('title') or '') == title
                candidates.append((0 if exact else 1, r))
            elif query == data.get('isrc') and len(results) == 1:
                candidates.append((2, r))
        for _, r in sorted(candidates, key=lambda c: c[0])[:1]:
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
            return


def artist_genre(resolver, artist_id, artist_name):
    """The genre tag, as spotdl wrote it before: the artist's first Spotify genre (Last.fm if none)."""
    if not artist_id and not artist_name:
        return ''
    from genres import artist_key
    entry = resolver.artist_genres(artist_id or artist_key({'name': artist_name}), artist_name)
    genres = entry.get('spotify') or entry.get('lastfm') or []  # spotify is None without Spotify
    return genres[0] if genres else ''


def tag_file(path, genre=None, spotify_id=None):
    """Write the genre and the Spotify id into the file's tags."""
    from mutagen.id3 import ID3, ID3NoHeaderError, TCON, TXXX
    from mutagen.mp4 import MP4, MP4FreeForm

    try:
        if path.suffix.lower() == '.mp3':
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            if genre:
                tags.setall('TCON', [TCON(encoding=3, text=[genre])])
            if spotify_id:
                tags.setall('TXXX:SPOTIFY_ID', [TXXX(encoding=3, desc='SPOTIFY_ID', text=[spotify_id])])
            tags.save(path)
        elif path.suffix.lower() in ('.m4a', '.mp4'):
            audio = MP4(path)
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
        for track_id in info['track_ids']:
            record = tracks.get(track_id)
            if not record or record['status'] != 'ok' or not record.get('path'):
                continue
            rel = os.path.relpath(root / record['path'], folder).replace(os.sep, '/')
            lines.append(f"#EXTINF:{record.get('duration', -1)},{', '.join(record.get('artists', []))} - {record.get('title', '')}")
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
        elif record['status'] == 'failed':
            failed.append({'track_id': track_id, **record})
        elif record['status'] == 'removed':
            removed.append({'track_id': track_id, **record})

    pending = None
    if plan:
        pending = {
            'generated_at': plan['generated_at'],
            'to_download': len(plan['to_download']),
            'to_move': len(plan['to_move']),
            'to_remove': len(plan['to_remove']),
            'playlists': len(plan['playlists']),
            'moves_folder': Path(library['root']) != root,
        }
    return {
        'music_dir': str(root / layout_base(config)),
        'downloaded': downloaded,
        'failed': failed,
        'removed': removed,
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
        raise ValueError(f'Folder not found: {source}')

    plan = build_plan(sp, progress)
    config = config_store.load_config()
    root = music_root(config)
    library = load_library()
    if Path(library['root']) != root:
        raise ValueError('The music folder changed. Run Sync first, then import.')
    tracks = library['tracks']

    by_name = defaultdict(list)
    for track_id, info in plan['info'].items():
        artists = [a for a in info['artists'] if a]
        for artist in artists[:1] + [', '.join(artists)]:
            by_name[(_artist_key(artist), _norm(info['title'] or ''))].append(track_id)

    files = [p for p in source.rglob('*') if p.suffix.lower() in AUDIO_EXTENSIONS and p.is_file()]
    matched, already, unmatched = 0, 0, []
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
        tag_file(dest, spotify_id=track_id)
        tracks[track_id] = {**info, 'path': str(dest.relative_to(root)), 'folder': folder, 'status': 'ok',
                            'source_url': None, 'imported_from': str(path),
                            'downloaded_at': datetime.now().isoformat(timespec='seconds')}
        matched += 1
        if matched % 25 == 0:
            save_library(library)

    save_library(library)
    # Remove folders left empty by the moves (the Playlists folder stays).
    for folder in sorted((d for d in source.rglob('*') if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
        if folder.name != PLAYLISTS_FOLDER and not any(f for f in folder.iterdir() if f.name != '.DS_Store'):
            shutil.rmtree(folder, ignore_errors=True)
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
