import { Component, OnInit } from '@angular/core';
import { TrackService } from 'src/app/services/track.service';

@Component({
  selector: 'app-recently-played',
  templateUrl: './recently-played.component.html',
})
export class RecentlyPlayedComponent implements OnInit {
  tracks: any[] = [];

  constructor(private trackService: TrackService) {}

  ngOnInit(): void {
    this.trackService.getRecentlyPlayedTracks().subscribe({
      next: (data) => {
        this.tracks = data;
      },
      error: (err) => {
        console.error('Error fetching recently played tracks:', err);
      }
    });
  }
}
