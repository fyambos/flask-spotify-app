"""Analyse the genres of the tracks already in your genre playlists.

Usage (from src/backend):
    python analyze.py                  # analyse every playlist in data/config.json
    python analyze.py --list-playlists # list your Spotify playlists (name + id)

Writes data/reports/genre-analysis.md and .json. Read-only: nothing is changed on Spotify.
"""
import argparse
import json
from collections import Counter
from datetime import datetime

from dotenv import load_dotenv

from config_store import DATA_DIR, load_config
from genres import GenreResolver, matching_playlists
from spotify_client import create_client, my_playlists, playlist_meta, playlist_tracks

REPORT_DIR = DATA_DIR / 'reports'
TOP_N = 30


def list_playlists(sp):
    for p in my_playlists(sp):
        print(f"{p['id']}  {p['name']}")


def analyse(sp, top_n):
    config = load_config()
    playlists = config['playlists']
    resolver = GenreResolver(sp)
    report = []

    for entry in playlists:
        meta = playlist_meta(sp, entry['playlist_id'])
        label = entry.get('name') or meta['name']
        print(f"\n== {label} (Spotify: {meta['name']}) ==")
        tracks = playlist_tracks(sp, entry['playlist_id'])

        genre_counts, sources = Counter(), Counter()
        own_match, other_match, no_genre = 0, Counter(), []
        for i, track in enumerate(tracks, 1):
            genres = resolver.track_genres(track)
            for artist in track['artists']:
                entry = resolver.cache.get(artist.get('id'))
                if entry:
                    sources['spotify' if entry['spotify'] else 'lastfm' if entry.get('lastfm') else 'none'] += 1
            genre_counts.update(set(genres))
            if not genres:
                no_genre.append(f"{track['artists'][0]['name']} - {track['name']}")
            matches = matching_playlists(genres, playlists)
            if any(m['id'] == entry['id'] for m in matches):
                own_match += 1
            for m in matches:
                if m['id'] != entry['id']:
                    other_match[m.get('name') or m['playlist_id']] += 1
            if i % 50 == 0:
                print(f'  {i}/{len(tracks)} tracks...')
        resolver.save()

        n = len(tracks) or 1
        report.append({
            'name': label,
            'spotify_name': meta['name'],
            'playlist_id': entry['playlist_id'],
            'keywords': entry['genre_names'],
            'track_count': len(tracks),
            'genre_sources': dict(sources),
            'own_keywords_match_pct': round(100 * own_match / n),
            'also_matches_other_playlists': {k: round(100 * v / n) for k, v in other_match.most_common()},
            'top_genres': [(g, c, round(100 * c / n)) for g, c in genre_counts.most_common(top_n)],
            'tracks_without_genre': no_genre,
        })

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / 'genre-analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (REPORT_DIR / 'genre-analysis.md').write_text(to_markdown(report), encoding='utf-8')
    print(f"\nReport written to {REPORT_DIR / 'genre-analysis.md'}")


def to_markdown(report):
    lines = [f"# Genre analysis — {datetime.now():%Y-%m-%d %H:%M}", '']
    for r in report:
        lines += [
            f"## {r['name']} (Spotify: {r['spotify_name']})",
            '',
            f"- Tracks: {r['track_count']}",
            f"- Current keywords: {', '.join(r['keywords']) or '—'}",
            f"- Genre source per artist: {r['genre_sources']}",
            f"- Tracks matched by its own keywords: {r['own_keywords_match_pct']}%",
            f"- Tracks also matched by other playlists: "
            + (', '.join(f'{k} {v}%' for k, v in r['also_matches_other_playlists'].items()) or '—'),
            '',
            '| Genre | Tracks | % |',
            '|---|---|---|',
        ]
        lines += [f'| {g} | {c} | {p}% |' for g, c, p in r['top_genres']]
        if r['tracks_without_genre']:
            lines += ['', f"Without any genre ({len(r['tracks_without_genre'])}):", '']
            lines += [f'- {t}' for t in r['tracks_without_genre']]
        lines.append('')
    return '\n'.join(lines)


if __name__ == '__main__':
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--list-playlists', action='store_true', help='list your Spotify playlists and exit')
    parser.add_argument('--top', type=int, default=TOP_N, help='number of genres shown per playlist')
    args = parser.parse_args()
    sp = create_client()
    if args.list_playlists:
        list_playlists(sp)
    else:
        analyse(sp, args.top)
