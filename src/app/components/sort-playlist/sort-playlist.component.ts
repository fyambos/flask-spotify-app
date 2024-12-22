import { Component } from '@angular/core';

@Component({
  selector: 'app-sort-playlist',
  templateUrl: './sort-playlist.component.html',
})
export class SortPlaylistComponent {
  constructor() { }

  sortPlaylist() {
    console.log('Sort Playlist button clicked!');
  }
}
