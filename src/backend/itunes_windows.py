"""Keep iTunes for Windows in line with the local library (the Windows counterpart of apple_music.py).

The Apple Music app for Windows can't import playlists and can't be scripted, iTunes can
(COM, "iTunes.Application"). The iPhone then gets the songs and playlists from the iTunes
sync. Installing the Apple Music or Apple Devices app takes the music library away from
iTunes, so they must not be installed for this to work.

- adds the downloaded songs to the iTunes library (once, referenced in place, not copied),
  and points them to their new location after a move
- writes every playlist, reusing the iTunes playlist linked to it before or with the same
  name: it is emptied and filled again in order (a re-imported .m3u8 is ignored by iTunes,
  so .m3u8 files are not used here)
- puts each playlist in its folder (Settings > Folders, "Music Sorter" by default)
- removes from iTunes the songs that are no longer in the local library (files stay on disk)

Needs pywin32. The first launch of iTunes shows a license dialog, COM calls wait until it
is accepted.
"""
import os
import platform

import config_store
from errors import AppError
import library

USER_PLAYLIST = 2   # ITPlaylistKind.ITPlaylistKindUser
FOLDER = 4          # ITUserPlaylistSpecialKind.ITUserPlaylistSpecialKindFolder
FILE_TRACK = 1      # ITTrackKind.ITTrackKindFile


def available():
    if platform.system() != 'Windows':
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def _pid(it, obj):
    """Persistent ID as 16 hex digits (the same form Apple Music shows)."""
    high = it.ITObjectPersistentIDHigh(obj) & 0xFFFFFFFF
    low = it.ITObjectPersistentIDLow(obj) & 0xFFFFFFFF
    return f'{high:08X}{low:08X}'


def _split(pid):
    return int(pid[:8], 16), int(pid[8:], 16)


def _signed(value):
    """COM expects signed 32-bit integers."""
    return value - (1 << 32) if value >= 1 << 31 else value


def _track(it, pid):
    if not pid:
        return None
    try:
        high, low = _split(pid)
        return it.LibraryPlaylist.Tracks.ItemByPersistentID(_signed(high), _signed(low))
    except Exception:
        return None


def _add_file(it, path):
    """Add a file to the library and return its track (AddFile works in the background)."""
    import time
    op = it.LibraryPlaylist.AddFile(str(path))
    if op is None:
        return None
    while op.InProgress:
        time.sleep(0.2)
    tracks = op.Tracks
    return tracks.Item(1) if tracks is not None and tracks.Count else None


def _user_playlists(it):
    """{persistent id: (playlist, name, parent name)} of the user playlists and folders."""
    result = {}
    playlists = it.LibrarySource.Playlists
    for i in range(1, playlists.Count + 1):
        pl = playlists.Item(i)
        if pl.Kind != USER_PLAYLIST:
            continue
        try:
            parent = pl.Parent.Name if pl.Parent is not None else ''
        except Exception:
            parent = ''
        result[_pid(it, pl)] = (pl, pl.Name, parent, getattr(pl, 'SpecialKind', 0))
    return result


def _folder(it, name, existing):
    for pl, pl_name, _, kind in existing.values():
        if kind == FOLDER and pl_name == name:
            return pl
    folder = it.CreateFolder(name)
    existing[_pid(it, folder)] = (folder, name, '', FOLDER)
    return folder


def update(sp=None, progress=None):
    """Bring iTunes in line with the local library and the playlists of the last sync."""
    progress = progress or (lambda **kw: None)
    if not available():
        raise RuntimeError('iTunes is only available on Windows, with pywin32 installed.')
    import pythoncom
    import win32com.client

    import msvcrt
    pythoncom.CoInitialize()
    # Two updates at once each empty a playlist, then each fill it: a lock on a file makes them wait.
    with open(config_store.DATA_DIR / 'itunes.lock', 'w') as lock:
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            it = win32com.client.Dispatch('iTunes.Application')
            return _update(it, progress)
        finally:
            pythoncom.CoUninitialize()


