import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { PlaylistService, SetupStatus } from './playlist.service';

/** What the app can do right now (Spotify connected, playlists imported...), shared by the pages. */
@Injectable({ providedIn: 'root' })
export class StatusService {
  readonly status$ = new BehaviorSubject<SetupStatus | null>(null);
  readonly backendDown$ = new BehaviorSubject<boolean>(false);

  constructor(private playlistService: PlaylistService) { }

  refresh(): void {
    this.playlistService.getSetupStatus().subscribe({
      next: status => { this.backendDown$.next(false); this.status$.next(status); },
      error: () => this.backendDown$.next(true),
    });
  }

  get status(): SetupStatus | null {
    return this.status$.value;
  }

  /** Spotify can be read and written (Premium connected, not blocked). */
  get spotifyReady(): boolean {
    const spotify = this.status?.spotify;
    return !!spotify?.connected && !spotify.limit && this.status?.import.source !== 'tunemymusic'
      && this.status?.import.source !== 'spotify-export';
  }
}
