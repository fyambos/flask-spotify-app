"""Local copy of your Spotify library.

- Songs of the genre playlists are downloaded once into <music_dir>/<Genre>/ (the first
  genre playlist in priority order decides the folder).
- Optionally, songs of your other playlists that are not in your Liked Songs go to
  <music_dir>/<non_liked folder>/, depending on Settings > Playlists to download (all
  playlists, Liked Songs only, or a chosen list). Liked songs not sorted yet are not downloaded.
- Every playlist you own (genre playlists, other playlists, Liked Songs) is written as an
  .m3u8 file in <music_dir>/Playlists/, pointing to the downloaded files. Nothing is
  downloaded twice.
- Spotify is the reference: a song moved to another genre playlist moves to that folder;
  a song no longer in any synced playlist is kept, moved to the removed folder or deleted.

Audio comes from YouTube Music through spotdl, using the metadata we already have from
Spotify (spotdl's own Spotify access is never used).
"""
import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import config_store
from config_store import DATA_DIR
from spotify_client import liked_tracks, my_playlists, playlist_tracks

LIBRARY_PATH = DATA_DIR / 'library.json'
PLAN_PATH = DATA_DIR / 'library-plan.json'
PLAYLISTS_FOLDER = 'Playlists'
LIKED_PLAYLIST_ID = 'liked'
LIKED_PLAYLIST_NAME = 'Liked Songs'
FILE_TEMPLATE = '{artists} - {title}.{output-ext}'
FILE_TEMPLATE_WITH_ALBUM = '{artists} - {title} ({album}).{output-ext}'
INVISIBLE = '⠀ㅤ​'


def music_root(config):
    return Path(os.path.expanduser(config['music_dir']))


