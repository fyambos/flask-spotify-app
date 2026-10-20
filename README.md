# Music Sorter

Sorts your Spotify Liked Songs into Spotify playlists of your choosing, and keeps a local copy of your playlists (MP3 files + `.m3u8` playlists) for Apple Music, Android or Windows.

Runs on your computer: a Flask backend (`src/backend`) and an Angular web app (`src/app`). Nothing is hard-coded: everything is configured from the app and saved in `src/backend/data/`.

## Features

- **Setup assistant**: pick your genre playlists. The app learns how they are sorted (genres, artists, album keywords), shows how accurate the rules are and proposes fixes.
- **Liked Songs**: classifies new liked songs, lets you review them, then adds them to the playlists on Spotify. Your Liked Songs are never modified.
- **Genres**: rules per playlist (genres, excluded genres, album and title keywords), priority by drag and drop, misplaced songs with suggested rules.
- **Library**: downloads the songs of your genre playlists into `<music folder>/<Genre>/`, writes every playlist you own as an `.m3u8` file, follows the changes you make on Spotify, imports files you downloaded before.
- **Apple Music** (Mac): after each sync, adds the songs and writes your playlists in a "Music Sorter" folder.

## Requirements

- Python 3.10+
- Node.js 18+
- ffmpeg
  - Mac: `brew install ffmpeg`
  - Windows: `winget install ffmpeg`
  - Linux: `sudo apt install ffmpeg`
- A Spotify account with **Premium** (required by Spotify for developer apps since February 2026)
- Optional: a Last.fm API key (much better genres), a YouTube Music Premium account (256 kbps downloads)

## Setup on a new computer

### 1. Spotify and Last.fm keys

1. Go to the [Spotify developer dashboard](https://developer.spotify.com/dashboard) → **Create app**.
   - Redirect URI: `http://127.0.0.1:8888/callback` (Spotify no longer accepts `localhost`)
   - API: **Web API**
   - In **Settings**, copy the **Client ID** and the **Client secret**.
2. Optional: create a Last.fm API account at https://www.last.fm/api/account/create and copy the **API key**.
3. Create the backend `.env` file:

```bash
cp src/backend/.env.example src/backend/.env
```

Fill `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` and `LASTFM_API_KEY`.

### 2. Backend

```bash
cd src/backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The API runs on http://localhost:5001 (port 5000 is used by AirPlay on macOS). On the first start, a browser window opens to log in to Spotify.

### 3. Web app

```bash
npm install
npm start
```

Open http://localhost:4200. The setup assistant opens on the first launch.

### Moving to another computer

Your settings and rules are in `src/backend/data/config.json`, and the list of downloaded songs in `src/backend/data/library.json`. Copy the `data` folder next to the new backend, or set `SPOTSORT_DATA_DIR` in `.env` to a synced folder (iCloud Drive, Dropbox…). Copy your music folder too, or import it from the Library page.

## How sorting works

For each liked song not yet in one of your genre playlists:

1. a choice you remembered for its artist
2. album and title keywords, in priority order
3. artist history: the playlist that already holds most of the artist's songs
4. genres (Spotify + Last.fm), the closest playlist wins when several match
5. otherwise the song goes to your review list

Excluded genres apply to every step. Songs you already placed are never moved by the rules.

**Several playlists per song** (Settings): a song can go to every playlist whose album or title keywords match, plus its style playlist. Downloads use the first one.

## Library

- **Check** shows what the next sync will do. **Sync** downloads the missing songs, moves the ones you moved on Spotify and rewrites the playlists.
- Folder of a song: its first genre playlist, in priority order.
- **Non-Liked Songs** (Settings): also download songs of your other playlists that are not in your Liked Songs, into their own folder.
- **Removed songs** (Settings): songs no longer in any synced playlist are kept, moved to a folder (default `_Removed`) or deleted.
- **Import existing files**: matches files you downloaded before (by Spotify link, or artist + title + duration) and moves them to the folder of their current playlist, without downloading them again.
- Playlists are written to `<music folder>/Playlists/*.m3u8` with relative paths, so the whole folder can be copied anywhere.

Tags written: title, artists, album, album artist, track and disc number, year, cover, ISRC, genre (the artist's first Spotify genre) and the Spotify id.

Audio comes from YouTube Music through [spotDL](https://github.com/spotDL/spotify-downloader). Without Premium the source is about 130 kbps. With a YouTube Music Premium account, export your YouTube cookies to a `cookies.txt` file (browser extension "Get cookies.txt LOCALLY") and set its path in Settings to get 256 kbps.

### On your devices

- **Mac**: after each sync, the app adds the songs to Apple Music and writes your playlists in a "Music Sorter" folder (Library page → "After each sync", or the Update Apple Music button). macOS asks once for permission to control Music.
- **iPhone**, set up once: with Apple Music or iTunes Match, turn on Sync Library on the Mac and the iPhone. Without it, in Finder select the iPhone, sync the "Music Sorter" playlists and turn on "Show this iPhone when on Wi-Fi": it syncs while the iPhone charges on the same Wi-Fi.
- **Android**: copy the music folder to the phone, or keep it in sync with [Syncthing](https://syncthing.net). Poweramp, Samsung Music and VLC read the `.m3u8` playlists.
- **Windows**: open the music folder in MusicBee, foobar2000 or VLC.

## Command line

```bash
cd src/backend
python analyze.py                  # genres of the songs in your genre playlists -> data/reports/genre-analysis.md
python analyze.py --list-playlists # your Spotify playlists with their ids
```

## Project structure

```plain text
src/
├── app/                      Angular web app
└── backend/
    ├── app.py                API
    ├── config_store.py       settings and rules (data/config.json)
    ├── spotify_client.py     Spotify Web API (2026 changes)
    ├── genres.py             Spotify + Last.fm genres, keyword matching
    ├── sorter.py             liked songs classification
    ├── setup_analysis.py     rule learning, accuracy, suggestions
    ├── library.py            downloads, .m3u8 playlists, import
    ├── apple_music.py        Apple Music sync (macOS)
    ├── analyze.py            genre analysis (command line)
    └── data/                 (git-ignored) settings, Spotify token, caches, library
```

## License

MIT
