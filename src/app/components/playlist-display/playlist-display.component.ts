import { Component, OnInit } from '@angular/core';
import { Firestore } from '@angular/fire/firestore';
import { collection, getDocs } from 'firebase/firestore';
import { PlaylistService } from 'src/app/services/playlist.service';

@Component({
  selector: 'app-playlist-display',
  templateUrl: './playlist-display.component.html',
})
export class PlaylistDisplayComponent implements OnInit {
  playlists: any[] = [];

  constructor(
    private firestore: Firestore,
    private playlistService: PlaylistService
  ) {}

  ngOnInit(): void {
    this.getPlaylists();
  }

  async getPlaylists(): Promise<void> {
    const playlistsCollection = collection(this.firestore, 'playlists');
    try {
      const snapshot = await getDocs(playlistsCollection);
      this.playlists = snapshot.docs.map((doc) => {
        const playlist = doc.data();
        playlist['details'] = null;
        return playlist;
      });

      for (const playlist of this.playlists) {
        this.getPlaylistDetails(playlist.playlist_id);
      }
    } catch (error) {
      console.error('Error fetching playlists from Firestore:', error);
    }
  }

  getPlaylistDetails(playlistId: string): void {
    this.playlistService.getPlaylistDetails(playlistId).subscribe({
      next: (data) => {
        const playlist = this.playlists.find(p => p.playlist_id === playlistId);
        if (playlist) {
          playlist.details = data;
        }
      },
      error: (err) => {
        console.error('Error fetching playlist details:', err);
      }
    });
  }
}