def safe_name(name):
    """A name usable as a file or folder name on macOS, Windows and Android."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', ' ', name).strip(f' .\t{INVISIBLE}')
    return re.sub(r'\s+', ' ', name) or 'Untitled'


def load_library():
    if LIBRARY_PATH.exists():
        return json.loads(LIBRARY_PATH.read_text(encoding='utf-8'))
    return {'tracks': {}, 'playlists': {}}


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


# --- Plan: what the local copy should look like ---

def build_plan(sp, progress):
    config = config_store.load_config()
    root = music_root(config)
    library = load_library()
    non_liked = config['non_liked']
    download = config.get('download') or {'mode': 'all', 'playlists': []}
    chosen = set(download.get('playlists') or [])

    progress(step='Reading your Liked Songs')
    liked = liked_tracks(sp)
    liked_ids = [t['id'] for t in liked]
    liked_set = set(liked_ids)

    meta = {t['id']: t for t in liked}
    desired = {}
    contents = {}

    genres = config['playlists']
    for i, entry in enumerate(genres, 1):
        progress(step=f"Reading {entry['name']}", done=i, total=len(genres))
        tracks = playlist_tracks(sp, entry['playlist_id'])
        contents[entry['playlist_id']] = {'name': entry['name'], 'track_ids': [t['id'] for t in tracks]}
        for t in tracks:
            meta.setdefault(t['id'], t)
            if download['mode'] == 'liked' and t['id'] not in liked_set:
                continue
            desired.setdefault(t['id'], safe_name(entry['name']))

    progress(step='Reading your other playlists')
    me = sp.me()['id']
    genre_ids = {e['playlist_id'] for e in genres}
    others = [p for p in my_playlists(sp)
              if p['id'] not in genre_ids and ((p.get('owner') or {}).get('id') == me or p.get('collaborative'))]
    pending_liked = set(liked_set - desired.keys())
    for i, p in enumerate(others, 1):
        progress(step=f"Reading {p['name'].strip(INVISIBLE + ' ')}", done=i, total=len(others))
        try:
            tracks = playlist_tracks(sp, p['id'])
        except Exception:
            continue
        contents[p['id']] = {'name': p['name'], 'track_ids': [t['id'] for t in tracks]}
        for t in tracks:
            meta.setdefault(t['id'], t)
            if t['id'] in desired:
                continue
            if t['id'] in liked_set:
                pending_liked.add(t['id'])
            elif download['mode'] == 'all' or (download['mode'] == 'selected' and p['id'] in chosen):
                desired[t['id']] = safe_name(non_liked['folder'])
    contents[LIKED_PLAYLIST_ID] = {'name': LIKED_PLAYLIST_NAME, 'track_ids': liked_ids}

    to_download, to_move, to_remove = [], [], []
    for track_id, folder in desired.items():
        record = library['tracks'].get(track_id)
        exists = record and record.get('path') and (root / record['path']).exists()
        if not exists:
            to_download.append(track_id)
        elif record['folder'] != folder or record['status'] != 'ok':
            to_move.append(track_id)
    for track_id, record in library['tracks'].items():
        if track_id not in desired and record['status'] == 'ok':
            to_remove.append(track_id)

    plan = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'music_dir': str(root),
        'desired': desired,
        'to_download': to_download,
        'to_move': to_move,
        'to_remove': to_remove,
        'pending_liked': len(pending_liked),
        'playlists': contents,
        'meta': {tid: _song_data(meta[tid], desired[tid]) for tid in to_download if tid in meta},
        'info': {tid: _track_info(meta[tid]) for tid in desired if tid in meta},
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    return plan


def _song_data(track, folder):
    album = track.get('album') or {}
    images = album.get('images') or []
    release = album.get('release_date') or ''
    return {
        'name': track['name'],
        'artists': [a['name'] for a in track['artists']],
        'artist': track['artists'][0]['name'],
        'genres': [folder],
        'disc_number': track.get('disc_number') or 1,
        'disc_count': 1,
        'album_name': album.get('name') or track['name'],
        'album_artist': (album.get('artists') or track['artists'])[0]['name'],
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
        'artist_id': track['artists'][0].get('id') or '',
        'album_type': album.get('album_type') or 'album',
    }


# --- Sync: apply the plan ---

def sync(sp, progress=None, apply=True):
    progress = progress or (lambda **kw: None)
    plan = build_plan(sp, progress)
    if not apply:
        progress(step='Done')
        return plan

    config = config_store.load_config()
    root = music_root(config)
    root.mkdir(parents=True, exist_ok=True)
    library = load_library()
    tracks = library['tracks']

    for i, track_id in enumerate(plan['to_move'], 1):
        progress(step='Moving songs to their new folder', done=i, total=len(plan['to_move']))
        _move(root, tracks[track_id], plan['desired'][track_id])
        tracks[track_id]['status'] = 'ok'
        tracks[track_id].pop('removed_at', None)
    save_library(library)

    _download_all(sp, root, config, plan, library, progress)

    removed = config['removed']
    for i, track_id in enumerate(plan['to_remove'], 1):
        progress(step='Handling removed songs', done=i, total=len(plan['to_remove']))
        record = tracks[track_id]
        if removed['mode'] == 'delete':
            (root / record['path']).unlink(missing_ok=True)
            del tracks[track_id]
            continue
        if removed['mode'] == 'move':
            _move(root, record, safe_name(removed['folder']))
        record['status'] = 'removed'
        record['removed_at'] = datetime.now().isoformat(timespec='seconds')
    save_library(library)

    progress(step='Writing playlists', current=[])
    write_playlists(root, plan['playlists'], library)
    save_library(library)

    import apple_music
    if config.get('apple_music_auto') and apple_music.available():
        apple_music.update(sp, progress)
    progress(step='Done')
    return plan


def _move(root, record, folder):
    src = root / record['path']
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


DOWNLOAD_WORKERS = 4


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

    # Genres are looked up before starting (the resolver and its cache are not thread-safe).
    songs = {}
    for tid in ids:
        data = dict(plan['meta'][tid])
        data['genres'] = [artist_genre(resolver, data['artist_id'], data['artist'])]
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
        try:
            _, path = local.downloader.download_song(song)
        except Exception:
            path = None
        info = plan['info'].get(tid, {})
        with lock:
            if path and Path(path).exists():
                tag_file(Path(path), spotify_id=tid)
                tracks[tid] = {**info, 'path': str(Path(path).relative_to(root)), 'folder': folder,
                               'status': 'ok', 'source_url': song.download_url,
                               'downloaded_at': datetime.now().isoformat(timespec='seconds')}
            else:
                tracks[tid] = {**info, 'path': None, 'folder': folder, 'status': 'failed',
                               'error': 'Could not be downloaded'}
            state['current'].remove(label(tid))
            state['done'] += 1
            report()
            if state['done'] % 10 == 0:
                save_library(library)

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        list(pool.map(work, ids))
    save_library(library)


def artist_genre(resolver, artist_id, artist_name):
    """The genre tag, as spotdl wrote it before: the artist's first Spotify genre (Last.fm if none)."""
    if not artist_id:
        return ''
    entry = resolver.artist_genres(artist_id, artist_name)
    genres = entry.get('spotify') or entry.get('lastfm') or []
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
    """One .m3u8 per playlist in Playlists/<folder>/, with paths relative to that folder."""
    config = config_store.load_config()
    folders = config.get('playlist_folders') or {}
    default = config.get('default_folder') or ''
    base_dir = root / PLAYLISTS_FOLDER
    base_dir.mkdir(parents=True, exist_ok=True)
    tracks = library['tracks']
    previous = library.get('playlists', {})
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
        (base_dir / filename).write_text('\n'.join(lines) + '\n', encoding='utf-8')

        old = previous.get(playlist_id)
        if old and old != filename:
            (base_dir / old).unlink(missing_ok=True)
        written[playlist_id] = filename

    for playlist_id, old in previous.items():
        if playlist_id not in written and old not in written.values():
            (base_dir / old).unlink(missing_ok=True)
    for sub in base_dir.iterdir():
        if sub.is_dir() and not any(f for f in sub.iterdir() if f.name != '.DS_Store'):
            shutil.rmtree(sub, ignore_errors=True)
    library['playlists'] = written


