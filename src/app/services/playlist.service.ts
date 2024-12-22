import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class PlaylistService {

  private apiUrl = 'http://localhost:5000/sort-playlist'; 

  constructor(private http: HttpClient) { }

  sortPlaylist(playlistId: string): Observable<any> {
    return this.http.post<any>(this.apiUrl, { playlist_id: playlistId });
  }
}
