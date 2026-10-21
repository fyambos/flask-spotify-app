"""Keep Apple Music (macOS Music app) in line with the local library.

- adds the downloaded songs to the Music library (once), and fixes their location after a move
- writes every playlist in Spotify order, reusing the Apple Music playlist with the same
  name (it keeps its cover and folder); missing ones are created (genre playlists in
  the "Genres" folder if it exists, the others at the top level)
- puts each playlist in its folder (Settings > Folders, "Music Sorter" by default) and
  removes the folders it no longer uses once they are empty
- removes from Apple Music the songs that are no longer in the local library

Uses AppleScript (osascript). macOS asks once for permission to control Music.
Works whether or not Music copies the files to its own folder: the location of each
song is updated after a move.
"""
import platform
import re
import subprocess
import unicodedata
import tempfile
from pathlib import Path

import config_store
from errors import AppError, log
import library

GENRES_FOLDER = 'Genres'


def available():
    return platform.system() == 'Darwin'


def _run(script, data):
    """Run an AppleScript that reads one argument: a file with tab-separated lines."""
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(data)
        data_path = f.name
    with tempfile.NamedTemporaryFile('w', suffix='.applescript', delete=False, encoding='utf-8') as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(['osascript', script_path, data_path], capture_output=True, text=True, timeout=3600)
    finally:
        Path(data_path).unlink(missing_ok=True)
        Path(script_path).unlink(missing_ok=True)
    if result.returncode != 0:
        log.warning('Apple Music: %s', result.stderr.strip())
        raise AppError('apple_not_responding')
    return result.stdout


# One line per song: <spotify id> TAB <persistent id or empty> TAB <POSIX path>
# Prints one line per song: <spotify id> TAB <persistent id>
ADD_TRACKS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    set out to ""
    tell application "Music"
        repeat with l in lines_
            if l as text is not "" then
                set AppleScript's text item delimiters to tab
                set parts to text items of (l as text)
                set AppleScript's text item delimiters to ""
                set sid to item 1 of parts
                set pid to item 2 of parts
                set p to item 3 of parts
                set t to missing value
                if pid is not "" then
                    try
                        set t to (first track of library playlist 1 whose persistent ID is pid)
                        set location of t to (POSIX file p)
                        -- Apple Music sometimes keeps no location: the track is dead, it is added again.
                        if location of t is missing value then
                            delete t
                            set t to missing value
                        end if
                    on error
                        set t to missing value
                    end try
                end if
                if t is missing value then
                    try
                        set t to add (POSIX file p)
                    end try
                end if
                if t is not missing value then set out to out & sid & tab & (persistent ID of t) & linefeed
            end if
        end repeat
    end tell
    return out
end run
'''

# Prints one line per file track, in library order: <persistent id> TAB <POSIX path or empty>
LIST_FILE_TRACKS = r'''
on run argv
    tell application "Music"
        set ids to persistent ID of every file track of library playlist 1
        set locs to location of every file track of library playlist 1
    end tell
    set out to ""
    repeat with i from 1 to count of ids
        set l to item i of locs
        set p to ""
        if l is not missing value then
            try
                set p to POSIX path of l
            end try
        end if
        set out to out & (item i of ids) & tab & p & linefeed
    end repeat
    return out
end run
'''

# Lines: playlist persistent ids. Prints <playlist id> TAB <track ids separated by commas>.
LIST_PLAYLIST_TRACKS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    set out to ""
    tell application "Music"
        repeat with l in lines_
            if l as text is not "" then
                try
                    set pl to (first user playlist whose persistent ID is (l as text))
                    set ids to {}
                    try
                        set ids to persistent ID of every track of pl
                    end try
                    set par to ""
                    try
                        set par to name of parent of pl
                    end try
                    set AppleScript's text item delimiters to ","
                    set out to out & (l as text) & tab & (ids as text) & tab & par & linefeed
                    set AppleScript's text item delimiters to ""
                end try
            end if
        end repeat
    end tell
    return out
end run
'''

