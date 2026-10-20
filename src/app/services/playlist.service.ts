import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_URL } from './api';

export interface GenrePlaylist {
  id: string;
  name: string;
  /** null: a playlist that only exists in the app until the next Spotify sync. */
  playlist_id: string | null;
  genre_names: string[];
  exclude_genres: string[];
  album_keywords: string[];
  title_keywords: string[];
}

export interface AppConfig {
  music_dir: string;
  audio_format: string;
  fallback_genre: string;
  artist_history: { enabled: boolean; min_share: number };
  multi_playlist: boolean;
  download: { mode: 'all' | 'selected'; playlists: string[]; seen: string[] };
  layout: { preset: LayoutPreset; folder: string; order: string[] };
  sort_from: string[];
  import_reminder: boolean;
  removed: { mode: 'keep' | 'move' | 'delete'; folder: string };
  youtube_cookies: string;
  apple_music_auto: boolean;
  playlist_folders: { [spotifyPlaylistId: string]: string };
  default_folder: string;
  folders: string[];
  artist_rules: { [artistId: string]: { name: string; playlist: string } };
  playlists: GenrePlaylist[];
}

export interface LayoutExample {
  album_artist: string;
  album: string;
  file: string;
  first_playlist: string | null;
  separator: string;
  music_dir: string;
}

export type LayoutPreset = 'artist_album' | 'artist' | 'one_folder' | 'first_playlist';

export interface LikeItem {
  track_id: string;
  name: string;
  artists: string[];
  artist_id: string;
  album: string;
  image_url?: string | null;
  genres: string[];
  playlist: string | null;
  also?: string[];
  suggestion: string | null;
  status: 'already' | 'auto' | 'manual' | 'review' | 'applied';
  reason: string;
}

export interface SpotifyPlaylist {
  id: string;
  name: string;
  image_url: string | null;
  track_count: number;
  /** false: playlist of another user. null: unknown (imported from a file). */
  owned: boolean | null;
  maybe_incomplete: boolean;
  new: boolean;
  app_only: boolean;
}

export interface ImportStatus {
  source: 'spotify' | 'tunemymusic' | 'spotify-export' | null;
  file: string | null;
  updated_at: string | null;
  days: number | null;
  reminder: boolean;
  watching: boolean;
}

export interface ImportState {
  job: JobState;
  status: ImportStatus;
  result: { kind: string; file: string; songs: number; playlists: number; songs_added: number; songs_removed: number; playlists_added: string[] } | null;
  watch: { last: string | null; error: string | null };
}

export interface SpotifySyncChange {
  entry_id: string;
  name: string;
  create: boolean;
  to_add: string[];
  removed_on_spotify: string[];
}

export type SuggestionType = 'add_genre' | 'exclude_genre' | 'album_keyword' | 'title_keyword' | 'move_above' | 'multi_playlist' | 'artist';

export interface RuleSuggestion {
  type: SuggestionType;
  playlist: string;
  value: string;
  artist?: string;
  count?: number;
}

export interface MisplacedSong {
  track_id: string;
  name: string;
  artists: string[];
  album: string;
  image_url?: string | null;
  genres: string[];
  went_to: string | null;
  reason: string;
  suggestions: RuleSuggestion[];
}

export interface PlaylistStats {
  track_count: number;
  genre_coverage?: number;
  accuracy: number;
  accuracy_new_artists: number;
  to_review: number;
  goes_elsewhere: { [genre: string]: number };
  misplaced?: MisplacedSong[];
  suggestions?: RuleSuggestion[];
}

export interface SetupStatus {
  spotify: { connected: boolean; name?: string | null; image_url?: string | null; error?: string; limit?: string;
             missing_keys?: boolean; needs_login?: boolean; logging_in?: boolean };
  lastfm: boolean;
  ffmpeg: boolean;
  configured: boolean;
  /** Playlists known to the app (from Spotify or an imported file). */
  playlists: boolean;
  import: ImportStatus;
  sort: { pending: number; waiting: boolean };
}

export interface JobState {
  running: boolean;
  step?: string;
  done?: number;
  total?: number;
  current?: string[];
  error?: string | null;
}

export interface SetupAnalysis {
  job: JobState;
  evaluation: JobState;
  proposal: { generated_at: string; multi_playlist?: boolean; playlists: GenrePlaylist[]; stats: { [id: string]: PlaylistStats } } | null;
}

export interface AccuracyState {
  job: JobState;
  result: { generated_at: string; rules_hash: string; stats: { [id: string]: PlaylistStats } } | null;
  rules_hash: string;
}

export interface LibraryTrack {
  track_id: string;
  title: string;
  artists: string[];
  album: string;
  image_url?: string | null;
  folder: string;
  path: string | null;
  status: 'ok' | 'failed' | 'removed';
  error?: string;
  removed_at?: string;
}

export interface ImportResult {
  finished_at: string;
  source: string;
  mode: 'copy' | 'move';
  files: number;
  matched: number;
  already: number;
  unmatched: string[];
}

export interface LibraryState {
  job: JobState;
  import: ImportResult | null;
  apple_music: { available: boolean; job: JobState };
  music_dir: string;
  downloaded: number;
  failed: LibraryTrack[];
  removed: LibraryTrack[];
  playlists: number;
  plan: { generated_at: string; to_download: number; to_move: number; to_remove: number; playlists: number; moves_folder: boolean } | null;
}

