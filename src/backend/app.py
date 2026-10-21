import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import requests

import apple_music
import catalog as catalog_store
import config_store
import devices
import downloads_watch
import errors
import events
import library
import setup_analysis
import sort_state
import sorter
import stats
from spotify_client import SpotifyLimitError, blocked, create_client, keys_present, logged_in, playlist_meta
from spotify_client import me as spotify_me

load_dotenv()
app = Flask(__name__)
# The backend has no login: only pages served from this computer may call it (any port), and tools
# without a browser (no Origin). A page of another site open in the browser can't drive it.
LOCAL_ORIGIN = re.compile(r'https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$')
CORS(app, origins=[LOCAL_ORIGIN])


@app.before_request
def refuse_other_sites():
    origin = request.headers.get('Origin')
    if origin and not LOCAL_ORIGIN.match(origin):
        return jsonify({'error': 'forbidden'}), 403

class _LazySpotify:
    """The Spotify client, created on first use, so the backend starts without keys."""

    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            self._client = create_client()
        return getattr(self._client, name)


sp = _LazySpotify()
likes_job = sorter.Job(sorter.build_preview, 'likes')
setup_job = sorter.Job(setup_analysis.analyse, 'setup')
accuracy_job = sorter.Job(setup_analysis.check_accuracy, 'accuracy')
reevaluate_job = sorter.Job(setup_analysis.reevaluate, 'reevaluate')
library_job = sorter.Job(library.sync, 'library')
import_job = sorter.Job(library.import_files, 'import')
import itunes_windows
# Apple Music on macOS, iTunes on Windows.
apple_job = sorter.Job(apple_music.update if apple_music.available() else itunes_windows.update, 'apple')
spotify_sync_job = sorter.Job(lambda sp, progress: sort_state.push(sp, catalog_store.refresh_from_spotify(sp, progress), progress),
                              'spotify_sync')


AUTO_SYNC_MAX = 200  # songs; above it, or on the first import, the Sync waits for the user


def _import_and_sync(sp, progress, path):
    """Import an exported playlists file and check the library.

    The Sync runs by itself only for an update of a library already synced, with nothing to
    move or remove and a few songs to download. On a first import, the user chooses the
    playlists to download first.
    """
    progress(step='Reading the file')
    result = catalog_store.import_file(path)
    plan = library.sync(sp, progress, apply=False)
    first = not library.load_library()['tracks']
    auto = not first and not plan['to_move'] and not plan['to_remove'] and len(plan['to_download']) <= AUTO_SYNC_MAX
    result.update(first=first, synced=auto, to_download=len(plan['to_download']))
    library.IMPORTED_PATH.write_text(json.dumps(result), encoding='utf-8')
    if auto:
        library.sync(sp, progress, apply=True)


file_import_job = sorter.Job(_import_and_sync, 'file_import')
chosen_job = sorter.Job(library.download_chosen, 'chosen')
# Jobs that write the library (library.json, files, Apple Music): only one at a time.
LIBRARY_JOBS = (library_job, import_job, file_import_job, apple_job, chosen_job)
BUSY = 'busy'


def _library_busy():
    return any(job.state.get('running') for job in LIBRARY_JOBS)


def _on_downloaded_file(path):
    if _library_busy():
        raise downloads_watch.Busy()  # imported once the current job is done
    file_import_job.start(sp, path=str(path))


downloads_watch.start(_on_downloaded_file)


@app.errorhandler(Exception)
def handle_error(e):
    """Every error reaches the page as a code (the page has the texts)."""
    if isinstance(e, HTTPException):
        return e
    code, params = errors.describe(e)
    app.logger.warning('%s %s: %s', request.method, request.path, code)
    status = 503 if code in ('spotify_limit', 'spotify_down', 'youtube_down', 'lastfm_down', 'no_internet') else 400
    return jsonify({'error': code, 'params': params}), status


