import os
import platform
import shutil
import subprocess

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import requests

import apple_music
import config_store
import library
import setup_analysis
import sorter
from genres import GenreResolver
from spotify_client import (SpotifyLimitError, add_to_playlist, create_client, my_playlists, playlist_meta,
                            playlist_tracks, remove_from_playlist)

load_dotenv()
app = Flask(__name__)
CORS(app)

class _LazySpotify:
    """The Spotify client, created on first use, so the backend starts without keys."""

    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            self._client = create_client()
        return getattr(self._client, name)


sp = _LazySpotify()
likes_job = sorter.Job(sorter.build_preview)
setup_job = sorter.Job(setup_analysis.analyse)
accuracy_job = sorter.Job(setup_analysis.check_accuracy)
reevaluate_job = sorter.Job(setup_analysis.reevaluate)
library_job = sorter.Job(library.sync)
import_job = sorter.Job(library.import_files)
apple_job = sorter.Job(apple_music.update)


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, SpotifyLimitError):
        app.logger.warning('%s %s: %s', request.method, request.path, e)
        return jsonify({'error': str(e)}), 503
    if isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        app.logger.warning('%s %s: Spotify did not respond (%s)', request.method, request.path, type(e).__name__)
        return jsonify({'error': 'Spotify did not respond. Try again in a moment.'}), 503
    app.logger.exception(e)
    return jsonify({'error': str(e)}), 400


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
    body = request.json
    try:
        rules = {f: body.get(f, []) for f in config_store.RULE_FIELDS if f != 'genre_names'}
        entry = config_store.add_playlist(body.get('name', ''), body['playlist_id'], body['genre_names'], **rules)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409
    return jsonify(entry), 201


@app.route('/config/playlists/<entry_id>', methods=['PATCH'])
def update_playlist(entry_id):
    try:
        return jsonify(config_store.update_playlist(entry_id, request.json))
    except KeyError:
        return jsonify({'error': 'Playlist not found'}), 404


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

def _keys_present():
    return bool(os.getenv('SPOTIFY_CLIENT_ID') and os.getenv('SPOTIFY_CLIENT_SECRET'))


def _logged_in():
    return (config_store.DATA_DIR / '.spotify-token').exists()


login_state = {'running': False}


@app.route('/setup/login', methods=['POST'])
def spotify_login():
    """Opens the Spotify login page in the browser and waits for it in the background."""
    if not _keys_present():
        return jsonify({'error': 'Spotify keys are missing in src/backend/.env.'}), 400
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

    import threading
    threading.Thread(target=run, daemon=True).start()
    return jsonify({'running': True}), 202


@app.route('/setup/status', methods=['GET'])
def setup_status():
    base = {'lastfm': bool(os.getenv('LASTFM_API_KEY')), 'ffmpeg': shutil.which('ffmpeg') is not None,
            'configured': bool(config_store.load_config()['playlists'])}
    if not _keys_present():
        return jsonify({**base, 'spotify': {'connected': False, 'missing_keys': True}})
    if not _logged_in():
        return jsonify({**base, 'spotify': {'connected': False, 'needs_login': True,
                                            'logging_in': login_state['running']}})
    try:
        me = sp.me()
        spotify = {'connected': True, 'name': me.get('display_name') or me.get('id'),
                   'image_url': (me.get('images') or [{}])[0].get('url')}
    except SpotifyLimitError as e:
        # Connected, but Spotify has blocked the app for now.
        spotify = {'connected': True, 'name': None, 'limit': str(e)}
    except Exception as e:
        spotify = {'connected': False, 'error': str(e)}
    return jsonify({
        'spotify': spotify,
        'lastfm': bool(os.getenv('LASTFM_API_KEY')),
        'ffmpeg': shutil.which('ffmpeg') is not None,
        'configured': bool(config_store.load_config()['playlists']),
    })


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
    job = import_job.state if import_job.state.get('running') else library_job.state
    return jsonify({'job': job, 'import': library.load_import_result(), 'apple_music': {
        'available': apple_music.available(), 'job': apple_job.state}, **library.summary()})


@app.route('/library/apple-music', methods=['POST'])
def update_apple_music():
    if library_job.state.get('running') or import_job.state.get('running'):
        return jsonify({'error': 'Wait for the current sync or import to finish'}), 409
    started = apple_job.start(sp)
    return jsonify({'started': started, **apple_job.state}), 202 if started else 409


@app.route('/library/import', methods=['POST'])
def import_library():
    if library_job.state.get('running'):
        return jsonify({'error': 'A sync is running'}), 409
    body = request.json
    started = import_job.start(sp, source=body['path'], mode=body.get('mode', 'copy'))
    return jsonify({'started': started, **import_job.state}), 202 if started else 409


@app.route('/library/check', methods=['POST'])
def check_library():
    if import_job.state.get('running'):
        return jsonify({'error': 'An import is running'}), 409
    started = library_job.start(sp, apply=False)
    return jsonify({'started': started, **library_job.state}), 202 if started else 409


@app.route('/library/sync', methods=['POST'])
def sync_library():
    if import_job.state.get('running'):
        return jsonify({'error': 'An import is running'}), 409
    started = library_job.start(sp, apply=True)
    return jsonify({'started': started, **library_job.state}), 202 if started else 409


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
        return jsonify({'error': 'Track not found in preview'}), 404
    return jsonify(item)


@app.route('/likes/apply', methods=['POST'])
def apply_likes():
    return jsonify({'added': sorter.apply_preview(sp)})


# --- Spotify ---

@app.route('/sort-playlist', methods=['POST'])
def sort_playlist():
    """Move the tracks of a playlist into the genre playlists, using the same rules as the likes."""
    playlist_id = request.json['playlist_id']
    config = config_store.load_config()
    resolver = GenreResolver(sp)
    classifier = sorter.Classifier(sp, config, resolver)
    classifier.build_index()
    by_id = classifier.by_id
    moved = 0

    for track in playlist_tracks(sp, playlist_id):
        item = classifier.classify(track)
        if item['status'] == 'review':
            continue
        target = by_id[item['playlist']]
        if target['playlist_id'] == playlist_id:
            continue
        if item['status'] != 'already':
            add_to_playlist(sp, target['playlist_id'], [track['id']])
            classifier.track_index[track['id']] = target['id']
            print(f"Moved track {track['name']} to {target['name']} ({item['reason']}).")
        remove_from_playlist(sp, playlist_id, [track['id']])
        moved += 1

    resolver.save()
    return jsonify({'message': f'Playlist sorted successfully! {moved} tracks moved.'})


@app.route('/get-playlists', methods=['GET'])
def get_playlists():
    me = sp.me()['id']
    result = []
    for p in my_playlists(sp):
        images = p.get('images') or []
        result.append({
            'id': p['id'],
            # Some names are padded with invisible characters (braille blank, hangul filler).
            'name': p['name'].strip(' \t\u2800\u3164\u200b') or p['name'],
            'image_url': images[0]['url'] if images else None,
            'track_count': (p.get('items') or p.get('tracks') or {}).get('total', 0),
            'owned': (p.get('owner') or {}).get('id') == me,
        })
    return jsonify(result)


@app.route('/get-playlist-details/<playlist_id>', methods=['GET'])
def get_playlist_details(playlist_id):
    return jsonify(playlist_meta(sp, playlist_id))


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


if __name__ == '__main__':
    # Port 5000 is taken by AirPlay Receiver on macOS.
    app.run(port=int(os.getenv('PORT', 5001)), debug=True)
