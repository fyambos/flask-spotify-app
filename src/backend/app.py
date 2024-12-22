from flask import Flask, request, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask_cors import CORS
from dotenv import load_dotenv
import os
load_dotenv()
app = Flask(__name__)
CORS(app)

client_id = os.getenv('SPOTIFY_CLIENT_ID')
client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
redirect_uri = 'http://localhost:8888/callback'
scope = 'playlist-modify-private'

# set up Spotify OAuth
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id,
                                               client_secret=client_secret,
                                               redirect_uri=redirect_uri,
                                               scope=scope))

Playlists = {
    'Anime': {'genre_names': ['j-', 'anime', 'japanese', 'shonen', 'okinawan', 'otacore'], 'playlist_id': '5LNAe2PwYP6FoPIxSPbb3R'},
    'RnBSoul': {'genre_names': ['r&b', 'soul', 'blues', 'jazz', 'reggae', 'griot'], 'playlist_id': '2rH11zBidWaqocnRWIJWMl'},
    'Kr': {'genre_names': ['k-', 'korean'], 'playlist_id': '5LNAe2PwYP6FoPIxSPbb3R'},
    'Phonk': {'genre_names': ['phonk'], 'playlist_id': '5LNAe2PwYP6FoPIxSPbb3R'},
    'Scorecore': {'genre_names': ['video game music', 'soundtrack', 'new age piano', 'scorecore', 'baroque pop', 'bajki', 'neo mellow', 'epicore'], 'playlist_id': '1uUQ63t93OlPm284qbxwSb'},
    'BOP': {'genre_names': ['pop'], 'playlist_id': '3d7ie64qO1fmgU3HKU7lvj'},
    'Symphonic': {'genre_names': ['metal', 'grunge', 'rock'], 'playlist_id': '4ysOm1s5OflY8YPptQvDrr'},
}

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

        # find the appropriate target playlist
        for playlist_name, playlist_data in Playlists.items():
            
            if any(genre_name in genre for genre in genres for genre_name in playlist_data['genre_names']):
                target_playlist_id = playlist_data['playlist_id']

                # fetch existing tracks in the target playlist
                target_results = sp.playlist_tracks(target_playlist_id)
                target_tracks = target_results['items']
                target_track_ids = {item['track']['id'] for item in target_tracks}
                if track_id not in target_track_ids:
                    sp.user_playlist_add_tracks(sp.current_user()['id'], target_playlist_id, [track_id])
                    print(f"Moved track {track['name']} to {playlist_name} playlist.")
                else:
                    print(f"Track {track['name']} is already in {playlist_name} playlist.")
                sp.playlist_remove_all_occurrences_of_items(playlist_id, [track_id])
                # mark track as processed
                processed_track_ids.add(track_id)
                break

    return jsonify({"message": "Playlist sorted successfully!"})


if __name__ == '__main__':
    app.run(debug=True)
