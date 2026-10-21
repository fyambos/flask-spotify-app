"""Duplicates in your Spotify playlists: a song added twice, or two versions of one song.

Only your own playlists and Liked Songs. Two versions are the same song by the library's rule
(same main artist, same title without edition words, same length): a live, a remix or a slowed
version is never one. The album version is kept rather than the single or a compilation, the
original rather than a remaster, then the one added first. Nothing changes on Spotify until
the user asks; "Keep both" is remembered.
"""
import json
import re
from collections import Counter, defaultdict

import catalog as catalog_store
import library
from config_store import DATA_DIR

KEPT_PATH = DATA_DIR / 'spotify-duplicates-kept.json'
ALBUM_RANK = {'album': 0, 'single': 1, 'compilation': 2}
REMASTER = re.compile(r'remaster', re.IGNORECASE)


def _kept():
    try:
        return set(json.loads(KEPT_PATH.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return set()


def keep_both(key):
    kept = _kept() | {key}
    KEPT_PATH.write_text(json.dumps(sorted(kept), ensure_ascii=False), encoding='utf-8')


def _rank(track, position):
    """Lower is kept: original before remaster, album before single before compilation, then first added."""
    album = track.get('album') or {}
    remaster = bool(REMASTER.search(track.get('name') or '') or REMASTER.search(album.get('name') or ''))
    return remaster, ALBUM_RANK.get(album.get('album_type'), 1), position


def _song(track):
    album = track.get('album') or {}
    images = sorted(album.get('images') or [], key=lambda i: i.get('width') or 0)
    return {'id': track['id'], 'title': track['name'],
            'artist': ', '.join(a['name'] for a in track.get('artists') or [] if a.get('name')),
            'album': album.get('name'), 'album_type': album.get('album_type'),
            'image': images[0]['url'] if images else None}


def find(catalog=None):
    """[{key, playlist_id, playlist, kind ('twice' or 'versions'), keep, remove: [songs]}]."""
    catalog = catalog or catalog_store.load()
    if catalog.get('source') != 'spotify':
        return []
    kept, tracks, result = _kept(), catalog['tracks'], []
    for pid, playlist in catalog['playlists'].items():
        ids = playlist.get('track_ids') or []
        # Only playlists you can change, read song by song (others only have their size).
        if not playlist.get('owned') or len(ids) != playlist.get('total', len(ids)):
            continue
        for tid, n in Counter(ids).items():
            key = f'{pid}:twice:{tid}'
            if n > 1 and tid in tracks and key not in kept:
                result.append({'key': key, 'playlist_id': pid, 'playlist': playlist['name'], 'kind': 'twice',
                               'keep': _song(tracks[tid]), 'remove': []})
        songs = defaultdict(list)
        for position, tid in enumerate(dict.fromkeys(ids)):
            track = tracks.get(tid)
            if track and track.get('name') and track.get('artists'):
                info = library._track_info(track)
                songs[library.song_key(info['artists'], info['title'])].append((tid, info['duration'], position))
        for versions in songs.values():
            if len(versions) < 2 or not all(library.same_recording(versions[0][1], d) for _, d, _ in versions[1:]):
                continue
            ordered = sorted(versions, key=lambda v: _rank(tracks[v[0]], v[2]))
            key = f"{pid}:versions:{','.join(sorted(v[0] for v in versions))}"
            if key not in kept:
                result.append({'key': key, 'playlist_id': pid, 'playlist': playlist['name'], 'kind': 'versions',
                               'keep': _song(tracks[ordered[0][0]]), 'remove': [_song(tracks[v[0]]) for v in ordered[1:]]})
    return result


def remove(sp, progress, keys):
    """Remove the duplicates the user saw (keys), as they are on Spotify now."""
    from spotify_client import add_to_playlist, remove_from_playlist, unlike_tracks

    catalog = catalog_store.refresh_from_spotify(sp, progress)
    wanted = [d for d in find(catalog) if d['key'] in set(keys)]
    by_playlist = defaultdict(list)
    for duplicate in wanted:
        by_playlist[duplicate['playlist_id']].append(duplicate)
    for i, (pid, duplicates) in enumerate(by_playlist.items(), 1):
        progress(step=f"Removing duplicates from {duplicates[0]['playlist']}", done=i, total=len(by_playlist))
        losers = {song['id'] for d in duplicates for song in d['remove']}
        if pid == catalog_store.LIKED_ID:
            unlike_tracks(sp, sorted(losers))
            continue
        twice = {d['keep']['id'] for d in duplicates if d['kind'] == 'twice'}
        # Spotify removes every copy of a song: the songs added twice are put back once, at their first place.
        final, seen = [], set()
        for tid in catalog['playlists'][pid]['track_ids']:
            if tid not in losers and not (tid in twice and tid in seen):
                final.append(tid)
            seen.add(tid)
        remove_from_playlist(sp, pid, sorted(losers | twice))
        for position, tid in enumerate(final):
            if tid in twice:
                add_to_playlist(sp, pid, [tid], position=position)
    progress(step='Reading your playlists')
    catalog_store.refresh_from_spotify(sp, progress)
