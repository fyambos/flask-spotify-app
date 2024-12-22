import { Component, OnInit } from '@angular/core';
import { Firestore } from '@angular/fire/firestore';
import { collection, addDoc } from 'firebase/firestore';
import { PlaylistService } from 'src/app/services/playlist.service';

@Component({
  selector: 'app-set-playlists',
  templateUrl: './set-playlists.component.html',
})
export class SetPlaylistsComponent implements OnInit {
  playlists: any[] = []; // For storing playlists fetched from the user's Spotify account
  selectedPlaylistId: string = ''; // The playlist id selected by the user
  genreNames: string = ''; // Input for genre names
  message: string = ''; // For showing success or error messages

  constructor(private playlistService: PlaylistService, private firestore: Firestore) { }

  ngOnInit(): void {
    this.fetchPlaylists();
  }

  // Fetch all playlists from the user's account
  fetchPlaylists() {
    this.playlistService.getPlaylists().subscribe(playlists => {
      this.playlists = playlists;
    });
  }

  // Add the playlist data to Firebase Firestore
  async savePlaylist() {
    if (this.selectedPlaylistId && this.genreNames.trim()) {
      try {
        const genreNamesArray = this.genreNames.split(',').map(genre => genre.trim());

        // Add playlist data to Firestore
        await addDoc(collection(this.firestore, 'playlists'), {
          genre_names: genreNamesArray,
          playlist_id: this.selectedPlaylistId
        });

        this.message = 'Playlist added successfully!';
        this.genreNames = ''; // Clear the genre names input
      } catch (error) {
        console.error('Error adding playlist: ', error);
        this.message = 'Error adding playlist.';
      }
    } else {
      this.message = 'Please select a playlist and provide genre names.';
    }
  }
}
