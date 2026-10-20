import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_URL } from './api';

export interface GenrePlaylist {
  id: string;
  name: string;
  playlist_id: string;
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
  non_liked: { enabled: boolean; folder: string };
  removed: { mode: 'keep' | 'move' | 'delete'; folder: string };
  youtube_cookies: string;
  apple_music_auto: boolean;
  apple_folders: { [spotifyPlaylistId: string]: string };
  artist_rules: { [artistId: string]: { name: string; playlist: string } };
  playlists: GenrePlaylist[];
}

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
  owned: boolean;
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
  spotify: { connected: boolean; name?: string; image_url?: string | null; error?: string };
  lastfm: boolean;
  ffmpeg: boolean;
  configured: boolean;
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
  playlist_names: { [id: string]: string };
  import: ImportResult | null;
  apple_music: { available: boolean; job: JobState };
  music_dir: string;
  folders: { name: string; count: number }[];
  downloaded: number;
  failed: LibraryTrack[];
  removed: LibraryTrack[];
  playlists: number;
  plan: { generated_at: string; to_download: number; to_move: number; to_remove: number; pending_liked: number; playlists: number } | null;
}

export interface LikesState {
  job: JobState;
  preview: { generated_at: string; items: LikeItem[] } | null;
}

@Injectable({
  providedIn: 'root'
})
export class PlaylistService {

  private apiUrl = API_URL;

  constructor(private http: HttpClient) { }

  sortPlaylist(playlistId: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/sort-playlist`, { playlist_id: playlistId });
  }
  getPlaylists(): Observable<SpotifyPlaylist[]> {
    return this.http.get<SpotifyPlaylist[]>(`${this.apiUrl}/get-playlists`);
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
  applyLikes(): Observable<{ added: { [genre: string]: number } }> {
    return this.http.post<{ added: { [genre: string]: number } }>(`${this.apiUrl}/likes/apply`, {});
  }
}
