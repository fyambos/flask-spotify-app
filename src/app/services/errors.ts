/** The words for the backend's error codes: the backend says what happened, the page says it. */
const TEXTS: { [code: string]: string } = {
  busy: 'Wait for the current sync to finish.',
  analysis_running: 'Wait for the analysis to finish.',
  spotify_limit: 'Spotify request limit reached for today. Try again after {until}.',
  spotify_down: 'Spotify did not respond. Try again in a moment.',
  youtube_down: 'YouTube Music did not respond. Try again in a moment.',
  lastfm_down: 'Last.fm did not respond. Try again in a moment.',
  no_internet: 'No internet connection. Try again in a moment.',
  spotify_keys_missing: 'Spotify keys are missing in src/backend/.env.',
  not_an_export: 'This file is not an export from TuneMyMusic, Exportify or Spotify.',
  no_playlists: 'No playlists yet. Connect Spotify or import your playlists first.',
  sync_first: 'Click Sync on the Library page first.',
  not_in_not_found: 'This song is no longer in Not found.',
  not_youtube_link: 'This is not a YouTube Music or YouTube link.',
  folder_not_found: 'Folder not found: {folder}',
  music_folder_changed: 'The music folder changed. Run Sync first, then import.',
  apple_incomplete: 'Apple Music did not take every change: {playlists}. Run Update Apple Music again.',
  apple_not_responding: 'Apple Music did not respond. Open Apple Music, then try again.',
  playlist_exists: 'This playlist is already in the list.',
  unexpected: "Something went wrong. The details are in the backend's terminal.",
  // Why a song is in Not found.
  not_found: 'Not found on YouTube Music',
  unavailable: "YouTube doesn't give this video. Choose another version.",
  not_reached: 'YouTube Music did not respond. Retried at the next Sync.',
  wrong_version: 'Wrong version found on YouTube Music',
  download_failed: 'Could not be downloaded. Choose another version.',
  file_missing: 'File not found',
  wrong_length: 'Only found in another length: {actual} instead of {expected}.',
};

export function errorText(code: string | null | undefined, params?: { [key: string]: string } | null): string {
  if (!code) return '';
  const text = TEXTS[code] ?? TEXTS['unexpected'];
  return text.replace(/\{(\w+)\}/g, (_, key) => params?.[key] ?? '');
}