@app.route('/events', methods=['GET'])
def get_events():
    """The pages' one stream: every job's state at each step, and 'status' when what the app can do changed."""
    return Response(stream_with_context(events.stream()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# --- Local configuration (formerly Firestore) ---

@app.route('/config', methods=['GET'])
def get_config():
    return jsonify(config_store.load_config())


@app.route('/config/reveal', methods=['POST'])
def reveal_config():
    """Show config.json in the system file manager."""
    config_store.load_config()
    path = str(config_store.CONFIG_PATH)
    system = platform.system()
    if system == 'Darwin':
        subprocess.Popen(['open', '-R', path])
    elif system == 'Windows':
        subprocess.Popen(['explorer', '/select,', path])
    else:
        subprocess.Popen(['xdg-open', str(config_store.CONFIG_PATH.parent)])
    return '', 204


@app.route('/config/settings', methods=['PUT'])
def update_settings():
    return jsonify(config_store.update_settings(request.json))


@app.route('/config/playlists', methods=['POST'])
def add_playlist():
    """A "sort into" playlist. Without playlist_id: a new playlist, only in the app until the next Spotify sync."""
    body = request.json
    rules = {f: body.get(f, []) for f in config_store.RULE_FIELDS if f != 'genre_names'}
    entry = config_store.add_playlist(body.get('name', ''), body.get('playlist_id'), body.get('genre_names', []), **rules)
    return jsonify(entry), 201


@app.route('/config/playlists/<entry_id>', methods=['PATCH'])
def update_playlist(entry_id):
    try:
        return jsonify(config_store.update_playlist(entry_id, request.json))
    except KeyError:
        return jsonify({'error': 'unexpected'}), 404


@app.route('/config/playlists/<entry_id>', methods=['DELETE'])
def delete_playlist(entry_id):
    config_store.delete_playlist(entry_id)
    return '', 204


@app.route('/config/playlists/order', methods=['PUT'])
def reorder_playlists():
    return jsonify(config_store.reorder_playlists(request.json['ids']))


@app.route('/config/artist-rules', methods=['POST'])
def add_artist_rule():
    body = request.json
    config_store.set_artist_rule(body['artist_id'], body['name'], body['playlist'])
    return '', 204


@app.route('/config/artist-rules/<artist_id>', methods=['DELETE'])
def delete_artist_rule(artist_id):
    config_store.set_artist_rule(artist_id, None, None)
    return '', 204


# --- Setup assistant ---

_keys_present = keys_present
_logged_in = logged_in


login_state = {'running': False}


@app.route('/setup/login', methods=['POST'])
def spotify_login():
    """Opens the Spotify login page in the browser and waits for it in the background."""
    if not _keys_present():
        return jsonify({'error': 'spotify_keys_missing'}), 400
    if login_state['running']:
        return jsonify(login_state), 202

    def run():
        login_state['running'] = True
        try:
            sp.me()
        except Exception as e:
            app.logger.warning('Spotify login: %s', e)
        finally:
            login_state['running'] = False
            events.publish('status')

    import threading
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'running': True}), 202


REMINDER_DAYS = 7


def _import_status(catalog, config):
    """Where the playlists come from, and the reminder when the last import is old."""
    source = catalog.get('source')
    days = None
    if catalog.get('updated_at'):
        days = (datetime.now() - datetime.fromisoformat(catalog['updated_at'])).days
    # A file read in place of Spotify is not used any more once Spotify can be read: no reminder then.
    from_file = source in catalog_store.FILE_SOURCES and not (
        _keys_present() and _logged_in() and not blocked() and catalog_store.follows_spotify(catalog))
    return {
        'source': source,
        'file': catalog.get('file'),
        'from_file': from_file,
        'updated_at': catalog.get('updated_at'),
        'days': days,
        'reminder': bool(from_file and config.get('import_reminder', True) and days is not None and days > REMINDER_DAYS),
        'watching': downloads_watch.active(),
    }


@app.route('/setup/status', methods=['GET'])
def setup_status():
    config = config_store.load_config()
    catalog = catalog_store.load()
    if not catalog.get('source'):
        catalog = catalog_store.from_last_check() or catalog
    base = {'lastfm': bool(os.getenv('LASTFM_API_KEY')), 'ffmpeg': library.ffmpeg_path() is not None,
            'configured': bool(config['playlists']), 'playlists': catalog.get('source') is not None,
            'import': _import_status(catalog, config),
            'sort': {'pending': sort_state.pending_count(catalog, config) if catalog.get('source') else 0,
                     'waiting': sort_state.waiting()}}
    if not _keys_present():
        return jsonify({**base, 'spotify': {'connected': False, 'missing_keys': True}})
    if not _logged_in():
        return jsonify({**base, 'spotify': {'connected': False, 'needs_login': True,
                                            'logging_in': login_state['running']}})
    if blocked():
        # Connected, but Spotify has blocked the app for now: nothing is sent before the end of the block.
        try:
            sp.me()
        except SpotifyLimitError as e:
            return jsonify({**base, 'spotify': {'connected': True, 'name': None, 'limit': errors.describe(e)[1]['until']}})
    try:
        me = spotify_me(sp)
        spotify = {'connected': True, 'name': me.get('display_name') or me.get('id'),
                   'image_url': (me.get('images') or [{}])[0].get('url')}
    except SpotifyLimitError as e:
        spotify = {'connected': True, 'name': None, 'limit': errors.describe(e)[1]['until']}
    except Exception as e:
        spotify = {'connected': False, 'error': errors.describe(e)[0]}
    return jsonify({**base, 'spotify': spotify})


