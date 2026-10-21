"""Stats: what your playlists say about your taste, from whatever the app has.

Spotify, an Exportify or Spotify data export, or a TuneMyMusic file with Last.fm genres: each part
uses what is there and is left out when nothing is. Nothing is asked to Spotify here.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median

import catalog as catalog_store
import config_store
import library
import sort_state
from genres import CACHE_PATH as GENRES_PATH, artist_key


def _genres_cache():
    try:
        return json.loads(GENRES_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _cover(track):
    """The album cover, the smallest that is at least 160 px wide."""
    images = sorted((track.get('album') or {}).get('images') or [], key=lambda i: i.get('width') or 0)
    for image in images:
        if (image.get('width') or 0) >= 160:
            return image['url']
    return images[-1]['url'] if images else track.get('image_url')


def _song(track):
    return {'title': track['name'], 'artist': ', '.join(a['name'] for a in track.get('artists') or [] if a.get('name')),
            'image': _cover(track)}


def _clock(seconds):
    seconds = round(seconds)
    return f'{seconds // 60}:{seconds % 60:02d}'


def scopes():
    """The playlists Stats can look at: those whose songs the app knows."""
    view = sort_state.view(catalog_store.load())
    return [{'id': pid, 'name': p['name']} for pid, p in view['playlists'].items() if p.get('track_ids')]


def compute(playlist_id=None):
    view = sort_state.view(catalog_store.load())
    config = config_store.load_config()
    lib = library.load_library()
    extras = catalog_store.load_extras()
    if playlist_id:
        playlist_ids = [playlist_id] if playlist_id in view['playlists'] else []
    else:
        known = set(library.downloaded_playlists(config, view)) | {catalog_store.LIKED_ID}
        playlist_ids = [pid for pid in view['playlists'] if pid in known]

    # The songs, each once, and when they were first added to one of these playlists.
    added = {}
    order = []
    for pid in playlist_ids:
        playlist = view['playlists'][pid]
        dates = playlist.get('added') or []
        for i, tid in enumerate(playlist['track_ids']):
            if tid not in view['tracks'] or not view['tracks'][tid].get('name'):
                continue
            if tid not in added:
                order.append(tid)
                added[tid] = None
            date = dates[i] if i < len(dates) else None
            if date and (added[tid] is None or date < added[tid]):
                added[tid] = date
    matches = library._Matches().data  # YouTube Music's year and length of songs read from a file
    tracks = []
    for tid in order:
        track = {**view['tracks'][tid], **extras.get(tid, {})}
        found = (matches.get(tid) or {}).get('fields') or {}
        if not track.get('duration_ms'):
            seconds = (lib['tracks'].get(tid) or {}).get('duration') or found.get('duration')
            track['duration_ms'] = seconds * 1000 if seconds else None
        album = track.get('album') or {}
        if not album.get('release_date') and found.get('year'):
            track['album'] = {**album, 'release_date': str(found['year'])}
        if not _cover(track):
            # Songs read from a file: the cover YouTube Music gave, or the one of the downloaded song.
            track['image_url'] = found.get('cover_url') or (lib['tracks'].get(tid) or {}).get('image_url')
        tracks.append(track)

    result = {'songs': len(tracks), 'parts': {}}
    if not tracks:
        return result
    parts = result['parts']

    # 1. In short
    artists = Counter(a['name'] for t in tracks for a in t.get('artists') or [] if a.get('name'))
    seconds = sum((t.get('duration_ms') or 0) / 1000 for t in tracks)
    albums = Counter()
    album_cover = {}
    for t in tracks:
        name = (t.get('album') or {}).get('name')
        if name and _cover(t):
            albums[name] += 1
            album_cover.setdefault(name, _cover(t))
    parts['short'] = {'songs': len(tracks), 'artists': len(artists), 'hours': round(seconds / 3600),
                      'covers': [album_cover[name] for name, _ in albums.most_common(15)]}

    # 2. Your artists
    if artists:
        once = sum(1 for n in artists.values() if n == 1)
        artist_cover = {}
        for t in tracks:
            for a in t.get('artists') or []:
                if a.get('name') and _cover(t):
                    artist_cover.setdefault(a['name'], _cover(t))
        parts['artists'] = {'top': [{'name': name, 'songs': n, 'image': artist_cover.get(name)}
                                    for name, n in artists.most_common(10)],
                            'once': round(100 * once / len(artists))}

    # 3. Your genres: from the export, else from Spotify and Last.fm (the sorting's genres)
    cache = _genres_cache()
    genre_count, curated = Counter(), set()  # curated: Spotify's and Exportify's genres (Last.fm tags are free text)
    for t in tracks:
        genres = list(t.get('genres') or [])
        curated.update(g.lower() for g in genres)
        if not genres:
            for a in t.get('artists') or []:
                entry = cache.get(artist_key(a)) or {}
                genres += entry.get('genres') or []
                curated.update(g.lower() for g in entry.get('spotify') or [])
        genre_count.update(set(g.lower() for g in genres))
    if genre_count:
        rare = sorted(g for g, n in genre_count.items() if n == 1 and g in curated)
        parts['genres'] = {'top': [{'name': g, 'songs': n} for g, n in genre_count.most_common(10)],
                           'rare': rare[:12]}

    # 4. Your years
    dated = [(int(d[:4]), t) for t in tracks if (d := (t.get('album') or {}).get('release_date') or '')[:4].isdigit()]
    if len(dated) >= 10:
        years = sorted(y for y, _ in dated)
        per_year = Counter(years)
        parts['years'] = {
            'per_year': [{'year': y, 'songs': per_year.get(y, 0)} for y in range(years[0], years[-1] + 1)],
            'from': years[len(years) // 5], 'to': years[len(years) * 4 // 5],
            'oldest': [{**_song(t), 'year': y} for y, t in sorted(dated, key=lambda x: x[0])[:5]],
        }

    # 5. When you add songs
    months = Counter(d[:7] for d in added.values() if d)
    if sum(months.values()) >= 10:
        first, last = min(months), max(months)
        timeline, month = [], first
        while month <= last:
            timeline.append({'month': month, 'songs': months.get(month, 0)})
            y, m = int(month[:4]), int(month[5:7]) + 1
            month = f'{y + (m > 12)}-{(m - 1) % 12 + 1:02d}'
        busiest = max(months, key=months.get)
        parts['added'] = {'per_month': timeline, 'busiest': busiest, 'busiest_songs': months[busiest]}

    # 6. Hits or discoveries (Spotify's popularity, 0 to 100; 0 is often "unknown")
    # A copy Spotify replaces by another one in your country keeps a near-zero popularity of its own:
    # the one of the copy it plays is used, or none when that copy is not in your playlists.
    own_popularity = {tid: t.get('popularity') for tid, t in view['tracks'].items() if not t.get('playable_id')}
    for t in tracks:
        if t.get('playable_id'):
            t['popularity'] = own_popularity.get(t['playable_id'])
    popular = [(t['popularity'], t) for t in tracks if t.get('popularity')]
    if len(popular) >= 10:
        parts['popularity'] = {
            'hits': sum(1 for p, _ in popular if p >= 70),
            'known': sum(1 for p, _ in popular if 40 <= p < 70),
            'discoveries': sum(1 for p, _ in popular if p < 40),
            'least_known': [_song(t) for _, t in sorted(popular, key=lambda x: x[0])[:5]],
        }

    # 7. Mood (Spotify's audio features, from Exportify)
    featured = [t for t in tracks if t.get('features')]
    if len(featured) >= 10:
        scales = []
        for key in ('valence', 'energy', 'danceability', 'acousticness'):
            rated = sorted(((t['features'][key], t) for t in featured if key in t['features']), key=lambda x: x[0])
            if rated:
                scales.append({'key': key, 'average': round(mean(v for v, _ in rated), 2),
                               'low': [_song(t) for _, t in rated[:3]],
                               'high': [_song(t) for _, t in rated[-3:][::-1]]})
        modes = [t['features']['mode'] for t in featured if 'mode' in t['features']]
        tempos = [t['features']['tempo'] for t in featured if t['features'].get('tempo')]
        bpm = round(median(tempos)) if tempos else None
        # Every song on a map: how happy (valence) and how energetic.
        points = [[round(t['features']['valence'], 3), round(t['features']['energy'], 3), t['name'],
                   ', '.join(a['name'] for a in t.get('artists') or [] if a.get('name'))]
                  for t in featured if 'valence' in t['features'] and 'energy' in t['features']]
        parts['mood'] = {'scales': scales, 'points': points,
                         'minor': round(100 * sum(1 for m in modes if m == 0) / len(modes)) if modes else None,
                         'bpm': bpm, 'pace': None if bpm is None else 'slow' if bpm < 90 else 'fast' if bpm > 130 else 'medium'}

    # 8. Song length
    timed = [(t['duration_ms'] / 1000, t) for t in tracks if t.get('duration_ms')]
    if timed:
        parts['length'] = {'average': _clock(mean(s for s, _ in timed)),
                           'longest': [{**_song(t), 'length': _clock(s)} for s, t in sorted(timed, key=lambda x: -x[0])[:3]]}

    # 9. What you listen to: the history of a Spotify data export (Spotify's own top tracks: other route)
    if not playlist_id:
        listening = listening_stats()
        if listening:
            parts['listening'] = listening
    return result


def listening_stats():
    try:
        plays = json.loads(catalog_store.LISTENING_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not plays:
        return None
    by_artist = defaultdict(int)
    by_hour = [0] * 24
    for play in plays:
        by_artist[play['artist']] += play['ms']
        try:
            hour = datetime.fromisoformat(play['at'].replace('Z', '+00:00')).hour
        except (AttributeError, ValueError):
            continue
        by_hour[hour] += play['ms']
    top = sorted(by_artist.items(), key=lambda x: -x[1])[:10]
    return {'hours': round(sum(p['ms'] for p in plays) / 3_600_000),
            'top_artists': [{'name': name, 'hours': round(ms / 3_600_000, 1)} for name, ms in top],
            'by_hour': [round(ms / 3_600_000, 1) for ms in by_hour]}
