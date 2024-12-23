import { Component, OnInit } from '@angular/core';
import { Firestore } from '@angular/fire/firestore';
import { collection, getDocs, updateDoc, doc, deleteDoc } from 'firebase/firestore';
import { PlaylistService } from 'src/app/services/playlist.service';
import { PlaylistEditDialogComponent } from '../playlist-edit-dialog/playlist-edit-dialog.component';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from '../confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-playlist-display',
  templateUrl: './playlist-display.component.html',
})
export class PlaylistDisplayComponent implements OnInit {
  playlists: any[] = [];

  constructor(
    private firestore: Firestore,
    private playlistService: PlaylistService,
    private dialog: MatDialog
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
        playlist['id'] = doc.id;
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

  openEditDialog(playlist: any): void {
    const dialogRef = this.dialog.open(PlaylistEditDialogComponent, {
      data: { genre_names: playlist.genre_names },
    });

    dialogRef.afterClosed().subscribe((updatedGenres) => {
      if (updatedGenres) {
        this.updateGenresInFirestore(playlist.id, updatedGenres);
      }
    });
  }

  async updateGenresInFirestore(playlistId: string, updatedGenres: string[]): Promise<void> {
    try {
      const playlistDoc = doc(this.firestore, 'playlists', playlistId);
      await updateDoc(playlistDoc, {
        genre_names: updatedGenres,
      });
      const playlist = this.playlists.find(p => p.id === playlistId);
      if (playlist) {
        playlist.genre_names = updatedGenres;
      }
      console.log('Genres updated successfully!');
    } catch (error) {
      console.error('Error updating genres in Firestore:', error);
    }
  }

  openDeleteDialog(playlist: any): void {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Confirm',
        message: 'Are you sure you want to delete this playlist?',
      },
    });

    dialogRef.afterClosed().subscribe((confirmed) => {
      if (confirmed) {
        this.deletePlaylist(playlist.id);
      }
    });
  }

  async deletePlaylist(playlistId: string): Promise<void> {
    try {
      const playlistDoc = doc(this.firestore, 'playlists', playlistId);
      await deleteDoc(playlistDoc);
      this.playlists = this.playlists.filter((p) => p.id !== playlistId);
      console.log('Playlist deleted successfully!');
    } catch (error) {
      console.error('Error deleting playlist:', error);
    }
  }

}