# --- Playlists from a file (no Premium) ---

@app.route('/import', methods=['GET'])
def get_import():
    config = config_store.load_config()
    return jsonify({'job': file_import_job.state, 'status': _import_status(catalog_store.load(), config),
                    'result': library.load_imported(), 'watch': {'last': downloads_watch.state['last'],
                                                                 'error': downloads_watch.state['error']}})


@app.route('/import/watch', methods=['POST'])
def watch_downloads():
    """The import guide is open: watch the Downloads folder for the exported file."""
    downloads_watch.watch_for_guide()
    return jsonify({'watching': True, 'folder': str(downloads_watch.DOWNLOADS)})


@app.route('/import/file', methods=['POST'])
def import_playlists_file():
    """An exported file chosen by hand (uploaded from the page)."""
    upload = request.files.get('file')
    if not upload:
        return jsonify({'error': 'unexpected'}), 400
    folder = config_store.DATA_DIR / 'imports'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(upload.filename or 'playlists.csv').name
    upload.save(path)
    if not catalog_store.detect(path):
        return jsonify({'error': 'not_an_export'}), 400
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    started = file_import_job.start(sp, path=str(path))
    return jsonify({'started': started, **file_import_job.state}), 202 if started else 409


# --- Sorted songs waiting for Spotify ---

@app.route('/sort/spotify', methods=['GET'])
def get_spotify_sync():
    """What "Sync with Spotify" would do (reads Spotify, writes nothing)."""
    if not (_keys_present() and _logged_in()) or not catalog_store.follows_spotify(catalog_store.load()):
        return jsonify({'available': False, 'changes': [], 'job': spotify_sync_job.state})
    catalog = catalog_store.refresh_from_spotify(sp)
    return jsonify({'available': True, 'changes': sort_state.plan_sync(catalog), 'job': spotify_sync_job.state})


@app.route('/sort/spotify', methods=['POST'])
def run_spotify_sync():
    started = spotify_sync_job.start(sp)
    if started:
        sort_state.set_waiting(False)
    return jsonify({'started': started, **spotify_sync_job.state}), 202 if started else 409


@app.route('/setup/analyze', methods=['POST'])
def start_setup_analysis():
    started = setup_job.start(sp, playlists=request.json['playlists'],
                              multi_playlist=request.json.get('multi_playlist'))
    return jsonify({'started': started, **setup_job.state}), 202 if started else 409


@app.route('/setup/analyze', methods=['GET'])
def get_setup_analysis():
    return jsonify({'job': setup_job.state, 'evaluation': reevaluate_job.state,
                    'proposal': setup_analysis.load_proposal()})


@app.route('/setup/evaluate', methods=['POST'])
def start_setup_evaluation():
    body = request.json
    started = reevaluate_job.start(sp, playlists=body['playlists'], multi_playlist=body.get('multi_playlist', False))
    return jsonify({'started': started, **reevaluate_job.state}), 202 if started else 409


@app.route('/setup/apply', methods=['POST'])
def apply_setup():
    body = request.json
    return jsonify(setup_analysis.apply_proposal(body['playlists'], body.get('fallback_genre'), body.get('multi_playlist')))


@app.route('/genres/accuracy', methods=['POST'])
def start_accuracy_check():
    started = accuracy_job.start(sp)
    return jsonify({'started': started, **accuracy_job.state}), 202 if started else 409


@app.route('/genres/accuracy', methods=['GET'])
def get_accuracy():
    config = config_store.load_config()
    return jsonify({
        'job': accuracy_job.state,
        'result': setup_analysis.load_accuracy(),
        'rules_hash': setup_analysis.rules_hash(config['playlists'], config.get('multi_playlist', False)),
    })


# --- Local library (downloads + .m3u8 playlists) ---

@app.route('/library', methods=['GET'])
def get_library():
    # The job started last (its error stays shown once it is done).
    job = max((j.state for j in (library_job, file_import_job, import_job)), key=lambda state: state.get('started_at', 0))
    app_name = 'Apple Music' if apple_music.available() else 'iTunes' if itunes_windows.available() else None
    return jsonify({'job': job, 'import': library.load_import_result(), 'apple_music': {
        'available': app_name is not None, 'app': app_name, 'job': apple_job.state}, 'chosen': chosen_job.state,
        'platform': platform.system(), **library.summary()})


