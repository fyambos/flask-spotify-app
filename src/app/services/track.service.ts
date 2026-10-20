import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { API_URL } from './api';

@Injectable({
  providedIn: 'root',
})
export class TrackService {
  private apiUrl = API_URL;

  constructor(private http: HttpClient) {}

  getTopTracks(): Observable<any> {
    return this.http.get<any[]>(`${this.apiUrl}/get-top-tracks`);
  }
  getRecentlyPlayedTracks(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/get-recently-played`);
  }
}
