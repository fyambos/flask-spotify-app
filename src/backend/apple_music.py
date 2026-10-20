"""Keep Apple Music (macOS Music app) in line with the local library.

- adds the downloaded songs to the Music library (once), and fixes their location after a move
- writes every playlist into a "Music Sorter" folder in Apple Music, in Spotify order
- removes from Apple Music the songs that are no longer in the local library

Uses AppleScript (osascript). macOS asks once for permission to control Music.
Works whether or not Music copies the files to its own folder: the location of each
song is updated after a move.
"""
import json
import platform
import subprocess
import tempfile
from pathlib import Path

import config_store
import library

FOLDER_NAME = 'Music Sorter'


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

# Lines: "P" TAB <playlist name>, followed by "T" TAB <persistent id> lines, in order.
WRITE_PLAYLISTS = r'''
on run argv
    set lines_ to paragraphs of (read (POSIX file (item 1 of argv)) as «class utf8»)
    tell application "Music"
        if not (exists folder playlist "''' + FOLDER_NAME + r'''") then
            make new folder playlist with properties {name:"''' + FOLDER_NAME + r'''"}
        end if
        set f to folder playlist "''' + FOLDER_NAME + r'''"
        set pl to missing value
        repeat with l in lines_
            set l to l as text
            if l is not "" then
                set kind_ to text 1 of l
                set value_ to text 3 thru -1 of l
                if kind_ is "P" then
                    set pl to missing value
                    repeat with candidate in (user playlists whose name is value_)
                        try
                            if (name of parent of candidate) is "''' + FOLDER_NAME + r'''" then set pl to contents of candidate
                        end try
                    end repeat
                    if pl is missing value then
                        set pl to make new user playlist at f with properties {name:value_}
                    else
                        delete every track of pl
                    end if
                else if kind_ is "T" and pl is not missing value then
                    try
                        duplicate (first track of library playlist 1 whose persistent ID is value_) to pl
                    end try
                end if
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


def update(sp=None, progress=None):
    """Bring Apple Music in line with the local library and the playlists of the last sync."""
    progress = progress or (lambda **kw: None)
    if not available():
        raise RuntimeError('Apple Music is only available on macOS.')
    root = library.music_root(config_store.load_config())
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

    progress(step='Writing playlists in Apple Music')
    lines = []
    for info in plan['playlists'].values():
        ids = [tracks[t]['apple_id'] for t in info['track_ids'] if tracks.get(t, {}).get('apple_id')]
        if ids:
            lines.append(f"P\t{info['name'].strip(library.INVISIBLE + ' ')}")
            lines.extend(f'T\t{pid}' for pid in ids)
    _run(WRITE_PLAYLISTS, '\n'.join(lines))
    progress(step='Done')
    return {'songs': sum(1 for r in tracks.values() if r.get('apple_id'))}
