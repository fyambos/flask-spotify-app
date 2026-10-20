import { Component, OnInit } from '@angular/core';
import { TrackService } from 'src/app/services/track.service';

@Component({
  selector: 'app-stats',
  templateUrl: './stats.component.html',
})
export class StatsComponent implements OnInit {
  tab: 'top' | 'recent' = 'top';
  topTracks: any[] = [];
  recentTracks: any[] = [];
  loading = true;

  constructor(private trackService: TrackService) { }

  ngOnInit(): void {
    this.trackService.getTopTracks().subscribe({
      next: (tracks) => { this.topTracks = tracks; this.loading = false; },
      error: () => this.loading = false,
    });
    this.trackService.getRecentlyPlayedTracks().subscribe(tracks => this.recentTracks = tracks);
  }

  get tracks(): any[] {
    return this.tab === 'top' ? this.topTracks : this.recentTracks;
  }
}