# Prints one line per playlist: <persistent id> TAB <name> TAB <parent folder or empty> TAB <class> TAB <special kind>
LIST_PLAYLISTS = r'''
on run argv
    set out to ""
    tell application "Music"
        repeat with p in (every playlist)
            try
                set par to name of parent of p
            on error
                set par to ""
            end try
            set out to out & (persistent ID of p) & tab & (name of p) & tab & par & tab & ((class of p) as text) & tab & ((special kind of p) as text) & linefeed
        end repeat
    end tell
    return out
end run
'''

# Lines: names of folders to delete if they are empty.
DELETE_EMPTY_FOLDERS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    tell application "Music"
        repeat with l in lines_
            set n to l as text
            if n is not "" and (exists folder playlist n) then
                set used to false
                repeat with p in (every playlist)
                    try
                        if name of parent of p is n then set used to true
                    end try
                end repeat
                if not used then delete folder playlist n
            end if
        end repeat
    end tell
end run
'''

# Lines: "P" TAB <spotify id> TAB <apple persistent id or empty> TAB <folder or empty> TAB <name> TAB <song count>
#        followed by "T" TAB <track persistent id> lines, in order.
#        "D" TAB <apple persistent id>: a playlist of the app that is no longer downloaded, deleted.
# Existing playlists are emptied and filled again (they keep their cover), and moved to
# their folder. Playlists without songs are deleted, not created.
# Prints "C" TAB <spotify id> TAB <persistent id> for each playlist it creates, and
# "N" TAB <spotify id> TAB <song count> once each playlist is filled, to check it.
WRITE_PLAYLISTS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    set out to ""
    tell application "Music"
        set pl to missing value
        set sid to ""
        -- Tracks are taken by their position in this list (given by the "T" lines), not searched.
        set allTracks to every file track of library playlist 1
        set useIndex to false
        repeat with l in (lines_ & {"END"})
            set l to l as text
            if l is not "" then
                set AppleScript's text item delimiters to tab
                set parts to text items of l
                set AppleScript's text item delimiters to ""
                if (item 1 of parts is "P" or item 1 of parts is "END") and pl is not missing value then
                    set out to out & "N" & tab & sid & tab & (count of tracks of pl) & linefeed
                end if
                if item 1 of parts is "INDEX" then
                    set useIndex to ((count of allTracks) = ((item 2 of parts) as integer))
                else if item 1 of parts is "D" then
                    try
                        delete (first user playlist whose persistent ID is (item 2 of parts))
                    end try
                    set pl to missing value
                else if item 1 of parts is "P" then
                    set sid to item 2 of parts
                    set pid to item 3 of parts
                    set folderName to item 4 of parts
                    set playlistName to item 5 of parts
                    set songCount to (item 6 of parts) as integer
                    set pl to missing value
                    if pid is not "" then
                        try
                            set pl to (first user playlist whose persistent ID is pid)
                        end try
                    end if
                    if songCount is 0 then
                        if pl is not missing value then delete pl
                        set pl to missing value
                    else
                        if folderName is not "" and not (exists folder playlist folderName) then
                            make new folder playlist with properties {name:folderName}
                        end if
                        if pl is missing value then
                            if folderName is not "" then
                                set pl to make new user playlist at folder playlist folderName with properties {name:playlistName}
                            else
                                set pl to make new user playlist with properties {name:playlistName}
                            end if
                            set out to out & "C" & tab & sid & tab & (persistent ID of pl) & linefeed
                        else
                            -- Emptied until nothing is left: one delete does not always remove every track.
                            repeat 5 times
                                if (count of tracks of pl) is 0 then exit repeat
                                delete every track of pl
                            end repeat
                            if folderName is not "" then
                                set currentFolder to ""
                                try
                                    set currentFolder to name of parent of pl
                                end try
                                if currentFolder is not folderName then move pl to folder playlist folderName
                            end if
                        end if
                    end if
                else if item 1 of parts is "T" and pl is not missing value then
                    -- Retried once; a refusal is reported with Apple Music's own message.
                    set tr to missing value
                    if useIndex and (count of parts) > 2 then
                        try
                            set tr to item ((item 3 of parts) as integer) of allTracks
                            if persistent ID of tr is not (item 2 of parts) then set tr to missing value
                        end try
                    end if
                    try
                        if tr is not missing value then
                            duplicate tr to pl
                        else
                            duplicate (first file track of library playlist 1 whose persistent ID is (item 2 of parts)) to pl
                        end if
                    on error
                        try
                            delay 0.5
                            duplicate (first file track of library playlist 1 whose persistent ID is (item 2 of parts)) to pl
                        on error errorText
                            set out to out & "E" & tab & sid & tab & (item 2 of parts) & tab & errorText & linefeed
                        end try
                    end try
                end if
            end if
        end repeat
    end tell
    return out
end run
'''