def _update(it, progress):
    config = config_store.load_config()
    root = library.music_root(config)
    lib = library.load_library()
    plan = library.load_plan()
    if not plan:
        raise AppError('sync_first')
    tracks = lib['tracks']

    ok = {tid: r for tid, r in tracks.items() if r['status'] == 'ok' and r.get('path')}
    for i, (tid, record) in enumerate(ok.items(), 1):
        if i % 25 == 0 or i == len(ok):
            progress(step='Adding songs to iTunes', done=i, total=len(ok))
        path = str(root / record['path'])
        track = _track(it, record.get('itunes_id'))
        if track is not None:
            try:
                if (track.Location or '').lower() != path.lower():
                    track.Location = path  # the file moved
                stat = os.stat(path)
                stamp = [stat.st_size, int(stat.st_mtime)]
                if record.get('itunes_file') not in (None, stamp):
                    # Replaced at the same place (another version, a better quality): read again by iTunes.
                    track.UpdateInfoFromFile()
                record['itunes_file'] = stamp
                continue
            except Exception:
                track = None
        track = _add_file(it, path)
        if track is not None:
            record['itunes_id'] = _pid(it, track)
        if i % 100 == 0:
            library.save_library(lib)
    library.save_library(lib)

    progress(step='Removing songs no longer in the library')
    # Tracks of duplicate files that went to the Recycle Bin.
    for pid in lib.pop('itunes_remove', []):
        track = _track(it, pid)
        if track is not None:
            track.Delete()
    for record in tracks.values():
        if record['status'] != 'ok' and record.get('itunes_id'):
            track = _track(it, record['itunes_id'])
            if track is not None:
                track.Delete()  # removes it from iTunes, the file stays on disk
            record.pop('itunes_id', None)
    library.save_library(lib)

    progress(step='Writing playlists in iTunes')
    existing = _user_playlists(it)
    links = lib.setdefault('itunes_playlists', {})
    folders = config.get('playlist_folders') or {}
    default = config.get('default_folder') or ''
    contents = plan['playlists']
    # Playlists of the app that are no longer downloaded are removed from iTunes
    # (playlists the app never wrote are not touched).
    for playlist_id in [sid for sid in links if sid not in contents]:
        pid = links.pop(playlist_id)
        if pid in existing:
            existing.pop(pid)[0].Delete()
    for i, (playlist_id, info) in enumerate(contents.items(), 1):
        progress(step=f"Writing {info['name']} in iTunes", done=i, total=len(contents))
        # Two Spotify ids (single and album) can share one file: it is added once.
        pids = dict.fromkeys(tracks[t]['itunes_id'] for t in info['track_ids'] if tracks.get(t, {}).get('itunes_id'))
        found = [(pid, song) for pid, song in ((pid, _track(it, pid)) for pid in pids) if song is not None]
        songs = [song for _, song in found]
        pl = _find(it, playlist_id, info['name'], links, existing)
        if not songs:
            # Playlists without songs are deleted, not created.
            if pl is not None:
                pl.Delete()
                links.pop(playlist_id, None)
            continue
        folder_name = folders.get(playlist_id) or default
        folder = _folder(it, folder_name, existing) if folder_name else None
        if pl is None:
            pl = folder.CreatePlaylist(info['name']) if folder is not None else it.CreatePlaylist(info['name'])
            pid = _pid(it, pl)
            existing[pid] = (pl, info['name'], folder_name, 0)
        else:
            if folder is not None:
                try:
                    if pl.Parent is None or pl.Parent.Name != folder_name:
                        pl.Parent = folder
                except Exception:
                    pass  # stays where it is
        # Only the songs removed and added are changed: emptying and filling a playlist of 1600 songs
        # took minutes for one song changed. Songs added are put at the end.
        wanted = {pid for pid, _ in found}
        keep, entries = set(), pl.Tracks
        for i in range(entries.Count, 0, -1):  # from the end: deleting while enumerating fails
            entry = entries.Item(i)
            pid = _pid(it, entry)
            if pid in keep or pid not in wanted:
                entry.Delete()  # removed from the playlist only, the song stays in iTunes
            else:
                keep.add(pid)
        for pid, song in found:
            if pid not in keep:
                pl.AddTrack(song)
        links[playlist_id] = _pid(it, pl)
        library.save_library(lib)

    progress(step='Done')
    return {'songs': sum(1 for r in tracks.values() if r.get('itunes_id')), 'playlists': len(links)}


def _find(it, playlist_id, name, links, existing):
    """The iTunes playlist to reuse: linked before, else the same name (not already linked)."""
    pid = links.get(playlist_id)
    if pid in existing:
        return existing[pid][0]
    taken = {p for sid, p in links.items() if sid != playlist_id}
    for pid, (pl, pl_name, _, kind) in existing.items():
        if kind != FOLDER and pid not in taken and pl_name.strip() == name.strip():
            return pl
    return None
