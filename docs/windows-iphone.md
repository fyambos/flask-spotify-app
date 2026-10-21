# Spotify playlists on an iPhone, from Windows (no Spotify Premium)

So first you install what the app needs. Open PowerShell and run these one by one:

```
winget install Git.Git
winget install Python.Python.3.14
winget install OpenJS.NodeJS.LTS
```

Then install iTunes from the Microsoft Store, open it once and accept the license. Don't install the Apple Music or Apple Devices apps: once they're installed, iTunes doesn't handle music anymore.

Close PowerShell and open a new one, so it finds what you just installed. Go to any folder, for example Documents, and download the app:

```
cd $HOME\Documents
git clone https://github.com/fyambos/flask-spotify-app
cd flask-spotify-app\src\backend
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python app.py
```

Leave this window open, it's the backend.

Open a second PowerShell window:

```
cd $HOME\Documents\flask-spotify-app
npm install
npm start
```

In PowerShell, `npm` runs a script that Windows blocks by default. To avoid changing your script policy, use `npm.cmd install` and `npm.cmd start` instead.

Leave it open too, then go to http://localhost:4200 in your browser.

## In the app

1. Click Import from any streaming service, and leave that page open.
2. Click Open TuneMyMusic, pick Spotify, log in and load your library. Unselect the playlists you don't want (playlists made by other people come with 500 songs max), then choose Export to file, CSV. Save the file in Downloads, the app imports it.
3. Go to Settings, Playlists to download, and pick All my playlists or Choose playlists.
4. Go to Library and click Sync. The songs go to Music\Music Sorter and into iTunes, with your playlists in a Music Sorter folder.

## On the iPhone

1. Plug the iPhone into the PC and click the iPhone icon in iTunes.
2. Go to Music, check Sync Music, then Selected playlists, check the Music Sorter playlists and click Apply.
3. In Summary, turn on Sync with this iPhone over Wi-Fi. Next time, the iPhone syncs without the cable when it's on the same Wi-Fi as the PC and iTunes is open.

If you have an Apple Music subscription with Sync Library turned on in the iPhone settings (Music), iTunes can't sync music to it. Turn Sync Library off first.

## New songs later

Start the app again (python app.py in src\backend, npm start in the app folder), open the import page, export again from TuneMyMusic, then click Sync in Library, then sync the iPhone in iTunes.