@app.route('/library/apple-music', methods=['POST'])
def update_apple_music():
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    started = apple_job.start(sp)
    return jsonify({'started': started, **apple_job.state}), 202 if started else 409


@app.route('/library/import', methods=['POST'])
def import_library():
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    body = request.json
    started = import_job.start(sp, source=body['path'], mode=body.get('mode', 'copy'))
    return jsonify({'started': started, **import_job.state}), 202 if started else 409


@app.route('/library/check', methods=['POST'])
def check_library():
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    started = library_job.start(sp, apply=False)
    return jsonify({'started': started, **library_job.state}), 202 if started else 409


@app.route('/library/sync', methods=['POST'])
def sync_library():
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    started = library_job.start(sp, apply=True)
    return jsonify({'started': started, **library_job.state}), 202 if started else 409


@app.route('/library/matches/<track_id>', methods=['GET'])
def get_matches(track_id):
    """YouTube Music results for a song not found, to choose the right one by hand."""
    return jsonify({'results': library.youtube_candidates(track_id)})


@app.route('/library/matches/<track_id>', methods=['POST'])
def choose_match(track_id):
    """A result or a pasted link: the song is downloaded from it at once."""
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    library.choose_match(track_id, request.json.get('url', ''))
    chosen_job.start(sp, track_id=track_id)
    return jsonify({'started': True}), 202


@app.route('/library/ignored/<track_id>', methods=['POST', 'DELETE'])
def ignore_track(track_id):
    """Ignore this song in the next syncs (POST), or not any more (DELETE)."""
    if _library_busy():
        return jsonify({'error': BUSY}), 409
    library.ignore(track_id, ignored=request.method == 'POST')
    return jsonify(library.summary())


@app.route('/library/example', methods=['GET'])
def library_example():
    """A real song of the downloaded playlists, to show where files go for each layout."""
    config = config_store.load_config()
    view = sort_state.view(catalog_store.load(), config)
    ids = library._ordered(config, library.downloaded_playlists(config, view))
    for pid in ids:
        for tid in view['playlists'][pid]['track_ids']:
            track = view['tracks'].get(tid)
            if track and track.get('artists') and (track.get('album') or {}).get('name'):
                in_playlists = [view['playlists'][p]['name'] for p in ids if tid in view['playlists'][p]['track_ids']]
                return jsonify({'album_artist': library.safe_name(library.album_artist(track)),
                                'album': library.safe_name(track['album']['name']),
                                'file': library.safe_name(f"{', '.join(a['name'] for a in track['artists'])} - {track['name']}")
                                        + '.' + config['audio_format'],
                                'first_playlist': library.safe_name(in_playlists[0]) if in_playlists else None,
                                'separator': os.sep, 'music_dir': _display_path(library.music_root(config))})
    return jsonify({'album_artist': 'BLACKPINK', 'album': 'KILL THIS LOVE', 'file': 'BLACKPINK - Kill This Love.mp3',
                    'first_playlist': 'Kr', 'separator': os.sep, 'music_dir': _display_path(library.music_root(config))})


def _display_path(path):
    """~/Music instead of /Users/name/Music (macOS, Linux)."""
    home = Path.home()
    if platform.system() != 'Windows' and (path == home or home in path.parents):
        return '~/' + str(path.relative_to(home)) if path != home else '~'
    return str(path)


@app.route('/devices', methods=['GET'])
def get_devices():
    """Apple Music subscription and iPhone plugged in, for the iPhone card of Library (macOS)."""
    return jsonify(devices.status())


@app.route('/devices/music', methods=['POST'])
def open_music():
    devices.open_music()
    return '', 204


@app.route('/devices/finder', methods=['POST'])
def open_finder():
    devices.open_finder()
    return '', 204


@app.route('/library/reveal', methods=['POST'])
def reveal_library():
    root = library.music_root(config_store.load_config())
    root.mkdir(parents=True, exist_ok=True)
    opener = {'Darwin': ['open'], 'Windows': ['explorer']}.get(platform.system(), ['xdg-open'])
    subprocess.Popen(opener + [str(root)])
    return '', 204


# --- Liked songs sorting ---

@app.route('/likes/preview', methods=['POST'])
def start_likes_preview():
    started = likes_job.start(sp)
    return jsonify({'started': started, **likes_job.state}), 202 if started else 409


@app.route('/likes/preview', methods=['GET'])
def get_likes_preview():
    return jsonify({'job': likes_job.state, 'preview': sorter.load_preview()})


