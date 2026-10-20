"""Keep Apple Music (macOS Music app) in line with the local library.

- adds the downloaded songs to the Music library (once), and fixes their location after a move
- writes every playlist in Spotify order, reusing the Apple Music playlist with the same
  name (it keeps its cover and folder); missing ones are created (genre playlists in
  the "Genres" folder if it exists, the others at the top level)
- removes the "Music Sorter" folder made by earlier versions
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
import library

OLD_FOLDER = 'Music Sorter'
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
        raise RuntimeError(result.stderr.strip() or 'Apple Music did not respond')
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

DELETE_OLD_FOLDER = r'''
on run argv
    tell application "Music"
        if exists folder playlist "''' + OLD_FOLDER + r'''" then delete folder playlist "''' + OLD_FOLDER + r'''"
    end tell
end run
'''

# Lines: "P" TAB <spotify id> TAB <apple persistent id or empty> TAB <folder for a new playlist or empty> TAB <name>
#        followed by "T" TAB <track persistent id> lines, in order.
# Existing playlists are emptied and filled again (they keep their cover and folder).
# Prints "C" TAB <spotify id> TAB <persistent id> for each playlist it creates.
WRITE_PLAYLISTS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    set out to ""
    tell application "Music"
        set pl to missing value
        repeat with l in lines_
            set l to l as text
            if l is not "" then
                set AppleScript's text item delimiters to tab
                set parts to text items of l
                set AppleScript's text item delimiters to ""
                if item 1 of parts is "P" then
                    set sid to item 2 of parts
                    set pid to item 3 of parts
                    set folderName to item 4 of parts
                    set playlistName to item 5 of parts
                    set pl to missing value
                    if pid is not "" then
                        try
                            set pl to (first user playlist whose persistent ID is pid)
                        end try
                    end if
                    if pl is missing value then
                        if folderName is not "" and (exists folder playlist folderName) then
                            set pl to make new user playlist at folder playlist folderName with properties {name:playlistName}
                        else
                            set pl to make new user playlist with properties {name:playlistName}
                        end if
                        set out to out & "C" & tab & sid & tab & (persistent ID of pl) & linefeed
                    else
                        delete every track of pl
                    end if
                else if item 1 of parts is "T" and pl is not missing value then
                    try
                        duplicate (first track of library playlist 1 whose persistent ID is (item 2 of parts)) to pl
                    end try
                end if
            end if
        end repeat
    end tell
    return out
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


def _existing_playlists():
    """[(persistent id, name, parent)] of the user playlists, except system ones and the old folder."""
    result = []
    for line in _run(LIST_PLAYLISTS, '').splitlines():
        parts = line.split('\t')
        if (len(parts) >= 5 and parts[3] == 'user playlist' and parts[4] in ('none', 'missing value', '')
                and parts[2] != OLD_FOLDER):
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
    config = config_store.load_config()
    root = library.music_root(config)
    lib = library.load_library()
    plan = library.load_plan()
    if not plan:
        raise RuntimeError('Run Check or Sync on the Library page first.')
    tracks = lib['tracks']

    progress(step='Adding songs to Apple Music')
    ok = {tid: r for tid, r in tracks.items() if r['status'] == 'ok' and r.get('path')}
    lines = [f"{tid}\t{r.get('apple_id', '')}\t{root / r['path']}" for tid, r in ok.items()]
    for line in _run(ADD_TRACKS, '\n'.join(lines)).splitlines():
        if '\t' in line:
            tid, pid = line.split('\t', 1)
            if tid in tracks:
                tracks[tid]['apple_id'] = pid.strip()
    library.save_library(lib)

    progress(step='Removing songs no longer in the library')
    gone = [r['apple_id'] for r in tracks.values() if r['status'] != 'ok' and r.get('apple_id')]
    if gone:
        _run(REMOVE_TRACKS, '\n'.join(gone))
        for r in tracks.values():
            if r['status'] != 'ok':
                r.pop('apple_id', None)
        library.save_library(lib)

    progress(step='Removing the old Music Sorter folder')
    _run(DELETE_OLD_FOLDER, '')

    progress(step='Writing playlists in Apple Music')
    existing = _existing_playlists()
    links = lib.setdefault('apple_playlists', {})
    genre_ids = {p['playlist_id'] for p in config['playlists']}
    lines = []
    for spotify_id, info in plan['playlists'].items():
        ids = [tracks[t]['apple_id'] for t in info['track_ids'] if tracks.get(t, {}).get('apple_id')]
        pid = _find_playlist(spotify_id, info['name'], links, existing)
        folder = GENRES_FOLDER if spotify_id in genre_ids else ''
        lines.append(f"P\t{spotify_id}\t{pid}\t{folder}\t{info['name']}")
        lines.extend(f'T\t{track}' for track in ids)
        if pid:
            links[spotify_id] = pid
    for line in _run(WRITE_PLAYLISTS, '\n'.join(lines)).splitlines():
        parts = line.split('\t')
        if len(parts) == 3 and parts[0] == 'C':
            links[parts[1]] = parts[2].strip()
    library.save_library(lib)

    progress(step='Done')
    return {'songs': sum(1 for r in tracks.values() if r.get('apple_id')), 'playlists': len(links)}
