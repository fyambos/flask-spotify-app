import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_URL } from './api';

export interface Song {
  title: string;
  artist: string;
  /** Album cover. */
  image: string | null;
}

export interface Stats {
  songs: number;
  playlists: { id: string; name: string }[];
  /** Each part is missing when the app has nothing to show for it. */
  parts: {
    short?: { songs: number; artists: number; hours: number; covers: string[] };
    artists?: { top: { name: string; songs: number; image: string | null }[]; once: number };
    genres?: { top: { name: string; songs: number }[]; rare: string[] };
    years?: { per_year: { year: number; songs: number }[]; from: number; to: number; oldest: (Song & { year: number })[] };
    added?: { per_month: { month: string; songs: number }[]; busiest: string; busiest_songs: number };
    popularity?: { hits: number; known: number; discoveries: number; least_known: Song[] };
    mood?: {
      scales: { key: string; average: number; low: Song[]; high: Song[] }[];
      /** [happiness 0-1, energy 0-1, title, artist] of every song. */
      points: [number, number, string, string][];
      minor: number | null;
      bpm: number | null;
      pace: 'slow' | 'medium' | 'fast' | null;
    };
    length?: { average: string; longest: (Song & { length: string })[] };
    listening?: { hours: number; top_artists: { name: string; hours: number }[]; by_hour: number[] };
  };
}

@Injectable({
  providedIn: 'root',
})
export class StatsService {
  constructor(private http: HttpClient) { }

  /** All the playlists, or one ('' for all). */
  getStats(playlist: string): Observable<Stats> {
    return this.http.get<Stats>(`${API_URL}/stats`, { params: playlist ? { playlist } : {} });
  }
}