# Lines: "INDEX" TAB <number of file tracks>, "R" TAB <playlist persistent id>, then "X" TAB <position>
# (entries to remove, highest first) and "A" TAB <track persistent id> TAB <its position in the file tracks>
# (songs to add at the end).
REPAIR_PLAYLISTS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    tell application "Music"
        set pl to missing value
        set allTracks to every file track of library playlist 1
        set useIndex to false
        repeat with l in lines_
            set l to l as text
            if l is not "" then
                set AppleScript's text item delimiters to tab
                set parts to text items of l
                set AppleScript's text item delimiters to ""
                try
                    if item 1 of parts is "INDEX" then
                        set useIndex to ((count of allTracks) = ((item 2 of parts) as integer))
                    else if item 1 of parts is "R" then
                        set pl to (first user playlist whose persistent ID is (item 2 of parts))
                    else if item 1 of parts is "X" and pl is not missing value then
                        delete track ((item 2 of parts) as integer) of pl
                    else if item 1 of parts is "A" and pl is not missing value then
                        set tr to missing value
                        if useIndex and (count of parts) > 2 then
                            try
                                set tr to item ((item 3 of parts) as integer) of allTracks
                                if persistent ID of tr is not (item 2 of parts) then set tr to missing value
                            end try
                        end if
                        if tr is missing value then set tr to (first file track of library playlist 1 whose persistent ID is (item 2 of parts))
                        duplicate tr to pl
                    end if
                end try
            end if
        end repeat
    end tell
end run
'''

# Lines: <persistent id> of tracks whose file was replaced (same place): Apple Music reads it again.
REFRESH_TRACKS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    tell application "Music"
        repeat with l in lines_
            if l as text is not "" then
                try
                    refresh (first file track of library playlist 1 whose persistent ID is (l as text))
                end try
            end if
        end repeat
    end tell
end run
'''

# Lines: <persistent id> of songs to remove from Apple Music.
REMOVE_TRACKS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    tell application "Music"
        repeat with l in lines_
            if l as text is not "" then
                try
                    delete (first track of library playlist 1 whose persistent ID is (l as text))
                end try
            end if
        end repeat
    end tell
