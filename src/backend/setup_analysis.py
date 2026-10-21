"""Learn sorting rules from the tracks already in your genre playlists.

Used by the setup assistant and by "Suggest rules" on the Genres page:
1. read the chosen playlists and the genres of their tracks (Spotify + Last.fm)
2. propose rules for each playlist:
   - genres that cover most of its tracks while being rare in the other playlists
   - album keywords shared by many of its tracks ("ost", "original television soundtrack"...)
   - a priority order: most specific playlists first
3. measure how well the proposal re-sorts the tracks already there (each track is
   classified as if it were new), and report where it goes wrong.

Nothing is saved: the proposal goes to data/setup-proposal.json until you accept it.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime

import config_store
from config_store import DATA_DIR
from genres import GenreResolver, matches_any
from sorter import Classifier
import catalog as catalog_store
import sort_state

PROPOSAL_PATH = DATA_DIR / 'setup-proposal.json'
ACCURACY_PATH = DATA_DIR / 'accuracy.json'

MAX_GENRES = 10
MIN_ARTISTS = 3             # a genre or album keyword must be shared by this many different artists
MIN_PRECISION = 0.25        # share of the tracks with the genre that are in this playlist
MIN_LIFT = 1.5              # ...compared to the playlist's share of all tracks
MIN_NEW_COVERAGE = 2        # stop adding genres when one covers fewer new tracks than this
MIN_ALBUM_SHARE = 0.15
MIN_ALBUM_PRECISION = 0.25
MIN_ALBUM_LIFT = 2
MAX_ALBUM_KEYWORDS = 3
ALBUM_STOPWORDS = {
    'the', 'a', 'an', 'of', 'and', 'in', 'on', 'to', 'for', 'from', 'with', 'my', 'your', 'de',
    'la', 'le', 'les', 'vol', 'edition', 'deluxe', 'version', 'remastered', 'remix', 'feat',
    'single', 'ep', 'album', 'mix', 'live', 'pt', 'part', 'mini', 'bonus', 'minutes', 'special', 'all',
    'bande', 'du', 'des', 'et',
}
# Last.fm tags that name a place rather than a style (korean, japanese... are kept: they
# do describe K-pop / J-pop here). Only used when proposing rules, never when matching yours.
LOCATION_TAGS = {
    'usa', 'us', 'united states', 'america', 'american', 'canada', 'canadian', 'uk', 'british',
    'english', 'england', 'scottish', 'irish', 'ireland', 'french', 'france', 'german', 'germany',
    'swedish', 'sweden', 'norwegian', 'norway', 'danish', 'finnish', 'dutch', 'belgian', 'swiss',
    'italian', 'italy', 'spanish', 'spain', 'portuguese', 'brazil', 'brazilian', 'mexican',
    'australian', 'australia', 'new zealand', 'polish', 'russian', 'africa', 'african',
    'south korea', 'japan', 'china', 'europe', 'european',
}
FROM_TITLE = re.compile(r'from\s+(?:the\s+)?[\"“”\'‘’]+([^\"“”\'‘’]{2,40})[\"“”\'‘’]', re.IGNORECASE)
SOUNDTRACK_WORDS = re.compile(
    r'soundtrack|\bost\b|o\.s\.t|original|\bscore\b|bande[ -]originale|banda sonora|colonna sonora|trilha sonora|'
    r'musique (?:du|de|originale)|music from|motion picture|television|\bseries\b|\bsérie\b|\bfilm\b|\bmovie\b|'
    r'\banime\b|\bvideo ?game\b|\bgame\b', re.IGNORECASE)
PART_SUFFIX = re.compile(r'[\s,:-]+(?:pt\.?|part\.?|vol\.?|volume|season|saison)\s*\d+\s*$', re.IGNORECASE)


def _clean_work(name):
    name = PART_SUFFIX.sub('', name.strip(' -:,·'))
    name = PART_SUFFIX.sub('', name).strip(' -:,·').lower()
    return name if len(name) >= 3 and not SOUNDTRACK_WORDS.fullmatch(name) else None


def work_from_album(album):
    """'Les mystérieuses cités d'or (Bande originale de la série télévisée)' -> 'les mystérieuses cités d'or'."""
    match = re.match(r'^(.+?)\s*[\(\[]([^\)\]]*)[\)\]]', album)
    if match and SOUNDTRACK_WORDS.search(match.group(2)):
        return _clean_work(match.group(1))
    match = re.match(r'^(.+?)\s*(?:[-:–]\s*)?(?:the\s+)?(?:original\s+)?(?:motion picture\s+|television\s+|series\s+)?'
                     r'(?:soundtrack|o\.?s\.?t\.?|score)\b', album, re.IGNORECASE)
    if match:
        return _clean_work(match.group(1))
    return None


def _is_single(title, album):
    """The album is named after the song: an album keyword would only catch this song."""
    t, a = _norm_words(title), _norm_words(album)
    return bool(t) and (t <= a or a <= t)


def _norm_words(text):
    return set(re.findall(r"[\w']+", re.sub(r'\(feat[^)]*\)|\[.*?\]', ' ', text.lower()))) - ALBUM_STOPWORDS - {'instrumental', 'slowed', 'cover', 'version', 'remix'}


def work_from_title(title):
    """'Naruto Theme', 'Erza's Theme', 'Theme from Naruto', '(From "Naruto")' -> the work's name."""
    match = FROM_TITLE.search(title)
    if match:
        return _clean_work(match.group(1))
    match = re.match(r'^(?:main\s+)?theme\s+(?:from|of)\s+(.+)$', title, re.IGNORECASE)
    if match:
        return _clean_work(match.group(1))
    match = re.match(r'^(.+?)(?:\'s|’s)?\s+(?:main\s+)?theme\b', title, re.IGNORECASE)
    if match:
        return _clean_work(match.group(1))
    return None


ORDINAL = re.compile(r'^\d+(st|nd|rd|th)?$')


def _album_ngrams(album):
    words = re.findall(r"[\w&']+", album.lower())
    grams = set()
    for n in (1, 2, 3, 4):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if all(w in ALBUM_STOPWORDS or ORDINAL.match(w) for w in gram) \
                    or gram[0] in ALBUM_STOPWORDS or gram[-1] in ALBUM_STOPWORDS \
                    or ORDINAL.match(gram[0]) or ORDINAL.match(gram[-1]):
                continue
            if len(gram) == 1 and len(gram[0]) < 3:
                continue
            grams.add(' '.join(gram))
    return grams


def _artist(track):
    return track['artists'][0].get('id') or track['artists'][0]['name']


def propose_genres(tracks, tracks_genres, totals, base_share):
    """Greedy: add the genre covering the most uncovered tracks, among characteristic genres."""
    profile = Counter(g for genres in tracks_genres for g in set(genres))
    artists = defaultdict(set)
    for track, genres in zip(tracks, tracks_genres):
        for g in genres:
            artists[g].add(_artist(track))
    candidates = [
        g for g, c in profile.items()
        if g not in LOCATION_TAGS
        and len(artists[g]) >= MIN_ARTISTS
        and c / totals[g] >= MIN_PRECISION
        and c / totals[g] >= MIN_LIFT * base_share
    ]
    uncovered = [set(genres) for genres in tracks_genres]
    chosen = []
    while candidates and len(chosen) < MAX_GENRES:
        best = max(candidates, key=lambda g: (sum(g in t for t in uncovered), profile[g]))
        gain = sum(best in t for t in uncovered)
        if gain < MIN_NEW_COVERAGE:
            break
        chosen.append(best)
        candidates.remove(best)
        uncovered = [t for t in uncovered if best not in t]
    coverage = 1 - len(uncovered) / len(tracks_genres) if tracks_genres else 0
    precision = sum(profile[g] / totals[g] for g in chosen) / len(chosen) if chosen else 0
    return chosen, coverage, precision


def propose_album_keywords(tracks, album_totals, base_share):
    counts, artists = Counter(), defaultdict(set)
    for track in tracks:
        for gram in _album_ngrams((track.get('album') or {}).get('name', '')):
            counts[gram] += 1
            artists[gram].add(_artist(track))
    n = len(tracks)
    candidates = [
        g for g, c in counts.items()
        if len(artists[g]) >= MIN_ARTISTS and c / n >= MIN_ALBUM_SHARE
        and c / album_totals[g] >= max(MIN_ALBUM_PRECISION, MIN_ALBUM_LIFT * base_share)
    ]
    # Most widespread first; on a tie the longer phrase ("motion picture" before "motion").
    candidates.sort(key=lambda g: (-len(artists[g]), -len(g)))
    keywords = []
    for gram in candidates:
        if any(re.search(rf'(?<!\w){re.escape(k)}(?!\w)', gram) or re.search(rf'(?<!\w){re.escape(gram)}(?!\w)', k)
               for k in keywords):
            continue
        keywords.append(gram)
        if len(keywords) >= MAX_ALBUM_KEYWORDS:
            break
    return keywords


def analyse(sp, progress=None, playlists=(), multi_playlist=None):
    """playlists: [{'playlist_id', 'name'}] in any order. Returns the proposal."""
    if multi_playlist is None:
        multi_playlist = config_store.load_config().get('multi_playlist', False)
    progress = progress or (lambda **kw: None)
    resolver = GenreResolver(sp)
    current = {p['playlist_id']: p for p in config_store.load_config()['playlists']}
    catalog = _catalog(sp, progress)

    data = []
    for i, p in enumerate(playlists, 1):
        progress(step=f"Reading {p['name']}", done=i - 1, total=len(playlists))
        tracks = catalog_store.read_playlist(sp, catalog, p['playlist_id'])
        genres = []
        for j, track in enumerate(tracks, 1):
            genres.append(resolver.track_genres(track))
            if j % 25 == 0:
                progress(step=f"Looking up genres in {p['name']} ({j}/{len(tracks)})")
        playlist_id = p['playlist_id']
        if playlist_id.startswith(sort_state.APP_PREFIX):  # a playlist only in the app: keep its entry
            entry_id, playlist_id = playlist_id[len(sort_state.APP_PREFIX):], None
        else:
            entry_id = current.get(playlist_id, {}).get('id') or config_store._new_id()
        data.append({'id': entry_id, 'name': p['name'], 'playlist_id': playlist_id,
                     'tracks': tracks, 'genres': genres})
    resolver.save()

    progress(step='Learning how your playlists are sorted', done=len(playlists), total=len(playlists))
    # Count each distinct track once, even when it is in several playlists.
    unique = {}
    for d in data:
        for track, genres in zip(d['tracks'], d['genres']):
            unique[track['id']] = (track, genres)
    totals = Counter(g for _, genres in unique.values() for g in set(genres))
    album_totals = Counter(
        g for track, _ in unique.values() for g in _album_ngrams((track.get('album') or {}).get('name', ''))
    )
    total_tracks = len(unique) or 1

    entries, stats = [], {}
    for d in data:
        if d['tracks']:
            base_share = len(d['tracks']) / total_tracks
            chosen, coverage, precision = propose_genres(d['tracks'], d['genres'], totals, base_share)
            album_keywords = propose_album_keywords(d['tracks'], album_totals, base_share)
        else:
            chosen, coverage, precision, album_keywords = [], 0, 0, []
        entries.append({
            'id': d['id'], 'name': d['name'], 'playlist_id': d['playlist_id'],
            'genre_names': chosen, 'exclude_genres': [], 'album_keywords': album_keywords,
            'title_keywords': [],
        })
        stats[d['id']] = {'track_count': len(d['tracks']), 'genre_coverage': round(coverage, 2),
                          'precision': precision}

    _give_album_keywords_to_one_playlist(entries, data, album_totals, total_tracks)

    # Album rules first, then the most specific genre rules, empty playlists last.
    entries.sort(key=lambda e: (
        not e['album_keywords'],
        not e['genre_names'],
        -stats[e['id']]['precision'],
    ))

    evaluation = evaluate(sp, entries, data, resolver, multi_playlist)
    proposal = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'multi_playlist': multi_playlist,
        'playlists': entries,
        'stats': {e['id']: {**stats[e['id']], **evaluation[e['id']]} for e in entries},
    }
    for s in proposal['stats'].values():
        s.pop('precision', None)
    PROPOSAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROPOSAL_PATH.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding='utf-8')
    return proposal


def _give_album_keywords_to_one_playlist(entries, data, album_totals, total_tracks):
    """A keyword proposed for several playlists stays only where it is most characteristic."""
    sizes = {d['id']: len(d['tracks']) for d in data}
    counts = {d['id']: Counter(g for t in d['tracks'] for g in _album_ngrams((t.get('album') or {}).get('name', '')))
              for d in data}

    def lift(entry_id, keyword):
        return (counts[entry_id][keyword] / album_totals[keyword]) / (sizes[entry_id] / total_tracks)

    owners = defaultdict(list)
    for e in entries:
        for k in e['album_keywords']:
            owners[k].append(e['id'])
    for keyword, ids in owners.items():
        if len(ids) > 1:
            keep = max(ids, key=lambda i: lift(i, keyword))
            for e in entries:
                if e['id'] != keep and keyword in e['album_keywords']:
                    e['album_keywords'].remove(keyword)


def evaluate(sp, entries, data, resolver, multi_playlist=None):
    """Re-sort every track already in the playlists as if it were new, and compare.

    accuracy: with everything the sorter knows (artist history included)
    accuracy_new_artists: rules only, as for an artist you never sorted before
    """
    if multi_playlist is None:
        multi_playlist = config_store.load_config().get('multi_playlist', False)
    with_history = _evaluate_pass(sp, entries, data, resolver, True, multi_playlist)
    rules_only = _evaluate_pass(sp, entries, data, resolver, False, multi_playlist)
    return {
        entry_id: {**result, 'accuracy_new_artists': rules_only[entry_id]['accuracy']}
        for entry_id, result in with_history.items()
    }


def _evaluate_pass(sp, entries, data, resolver, history, multi_playlist):
    base = config_store.load_config()
    config = {**base, 'playlists': entries, 'multi_playlist': multi_playlist,
              'artist_history': {**base['artist_history'], 'enabled': history}}
    classifier = Classifier(sp, config, resolver)
    names = {e['id']: e['name'] for e in entries}
    places = defaultdict(set)
    album_artists = defaultdict(lambda: defaultdict(set))
    for d in data:
        for track in d['tracks']:
            classifier.add_track(d['id'], track)
            places[track['id']].add(d['id'])
            for gram in _album_ngrams((track.get('album') or {}).get('name', '')):
                album_artists[d['id']][gram].add(_artist(track))
    advisor = _RuleAdvisor(classifier, entries, album_artists, multi_playlist, data, places) if history else None

    results = {}
    for d in data:
        correct = review = 0
        wrong = Counter()
        misplaced = []
        for track in d['tracks']:
            # Leave the track out of what the classifier knows, so it is judged like a new one.
            for entry_id in places[track['id']]:
                classifier.add_track(entry_id, track, sign=-1)
            item = classifier.classify(track, evaluating=True)
            if advisor and (item['status'] == 'review'
                            or not {item['playlist'], *item.get('also', [])} & places[track['id']]):
                misplaced.append(advisor.explain(d['id'], track, item))
            for entry_id in places[track['id']]:
                classifier.add_track(entry_id, track)

            if item['status'] == 'review':
                review += 1
            elif {item['playlist'], *item.get('also', [])} & places[track['id']]:
                correct += 1
            else:
                wrong[names[item['playlist']]] += 1
        n = len(d['tracks']) or 1
        results[d['id']] = {
            'accuracy': round(correct / n, 2),
            'to_review': review,
            'goes_elsewhere': dict(wrong.most_common(3)),
        }
        if advisor:
            results[d['id']]['misplaced'] = misplaced
            results[d['id']]['suggestions'] = advisor.summarize(misplaced)
    return results


class _RuleAdvisor:
    """Rule suggestions for a song that the current rules send to the wrong playlist.

    A suggestion is only kept if it does not move any other song out of a playlist where
    it is correctly sorted today (checked by sorting those songs again with the new rule).
    """

    def __init__(self, classifier, entries, album_artists, multi_playlist, data, places):
        self.c = classifier
        self.entries = entries
        self.by_id = {e['id']: e for e in entries}
        self.order = {e['id']: i for i, e in enumerate(entries)}
        self.album_artists = album_artists
        self.multi_playlist = multi_playlist
        self.places = places
        self.tracks = {t['id']: t for d in data for t in d['tracks']}
        self._before = {}
        self._safe = {}

    def _lift(self, entry_id, genre):
        size = self.c.playlist_sizes[entry_id] + 10
        total = sum(self.c.playlist_sizes.values()) or 1
        if not self.c.genre_totals[genre]:
            return 0
        return (self.c.genre_profile[entry_id][genre] / size) / (self.c.genre_totals[genre] / total)

    # --- Safety check ---

    def _correct(self, track):
        item = self.c.classify(track, evaluating=True)
        return item['status'] != 'review' and bool({item['playlist'], *item.get('also', [])} & self.places[track['id']])

    def _affected(self, kind, entry_id, value):
        """Songs a rule change could move."""
        for track in self.tracks.values():
            inside = entry_id in self.places[track['id']]
            if kind == 'add_genre' and not inside and value in self.c.resolver.track_genres(track):
                yield track
            elif kind == 'exclude_genre' and inside and value in self.c.resolver.track_genres(track):
                yield track
            elif kind == 'album_keyword' and not inside and matches_any([(track.get('album') or {}).get('name', '')], [value]):
                yield track
            elif kind == 'title_keyword' and not inside and matches_any([track['name']], [value]):
                yield track

    def is_safe(self, kind, entry_id, value, current_track_id):
        key = (kind, entry_id, value)
        if key not in self._safe:
            field = {'add_genre': 'genre_names', 'exclude_genre': 'exclude_genres',
                     'album_keyword': 'album_keywords', 'title_keyword': 'title_keywords'}[kind]
            affected = [t for t in self._affected(kind, entry_id, value) if t['id'] != current_track_id]
            before = {t['id']: self._before.setdefault(t['id'], self._correct(t)) for t in affected}
            rules = self.by_id[entry_id][field]
            rules.append(value)
            try:
                broken = sum(1 for t in affected if before[t['id']] and not self._correct(t))
            finally:
                rules.remove(value)
            self._safe[key] = broken == 0
        return self._safe[key]

    # --- Suggestions ---

    def explain(self, home_id, track, item):
        home = self.by_id[home_id]
        went = item['playlist']
        genres = item['genres']
        suggestions = []

        def offer(kind, entry_id, value):
            if self.is_safe(kind, entry_id, value, track['id']):
                suggestions.append({'type': kind, 'playlist': entry_id, 'value': value})

        # The name of the show, film or game: 'Les mystérieuses cités d'or (Bande originale…)',
        # 'Naruto Theme', '(From "Naruto")'.
        work = work_from_title(item['name'])
        if work and work not in home['title_keywords']:
            offer('title_keyword', home_id, work)
        work = work_from_album(item['album'])
        if work and work not in home['album_keywords']:
            offer('album_keyword', home_id, work)
        elif not work and not _is_single(item['name'], item['album']):
            keyword = self._album_keyword(home_id, item['album'])
            if keyword:
                offer('album_keyword', home_id, keyword)

        # A genre of the song that is characteristic of its playlist.
        usable = [g for g in genres if g not in LOCATION_TAGS]
        candidates = [g for g in usable if g not in home['genre_names'] and self.c.genre_profile[home_id][g] > 0]
        candidates.sort(key=lambda g: -self._lift(home_id, g))
        for g in candidates[:3]:
            if (not went or self._lift(home_id, g) > self._lift(went, g)) and self.is_safe('add_genre', home_id, g, track['id']):
                suggestions.append({'type': 'add_genre', 'playlist': home_id, 'value': g})
                break

        # A genre that separates its playlist from the one it went to.
        if went:
            excludable = [g for g in usable if g not in self.by_id[went]['exclude_genres']
                          and self._lift(home_id, g) > self._lift(went, g)]
            excludable.sort(key=lambda g: -(self._lift(home_id, g) - self._lift(went, g)))
            for g in excludable[:3]:
                if self.is_safe('exclude_genre', went, g, track['id']):
                    suggestions.append({'type': 'exclude_genre', 'playlist': went, 'value': g})
                    break

        by_keyword = item['reason'].startswith(('album keyword', 'title keyword'))
        # A keyword playlist (like Drama) took the song: allow it in both playlists.
        if went and by_keyword and not self.multi_playlist:
            suggestions.append({'type': 'multi_playlist', 'playlist': home_id, 'value': went})
        # With keywords, the order of the list decides.
        if went and by_keyword and self.order[home_id] > self.order[went]:
            suggestions.append({'type': 'move_above', 'playlist': home_id, 'value': went})

        if item.get('artist_id') and self.c.config['artist_rules'].get(item['artist_id'], {}).get('playlist') != home_id:
            suggestions.append({'type': 'artist', 'playlist': home_id, 'value': item['artist_id'],
                                'artist': item['artists'][0]})

        return {
            'track_id': track['id'], 'name': item['name'], 'artists': item['artists'], 'album': item['album'],
            'image_url': item.get('image_url'), 'genres': genres[:6], 'went_to': went,
            'reason': item['reason'], 'suggestions': suggestions,
        }

    def _album_keyword(self, home_id, album):
        home = self.by_id[home_id]

        def artists(entry_id, gram):
            return len(self.album_artists[entry_id][gram])

        grams = [g for g in _album_ngrams(album) if g not in home['album_keywords']]
        clean = [g for g in grams if not any(artists(e, g) for e in self.by_id if e != home_id)]
        if not clean:
            return None
        # Shared by the most artists of the playlist; on a tie the longer, more precise phrase.
        return max(clean, key=lambda g: (artists(home_id, g), len(g.split()), len(g)))

    @staticmethod
    def summarize(misplaced):
        """Rules that would match the most misplaced songs of a playlist."""
        counts, examples = Counter(), {}
        for m in misplaced:
            for s in m['suggestions']:
                if s['type'] == 'artist':
                    continue
                key = (s['type'], s['playlist'], s['value'])
                counts[key] += 1
                examples[key] = s
        return [{**examples[k], 'count': n} for k, n in counts.most_common(5) if n >= 2]


def load_proposal():
    if PROPOSAL_PATH.exists():
        return json.loads(PROPOSAL_PATH.read_text(encoding='utf-8'))
    return None


def rules_hash(playlists, multi_playlist=False):
    """Fingerprint of the rules and their order, to know when an accuracy check is out of date."""
    rules = [[p['playlist_id']] + [sorted(p.get(f, [])) for f in config_store.RULE_FIELDS] for p in playlists]
    rules.append(bool(multi_playlist))
    return hashlib.sha1(json.dumps(rules).encode()).hexdigest()[:12]


def _catalog(sp, progress):
    import library
    return library.current_catalog(sp, progress)


def _read_playlists(sp, playlists, resolver, progress):
    catalog = _catalog(sp, progress)
    data = []
    for i, p in enumerate(playlists, 1):
        progress(step=f"Reading {p['name']}", done=i - 1, total=len(playlists))
        tracks = catalog_store.read_playlist(sp, catalog, sort_state.playlist_key(p))
        data.append({'id': p['id'], 'name': p['name'], 'playlist_id': p['playlist_id'], 'tracks': tracks,
                     'genres': [resolver.track_genres(t) for t in tracks]})
    resolver.save()
    return data


def check_accuracy(sp, progress=None):
    """Measure the current rules on the songs already in the genre playlists."""
    progress = progress or (lambda **kw: None)
    playlists = config_store.load_config()['playlists']
    resolver = GenreResolver(sp)
    data = _read_playlists(sp, playlists, resolver, progress)
    progress(step='Re-sorting your playlists with the current rules', done=len(playlists), total=len(playlists))
    stats = evaluate(sp, playlists, data, resolver)
    for d in data:
        stats[d['id']]['track_count'] = len(d['tracks'])
    save_accuracy(stats, playlists)


def reevaluate(sp, progress=None, playlists=(), multi_playlist=False):
    """Measure edited proposal rules again, without learning new ones."""
    progress = progress or (lambda **kw: None)
    resolver = GenreResolver(sp)
    data = _read_playlists(sp, playlists, resolver, progress)
    progress(step='Re-sorting your playlists with these rules', done=len(playlists), total=len(playlists))
    stats = evaluate(sp, playlists, data, resolver, multi_playlist)
    for d in data:
        stats[d['id']]['track_count'] = len(d['tracks'])
    proposal = load_proposal() or {}
    proposal.update({'playlists': list(playlists), 'stats': stats, 'multi_playlist': multi_playlist})
    PROPOSAL_PATH.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding='utf-8')


def save_accuracy(stats, playlists):
    multi = config_store.load_config().get('multi_playlist', False)
    result = {'generated_at': datetime.now().isoformat(timespec='seconds'),
              'rules_hash': rules_hash(playlists, multi), 'stats': stats}
    ACCURACY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCURACY_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')


def load_accuracy():
    if ACCURACY_PATH.exists():
        return json.loads(ACCURACY_PATH.read_text(encoding='utf-8'))
    return None


def apply_proposal(entries, fallback_genre=None, multi_playlist=None):
    """Replace the genre playlists of the config by the accepted ones (in this order)."""
    with config_store.editing() as config:
        config['playlists'] = [
            {'id': e.get('id') or config_store._new_id(), 'name': e['name'], 'playlist_id': e['playlist_id'],
             **{f: e.get(f, []) for f in config_store.RULE_FIELDS}}
            for e in entries
        ]
        if fallback_genre is not None:
            config['fallback_genre'] = fallback_genre
        if multi_playlist is not None:
            config['multi_playlist'] = bool(multi_playlist)

    # The proposal's accuracy is still valid if its rules were accepted as they are.
    proposal = load_proposal()
    if proposal and rules_hash(proposal['playlists'], proposal.get('multi_playlist')) \
            == rules_hash(config['playlists'], config.get('multi_playlist')):
        save_accuracy(proposal['stats'], config['playlists'])
    return config