@app.route('/likes/review/<track_id>', methods=['POST'])
def resolve_review(track_id):
    body = request.json
    try:
        item = sorter.resolve_review(track_id, body['playlist'], body.get('remember_artist', False))
    except KeyError:
        return jsonify({'error': 'unexpected'}), 404
    return jsonify(item)


@app.route('/likes/apply', methods=['POST'])
def apply_likes():
    if likes_job.state.get('running'):
        return jsonify({'error': 'analysis_running'}), 409
    return jsonify(sorter.apply_preview(sp))


# --- Spotify ---

CATALOG_TTL = 300  # seconds before the playlists are read from Spotify again for the pages


@app.route('/get-playlists', methods=['GET'])
def get_playlists():
    """Your playlists as the app sees them (Spotify or the imported file, plus app-only ones)."""
    catalog = catalog_store.load()
    if not catalog.get('source'):
        catalog = catalog_store.from_last_check() or catalog
    fresh = catalog.get('updated_at') and (datetime.now() - datetime.fromisoformat(catalog['updated_at'])).total_seconds() < CATALOG_TTL
    if _keys_present() and _logged_in() and catalog_store.follows_spotify(catalog) and not fresh and not blocked():
        try:
            catalog = catalog_store.refresh_from_spotify(sp)
        except SpotifyLimitError:
            if not catalog.get('source'):
                raise
    config = config_store.load_config()
    seen = set(config['download'].get('seen') or [])
    view = sort_state.view(catalog, config)
    result = []
    for item in catalog_store.summary(view)['playlists']:
        result.append({**item, 'new': bool(seen) and item['id'] not in seen,
                       'app_only': item['id'].startswith(sort_state.APP_PREFIX)})
    return jsonify(result)


@app.route('/download/seen', methods=['POST'])
def mark_playlists_seen():
    """The playlists shown in Settings are no longer "New"."""
    config = config_store.load_config()
    download = config['download']
    download['seen'] = list(dict.fromkeys((download.get('seen') or []) + request.json.get('ids', [])))
    config_store.update_settings({'download': download})
    return '', 204


@app.route('/get-playlist-details/<playlist_id>', methods=['GET'])
def get_playlist_details(playlist_id):
    return jsonify(playlist_meta(sp, playlist_id))


@app.route('/stats', methods=['GET'])
def get_stats():
    """What the playlists say about your taste (all of them, or ?playlist=<id>), from whatever the app has."""
    return jsonify({**stats.compute(request.args.get('playlist') or None), 'playlists': stats.scopes()})


@app.route('/get-top-tracks', methods=['GET'])
def get_top_tracks():
    top_tracks = sp.current_user_top_tracks(time_range='long_term', limit=10)
    return jsonify([{
        'name': item['name'],
        'artist': item['artists'][0]['name'],
        'image_url': item['album']['images'][0]['url'] if item['album']['images'] else '/assets/default-cover-image.jpg',
        'url': item['external_urls']['spotify'],
    } for item in top_tracks['items']])


@app.route('/get-recently-played', methods=['GET'])
def get_recently_played():
    results = sp.current_user_recently_played(limit=50)
    track_data = []
    for item in results['items']:
        track = item['track']
        track_data.append({
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'album': track['album']['name'],
            'image_url': track['album']['images'][0]['url'] if track['album']['images'] else '/assets/default-cover-image.jpg',
            'url': track['external_urls']['spotify'],
        })
    return jsonify(track_data)


def _reload_when_idle():
    """Flask's reloader restarts the backend as soon as its code changes, which stopped a Sync or a
    download halfway: it now waits until no job is running."""
    import time
    import werkzeug._reloader as reloader

    def waiting(trigger):
        def when_idle(self, filename):
            jobs = [job for job in globals().values() if isinstance(job, sorter.Job)]
            while any(job.state.get('running') for job in jobs) or login_state['running']:
                time.sleep(1)
            trigger(self, filename)
        return when_idle

    # The stat and the watchdog reloaders each have their own trigger.
    for loop in [reloader.ReloaderLoop, *reloader.ReloaderLoop.__subclasses__()]:
        if 'trigger_reload' in vars(loop):
            loop.trigger_reload = waiting(vars(loop)['trigger_reload'])


if __name__ == '__main__':
    _reload_when_idle()
    # Port 5000 is taken by AirPlay Receiver on macOS.
    # The reloader also restarts on *.zip: an imported zip saved in data/ would stop the running job.
    data = str(config_store.DATA_DIR)
    app.run(port=int(os.getenv('PORT', 5001)), debug=True, exclude_patterns=[f'{data}/*', f'{data}/*/*'])