end run
'''


def _playlist_tracks(playlist_ids):
    """{playlist: ([track ids], folder name)} of the given playlists."""
    result = {}
    for line in (_run(LIST_PLAYLIST_TRACKS, '\n'.join(playlist_ids)).splitlines() if playlist_ids else []):
        pid, ids, parent = (line.split('\t') + ['', ''])[:3]
        result[pid.strip()] = ([i for i in ids.strip().split(',') if i], parent.strip())
    return result


def _settled(playlist_ids, wait=30):
    """{playlist: [track ids]} once Apple Music stopped adding to them: the same twice, one second apart."""
    import time
    previous, deadline = None, time.time() + wait
    while True:
        current = {pid: ids for pid, (ids, _) in _playlist_tracks(playlist_ids).items()}
        if current == previous or time.time() > deadline:
            return current
        previous = current
        time.sleep(1)


def _file_tracks():
    """[(persistent id, path)] of the file tracks, in Apple Music's own order."""
    rows = []
    for line in _run(LIST_FILE_TRACKS, '').splitlines():
        pid, _, path = line.partition('\t')
        if pid:
            rows.append((pid.strip(), path))
    return rows


def _nfc(path):
    import unicodedata
    return unicodedata.normalize('NFC', path or '')


def _existing_playlists():
    """[(persistent id, name, parent)] of the user playlists, except system ones and the old folder."""
    result = []
    for line in _run(LIST_PLAYLISTS, '').splitlines():
        parts = line.split('\t')
        if len(parts) >= 5 and parts[3] == 'user playlist' and parts[4] in ('none', 'missing value', ''):
            result.append((parts[0], parts[1], parts[2]))
    return result


def _strip(name):
    return name.strip(library.INVISIBLE + ' ').lower()


def _core(name):
    """Letters and digits only: '𐙚⋆.˚ gallery' and 'gallery' are the same playlist."""
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD', name.lower()).encode('ascii', 'ignore').decode())


def _find_playlist(spotify_id, name, links, existing):
    """The Apple Music playlist to reuse for a Spotify playlist: linked before, else same name."""
    pids = {pid for pid, _, _ in existing}
    if links.get(spotify_id) in pids:
        return links[spotify_id]
    taken = {pid for sid, pid in links.items() if sid != spotify_id}
    for pid, apple_name, _ in existing:
        if apple_name == name and pid not in taken:
            return pid
    for pid, apple_name, _ in existing:
        if _strip(apple_name) == _strip(name) and pid not in taken:
            return pid
    for pid, apple_name, _ in existing:
        if _core(name) and _core(apple_name) == _core(name) and pid not in taken:
            return pid
    return ''


def update(sp=None, progress=None):
    """Bring Apple Music in line with the local library and the playlists of the last sync."""
    progress = progress or (lambda **kw: None)
    if not available():
        raise RuntimeError('Apple Music is only available on macOS.')
    # Two updates at once (even from two backends) each empty a playlist, then each fill it:
    # every song ends up twice. A lock on a file makes them wait for each other.
    import fcntl
    with open(config_store.DATA_DIR / 'apple-music.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _update(progress)


def _update(progress):
    config = config_store.load_config()
    root = library.music_root(config)
    lib = library.load_library()
    plan = library.load_plan()
    if not plan:
        raise AppError('sync_first')
    tracks = lib['tracks']

    progress(step='Adding songs to Apple Music')
    ok = {tid: r for tid, r in tracks.items() if r['status'] == 'ok' and r.get('path')}
    # Only songs that are new or moved are sent: the others are already right in Apple Music. Where
    # Apple Music has each file is remembered ('apple_path'): reading it for 1800 tracks takes seconds.
    file_list = {}

    def file_tracks():
        if 'rows' not in file_list:
            file_list['rows'] = _file_tracks()
        return file_list['rows']

    if any(r.get('apple_id') and 'apple_path' not in r for r in ok.values()):
        current = dict(file_tracks())  # once, for songs added before their place was remembered
        for r in ok.values():
            if r.get('apple_id') and 'apple_path' not in r:
                r['apple_path'] = _nfc(current.get(r['apple_id']) or '')
    lines = [f"{tid}\t{r.get('apple_id', '')}\t{root / r['path']}" for tid, r in ok.items()
             if not r.get('apple_id') or r.get('apple_path') != _nfc(str(root / r['path']))]
    for line in (_run(ADD_TRACKS, '\n'.join(lines)).splitlines() if lines else []):
        if '\t' in line:
            tid, pid = line.split('\t', 1)
            if tid in tracks:
                tracks[tid]['apple_id'] = pid.strip()
                tracks[tid]['apple_path'] = _nfc(str(root / tracks[tid]['path']))
    if lines:
        file_list.clear()
        # Songs sharing one file (two Spotify ids) share its track and its place.
        placed = {r['apple_id']: r['apple_path'] for r in ok.values() if r.get('apple_id') and r.get('apple_path')}
        for r in ok.values():
            if r.get('apple_id') in placed and r.get('apple_path') != placed[r['apple_id']] \
                    and placed[r['apple_id']] == _nfc(str(root / r['path'])):
                r['apple_path'] = placed[r['apple_id']]
    library.save_library(lib)

    # A file replaced at the same place (another version, a better quality): Apple Music keeps what it
    # read the first time (length, bitrate) and the iPhone keeps the old copy, until the file is read again.
    changed = []
    for r in ok.values():
        if not r.get('apple_id'):
            continue
        try:
            stat = (root / r['path']).stat()
        except OSError:
            continue
        stamp = [stat.st_size, int(stat.st_mtime)]
        if r.get('apple_file') not in (None, stamp) and r['apple_id'] not in changed:
            changed.append(r['apple_id'])
        r['apple_file'] = stamp
    if changed:
        _run(REFRESH_TRACKS, '\n'.join(changed))
    library.save_library(lib)

    progress(step='Removing songs no longer in the library')
    # Songs no longer downloaded, and tracks of duplicate files that went to the Trash.
    gone = [r['apple_id'] for r in tracks.values() if r['status'] != 'ok' and r.get('apple_id')]
    gone += lib.pop('apple_remove', [])
    if gone:
        _run(REMOVE_TRACKS, '\n'.join(gone))
        for r in tracks.values():
            if r['status'] != 'ok':
                r.pop('apple_id', None)
                r.pop('apple_path', None)
        file_list.clear()
        library.save_library(lib)

    progress(step='Writing playlists in Apple Music')
    index = {}

    def position():
        """Place of each track in Apple Music's list, to take it without a search among every track."""
        if not index:
            index.update({pid: i for i, (pid, _) in enumerate(file_tracks(), 1)})
        return index

    links = lib.setdefault('apple_playlists', {})
    genre_ids = {p['playlist_id'] for p in config['playlists']}
    folders = dict(config.get('playlist_folders') or {})
    default = config.get('default_folder') or ''
    counts_ok, wanted_ids = {}, {}
    lines, expected = [], {}
    # Playlists already right in Apple Music (same songs, same order, same folder) are left as they are.
    linked = [links[sid] for sid in plan['playlists'] if links.get(sid)]
    read = _playlist_tracks(linked)
    contents = {pid: ids for pid, (ids, _) in read.items()}
    parents = {pid: parent for pid, (_, parent) in read.items()}
    # Every playlist of Apple Music is listed only for playlists not linked yet (or deleted by hand).
    existing = _existing_playlists() if any(not links.get(sid) or links[sid] not in read for sid in plan['playlists']) else []
    parents.update({pid: parent for pid, _, parent in existing})
    # Playlists of the app that are no longer downloaded are removed from Apple Music
    # (playlists the app never wrote are not touched).
    for spotify_id in [sid for sid in links if sid not in plan['playlists']]:
        lines.append(f'D\t{links.pop(spotify_id)}')
    for spotify_id, info in plan['playlists'].items():
        # Two Spotify ids (single and album) can share one file: it is added once.
        ids = list(dict.fromkeys(tracks[t]['apple_id'] for t in info['track_ids'] if tracks.get(t, {}).get('apple_id')))
        expected[spotify_id] = len(ids)
        wanted_ids[spotify_id] = ids
        pid = links[spotify_id] if links.get(spotify_id) in read else _find_playlist(spotify_id, info['name'], links, existing)
        if spotify_id not in folders:
            # First time: keep the folder the playlist already has in Apple Music.
            folders[spotify_id] = parents.get(pid) or (GENRES_FOLDER if spotify_id in genre_ids else '')
        target = folders[spotify_id] or default
        # The same songs in another order are left as they are: Apple Music can only add at the end.
        if pid and ids and sorted(contents.get(pid) or []) == sorted(ids) and (parents.get(pid) or '') == target:
            counts_ok[spotify_id] = len(ids)
            links[spotify_id] = pid
            continue
        if pid and ids and pid in contents and (parents.get(pid) or '') == target:
            # Already there: only the songs removed and added are changed below (emptying and
            # filling it again took minutes for one song, and Apple Music's late adds doubled it).
            links[spotify_id] = pid
            continue
        lines.append(f"P\t{spotify_id}\t{pid}\t{target}\t{info['name']}\t{len(ids)}")
        lines.extend(f'T\t{track}\t{position().get(track, 0)}' for track in ids)
        if pid:
            links[spotify_id] = pid
    config_store.update_settings({'playlist_folders': folders})
    counts, refused = dict(counts_ok), []

    def write(script_lines):
        for line in _run(WRITE_PLAYLISTS, '\n'.join(script_lines)).splitlines():
            parts = line.split('\t')
            if len(parts) == 3 and parts[0] == 'C':
                links[parts[1]] = parts[2].strip()
            elif len(parts) == 3 and parts[0] == 'N':
                counts[parts[1]] = int(parts[2])
            elif len(parts) >= 4 and parts[0] == 'E':
                refused.append(f"{plan['playlists'].get(parts[1], {}).get('name', parts[1])}: {parts[2]} ({parts[3]})")

    if lines:
        write([f'INDEX\t{len(position())}'] + lines if any(l.startswith('T\t') for l in lines) else lines)
    # Apple Music adds songs with a delay and sometimes drops one or adds one twice, without an error.
    # Each changed playlist is read once Apple Music is done with it, then repaired: entries that are
    # extra or twice are removed, missing songs are added at the end.
    written = [sid for sid in expected if sid not in counts_ok and links.get(sid)]
    wanted = {sid: wanted_ids[sid] for sid in written}
    for attempt in range(3):
        if not wanted:
            break
        actual = _settled({links[sid] for sid in wanted})
        repair = []
        for sid, ids in wanted.items():
            got = actual.get(links[sid], [])
            counts[sid] = len(set(got) & set(ids))
            keep, extra = set(), []
            for position_, track in enumerate(got, 1):
                if track in ids and track not in keep:
                    keep.add(track)
                else:
                    extra.append(position_)
            missing = [t for t in ids if t not in keep]
            if extra or missing:
                repair.append(f'R\t{links[sid]}')
                repair += [f'X\t{p}' for p in sorted(extra, reverse=True)]
                repair += [f'A\t{track}' for track in missing]
            else:
                counts[sid] = len(ids)
        if not repair:
            break
        adds = sum(line.startswith('A\t') for line in repair)
        if adds > 50:
            # Many songs to add: each is taken by its place in the list instead of being searched.
            repair = [f'INDEX\t{len(position())}'] + [
                f'{line}\t{position().get(line[2:], 0)}' if line.startswith('A\t') else line for line in repair]
        _run(REPAIR_PLAYLISTS, '\n'.join(repair))
    used = {folders.get(sid) or default for sid in plan['playlists']} - {''}
    unused = set(lib.get('apple_folders_used', [])) - used
    if unused:
        _run(DELETE_EMPTY_FOLDERS, '\n'.join(unused))
    lib['apple_folders_used'] = sorted(used)
    library.save_library(lib)

    wrong = [f"{plan['playlists'][sid]['name']} ({n} songs instead of {expected[sid]})"
             for sid, n in counts.items() if sid in expected and n != expected[sid]]
    if refused:
        (config_store.DATA_DIR / 'apple-music-refused.txt').write_text('\n'.join(refused), encoding='utf-8')
    if wrong:
        raise AppError('apple_incomplete', playlists=', '.join(wrong))
    progress(step='Done')
    return {'songs': sum(1 for r in tracks.values() if r.get('apple_id')), 'playlists': len(links)}
