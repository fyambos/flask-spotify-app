import { Component, OnInit } from '@angular/core';
import { PlaylistService } from 'src/app/services/playlist.service';

@Component({
  selector: 'app-sort-playlist',
  templateUrl: './sort-playlist.component.html',
})
export class SortPlaylistComponent implements OnInit {
  playlists: { id: string; name: string }[] = [];
  selectedPlaylistId: string | null = null;

  constructor(private playlistService: PlaylistService) { }

  ngOnInit() {
    this.fetchPlaylists();
  }

  fetchPlaylists() {
    this.playlistService.getPlaylists().subscribe({
      next: (response) => {
        this.playlists = response.map((playlist: any) => ({
          id: playlist.id,
          name: playlist.name,
        }));
      },
      error: (error) => {
        alert('Failed to fetch playlists');
        console.error(error);
      },
    });
  }

  sortPlaylist() {
    if (!this.selectedPlaylistId) {
      alert('Please select a playlist');
      return;
    }

    this.playlistService.sortPlaylist(this.selectedPlaylistId).subscribe({
      next: response => {
        alert('Playlist sorted successfully!');
        console.log(response.message);
      },
      error: error => {
        alert('An error occurred while sorting the playlist');
        console.error(error);
      },
    });
  }
}