# --- Summary for the app ---

def summary():
    config = config_store.load_config()
    library = load_library()
    plan = load_plan()
    hidden = safe_name(config['non_liked']['folder'])
    genre_folders = [safe_name(p['name']) for p in config['playlists']]

    folders = {name: 0 for name in genre_folders}
    failed, removed = [], []
    for track_id, record in library['tracks'].items():
        if record['folder'] == hidden:
            continue  # Non-Liked Songs are only visible in the music folder
        if record['status'] == 'ok' and record['folder'] in folders:
            folders[record['folder']] += 1
        elif record['status'] == 'failed':
            failed.append({'track_id': track_id, **record})
        elif record['status'] == 'removed':
            removed.append({'track_id': track_id, **record})

    pending = None
    if plan:
        visible = lambda tid: plan['desired'].get(tid) != hidden
        pending = {
            'generated_at': plan['generated_at'],
            'to_download': sum(1 for t in plan['to_download'] if visible(t)),
            'to_move': len(plan['to_move']),
            'to_remove': len(plan['to_remove']),
            'pending_liked': plan['pending_liked'],
            'playlists': len(plan['playlists']),
        }
    return {
        'playlist_names': {pid: info['name'] for pid, info in (plan or {}).get('playlists', {}).items()},
        'music_dir': str(music_root(config)),
        'folders': [{'name': k, 'count': v} for k, v in folders.items()],
        'downloaded': sum(folders.values()),
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
    if not duration:
        return candidates[0] if len(candidates) == 1 else None
    gaps = sorted((abs(info[c]['duration'] - duration), c) for c in candidates)
    if gaps[0][0] > MAX_DURATION_GAP:
        return None
    # Same artist and title: the same song released twice (single and album), take the closest.
    return gaps[0][1]


def import_files(sp, progress=None, source='', mode='copy'):
    """Put already downloaded files where the current Spotify playlists say they belong."""
    progress = progress or (lambda **kw: None)
    source = Path(os.path.expanduser(source))
    if not source.is_dir():
        raise ValueError(f'Folder not found: {source}')

    plan = build_plan(sp, progress)
    config = config_store.load_config()
    root = music_root(config)
    library = load_library()
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


def load_import_result():
    if IMPORT_RESULT_PATH.exists():
        return json.loads(IMPORT_RESULT_PATH.read_text(encoding='utf-8'))
    return None
