import { Component, OnInit } from '@angular/core';
import { TrackService } from 'src/app/services/track.service';

@Component({
  selector: 'app-top-tracks',
  templateUrl: './top-tracks.component.html',
})
export class TopTracksComponent implements OnInit {
  topTracks: any[] = [];

  constructor(private trackService: TrackService) {}

  ngOnInit(): void {
    this.trackService.getTopTracks().subscribe({
      next: (data) => {
        this.topTracks = data;
      },
      error: (err) => {
        console.error('Error fetching top tracks:', err);
      }
    });
  }
}