export interface LikesState {
  job: JobState;
  preview: { generated_at: string; items: LikeItem[]; sources?: string[]; both?: string[] } | null;
}

@Injectable({
  providedIn: 'root'
})
export class PlaylistService {

  private apiUrl = API_URL;

  constructor(private http: HttpClient) { }

  getPlaylists(): Observable<SpotifyPlaylist[]> {
    return this.http.get<SpotifyPlaylist[]>(`${this.apiUrl}/get-playlists`);
  }

  spotifyLogin(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/setup/login`, {});
  }
  getSetupStatus(): Observable<SetupStatus> {
    return this.http.get<SetupStatus>(`${this.apiUrl}/setup/status`);
  }
  startSetupAnalysis(playlists: { playlist_id: string; name: string }[], multiPlaylist: boolean): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/setup/analyze`, { playlists, multi_playlist: multiPlaylist });
  }
  evaluateSetup(playlists: GenrePlaylist[], multiPlaylist: boolean): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/setup/evaluate`, { playlists, multi_playlist: multiPlaylist });
  }
  addArtistRule(artistId: string, name: string, playlist: string): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/config/artist-rules`, { artist_id: artistId, name, playlist });
  }
  getSetupAnalysis(): Observable<SetupAnalysis> {
    return this.http.get<SetupAnalysis>(`${this.apiUrl}/setup/analyze`);
  }
  applySetup(playlists: GenrePlaylist[], fallbackGenre: string, multiPlaylist: boolean): Observable<AppConfig> {
    return this.http.post<AppConfig>(`${this.apiUrl}/setup/apply`, { playlists, fallback_genre: fallbackGenre, multi_playlist: multiPlaylist });
  }
  getPlaylistDetails(playlistId: string): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/get-playlist-details/${playlistId}`);
  }

  getConfig(): Observable<AppConfig> {
    return this.http.get<AppConfig>(`${this.apiUrl}/config`);
  }
  addGenrePlaylist(entry: Partial<GenrePlaylist>): Observable<GenrePlaylist> {
    return this.http.post<GenrePlaylist>(`${this.apiUrl}/config/playlists`, entry);
  }
  updateGenrePlaylist(id: string, changes: Partial<GenrePlaylist>): Observable<GenrePlaylist> {
    return this.http.patch<GenrePlaylist>(`${this.apiUrl}/config/playlists/${id}`, changes);
  }
  deleteGenrePlaylist(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/config/playlists/${id}`);
  }
  reorderGenrePlaylists(ids: string[]): Observable<AppConfig> {
    return this.http.put<AppConfig>(`${this.apiUrl}/config/playlists/order`, { ids });
  }
  revealConfig(): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/config/reveal`, {});
  }
  updateSettings(changes: Partial<AppConfig>): Observable<AppConfig> {
    return this.http.put<AppConfig>(`${this.apiUrl}/config/settings`, changes);
  }
  deleteArtistRule(artistId: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/config/artist-rules/${artistId}`);
  }

  startAccuracyCheck(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/genres/accuracy`, {});
  }
  getAccuracy(): Observable<AccuracyState> {
    return this.http.get<AccuracyState>(`${this.apiUrl}/genres/accuracy`);
  }

  getLibrary(): Observable<LibraryState> {
    return this.http.get<LibraryState>(`${this.apiUrl}/library`);
  }
  checkLibrary(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/library/check`, {});
  }
  syncLibrary(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/library/sync`, {});
  }
  importLibrary(path: string, mode: 'copy' | 'move'): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/library/import`, { path, mode });
  }
  updateAppleMusic(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/library/apple-music`, {});
  }
  getLayoutExample(): Observable<LayoutExample> {
    return this.http.get<LayoutExample>(`${this.apiUrl}/library/example`);
  }
  revealLibrary(): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/library/reveal`, {});
  }

  startLikesPreview(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/likes/preview`, {});
  }
  getLikesState(): Observable<LikesState> {
    return this.http.get<LikesState>(`${this.apiUrl}/likes/preview`);
  }
  resolveLike(trackId: string, playlist: string, rememberArtist: boolean): Observable<LikeItem> {
    return this.http.post<LikeItem>(`${this.apiUrl}/likes/review/${trackId}`, { playlist, remember_artist: rememberArtist });
  }
  applyLikes(): Observable<{ added: { [genre: string]: number }; spotify: 'written' | 'review' | 'offline' }> {
    return this.http.post<{ added: { [genre: string]: number }; spotify: 'written' | 'review' | 'offline' }>(`${this.apiUrl}/likes/apply`, {});
  }

  markPlaylistsSeen(ids: string[]): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/download/seen`, { ids });
  }

  getImport(): Observable<ImportState> {
    return this.http.get<ImportState>(`${this.apiUrl}/import`);
  }
  watchDownloads(): Observable<{ watching: boolean; folder: string }> {
    return this.http.post<{ watching: boolean; folder: string }>(`${this.apiUrl}/import/watch`, {});
  }
  uploadPlaylistsFile(file: File): Observable<any> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<any>(`${this.apiUrl}/import/file`, form);
  }

  getSpotifySync(): Observable<{ available: boolean; changes: SpotifySyncChange[]; job: JobState }> {
    return this.http.get<{ available: boolean; changes: SpotifySyncChange[]; job: JobState }>(`${this.apiUrl}/sort/spotify`);
  }
  runSpotifySync(): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/sort/spotify`, {});
  }
}
