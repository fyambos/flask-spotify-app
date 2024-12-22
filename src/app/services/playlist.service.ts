import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class PlaylistService {

  private apiUrl = 'http://localhost:5000/'; 

  constructor(private http: HttpClient) { }

  sortPlaylist(playlistId: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/sort-playlist`, { playlist_id: playlistId });
  }
  getPlaylists(): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/get-playlists`);
  }
  getPlaylistDetails(playlistId: string): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/get-playlist-details/${playlistId}`);
  }
}
