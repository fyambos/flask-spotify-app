import { Component } from '@angular/core';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
})
export class HomeComponent {
  // Text from the user's own description of the app.
  features = [
    { path: '/library', icon: 'download', title: 'Download from Spotify as MP3', text: 'Create MP3 playlists that follow your Spotify playlists.' },
    { path: '/library', icon: 'hard-drive', title: 'Send your MP3 playlists to your computers or phones', text: 'Listen without a music streaming platform.' },
    { path: '/likes', icon: 'heart', title: 'Organize Liked Songs', text: 'Automatically organize liked songs into Spotify playlists of your choices.' },
    { path: '/stats', icon: 'bar-chart-3', title: 'Spotify stats', text: 'See your Spotify stats.' },
  ];
}
