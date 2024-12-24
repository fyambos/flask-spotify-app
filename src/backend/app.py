from flask import Flask, request, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask_cors import CORS
from dotenv import load_dotenv
import os
from firebase_admin import firestore, credentials, initialize_app
load_dotenv()
app = Flask(__name__)
CORS(app)
cred = credentials.Certificate('./ticket-app-115e1-firebase-adminsdk-op7k7-eecbaae882.json')
initialize_app(cred)
db = firestore.client()

client_id = os.getenv('SPOTIFY_CLIENT_ID')
client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
redirect_uri = 'http://localhost:8888/callback'
scope = 'playlist-read-private playlist-modify-private user-library-read user-top-read'

# set up Spotify OAuth
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id,
                                               client_secret=client_secret,
                                               redirect_uri=redirect_uri,
                                               scope=scope))

@app.route('/sort-playlist', methods=['POST'])
def sort_playlist():
    playlist_id = request.json['playlist_id']

    # fetch all tracks in the source playlist
    results = sp.playlist_tracks(playlist_id)
    tracks = results['items']

    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])

    # create a set to keep track of processed tracks
    processed_track_ids = set()

    # fetch playlist data from Firestore (assuming 'playlists' collection in Firestore)
    playlists_ref = db.collection('playlists')
    playlists_snapshot = playlists_ref.get()

    # convert Firestore data into a usable dictionary format
    playlists_data = {}
    for doc in playlists_snapshot:
        data = doc.to_dict()
        playlists_data[doc.id] = {
            'genre_names': data['genre_names'],
            'playlist_id': data['playlist_id']
        }

    # process each track and add it to the appropriate playlist based on genre
    for item in tracks:
        track = item['track']
        track_id = track['id']

        # skip if the track has already been processed
        if track_id in processed_track_ids:
            continue

        artist_id = track['artists'][0]['id']
        artist = sp.artist(artist_id)
        genres = artist['genres']
        print(f"Processing track {track['name']} by {artist['name']} with genres {genres}")

        # find the appropriate target playlist from Firestore data
        for playlist_name, playlist_data in playlists_data.items():
            if any(genre_name in genre for genre in genres for genre_name in playlist_data['genre_names']):
                target_playlist_id = playlist_data['playlist_id']

                # fetch playlist name from Spotify
                try:
                    target_playlist_details = sp.playlist(target_playlist_id)
                    target_playlist_name = target_playlist_details['name']
                except Exception as e:
                    print(f"Error fetching playlist details for {target_playlist_id}: {e}")
                    continue

                # fetch existing tracks in the target playlist
                target_results = sp.playlist_tracks(target_playlist_id)
                target_tracks = target_results['items']
                target_track_ids = {item['track']['id'] for item in target_tracks}

                if track_id not in target_track_ids:
                    sp.user_playlist_add_tracks(sp.current_user()['id'], target_playlist_id, [track_id])
                    print(f"Moved track {track['name']} to {target_playlist_name} playlist.")
                    sp.playlist_remove_all_occurrences_of_items(playlist_id, [track_id])
                else:
                    print(f"Track {track['name']} is already in {target_playlist_name} playlist.")
                    sp.playlist_remove_all_occurrences_of_items(playlist_id, [track_id])
                
                # mark track as processed
                processed_track_ids.add(track_id)
                break

    return jsonify({"message": "Playlist sorted successfully!"})


@app.route('/get-playlists', methods=['GET'])
def get_playlists():
    playlists = []
    results = sp.current_user_playlists()
    while results:
        playlists.extend(results['items'])
        results = sp.next(results) if results['next'] else None
    
    playlist_data = [
        {'id': playlist['id'], 'name': playlist['name']}
        for playlist in playlists
    ]
    return jsonify(playlist_data)

@app.route('/get-playlist-details/<playlist_id>', methods=['GET'])
def get_playlist_details(playlist_id):
    try:
        playlist = sp.playlist(playlist_id)

        playlist_data = {
            'id': playlist['id'],
            'name': playlist['name'],
            'description': playlist.get('description', 'No description available'),
            'track_count': playlist['tracks']['total'],
            'image_url': playlist['images'][0]['url'] if playlist['images'] else '/assets/default-cover-image.jpg',  # Fallback to a default image if no image is available
            'genres': [item['name'] for item in playlist.get('genres', [])] 
        }

        return jsonify(playlist_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/get-top-tracks', methods=['GET'])
def get_top_tracks():
    try:
        top_tracks = sp.current_user_top_tracks(time_range='long_term', limit=10)

        track_data = []
        for item in top_tracks['items']:
            track_data.append({
                'name': item['name'],
                'artist': item['artists'][0]['name'],
                'image_url': item['album']['images'][0]['url'] if item['album']['images'] else '/assets/default-cover-image.jpg',
                'url': item['external_urls']['spotify']
            })

        return jsonify(track_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)
