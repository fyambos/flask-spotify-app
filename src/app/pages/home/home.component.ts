import { Component, OnInit } from '@angular/core';
import { APP_TITLE, FEATURES } from 'src/app/services/features';
import { LibraryState, LikesState, PlaylistService } from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
})
export class HomeComponent implements OnInit {
  title = APP_TITLE;
  features = FEATURES;
  library: LibraryState | null = null;
  likes: LikesState | null = null;

  constructor(private playlistService: PlaylistService, private statusService: StatusService) { }

  ngOnInit(): void {
    // Stats come from Spotify only.
    this.statusService.status$.subscribe(status => {
      this.features = FEATURES.filter(f => f.path !== '/stats' || !!status?.playlists || !!status?.spotify?.connected);
    });
    this.playlistService.getLibrary().subscribe(state => this.library = state);
    this.playlistService.getLikesState().subscribe(state => this.likes = state);
  }

  count(status: string): number {
    return (this.likes?.preview?.items || []).filter(i => status === 'planned'
      ? i.status === 'auto' || i.status === 'manual' : i.status === status).length;
  }
}
