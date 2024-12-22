import { Component } from '@angular/core';
import { PlaylistService } from 'src/app/services/playlist.service';

@Component({
  selector: 'app-sort-playlist',
  templateUrl: './sort-playlist.component.html',
})
export class SortPlaylistComponent {
  constructor(private playlistService: PlaylistService) { }

  sortPlaylist() {
    const playlistId = '1teo3l55NhBcogXA6UOQ1O';
    this.playlistService.sortPlaylist(playlistId).subscribe({
      next: response => {
        alert('Playlist sorted successfully!');
        console.log(response.message);
      },
      error: error => {
        alert('An error occurred while sorting the playlist');
        console.error(error);
      }
    });
  }
}
