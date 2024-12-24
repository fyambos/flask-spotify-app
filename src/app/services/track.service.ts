import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class TrackService {
  private apiUrl = 'http://localhost:5000';

  constructor(private http: HttpClient) {}

  getTopTracks(): Observable<any> {
    return this.http.get<any[]>(`${this.apiUrl}/get-top-tracks`);
  }
  getRecentlyPlayedTracks(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/get-recently-played`);
  }
}
