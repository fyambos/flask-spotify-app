import { Component, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { PlaylistService, SetupStatus } from './services/playlist.service';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  status: SetupStatus | null = null;
  backendDown = false;
  inSetup = false;

  nav = [
    { path: '/likes', label: 'Liked Songs', icon: 'heart' },
    { path: '/genres', label: 'Genres', icon: 'list-music' },
    { path: '/library', label: 'Library', icon: 'hard-drive' },
    { path: '/stats', label: 'Stats', icon: 'bar-chart-3' },
    { path: '/settings', label: 'Settings', icon: 'settings' },
  ];

  constructor(private playlistService: PlaylistService, private router: Router) { }

  ngOnInit(): void {
    this.router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe((e) => {
      this.inSetup = (e as NavigationEnd).urlAfterRedirects.startsWith('/setup');
    });
    this.playlistService.getSetupStatus().subscribe({
      next: (status) => {
        this.status = status;
        // First launch: nothing configured yet, start with the setup assistant.
        if (!status.configured || !status.spotify.connected) {
          this.router.navigate(['/setup']);
        }
      },
      error: () => this.backendDown = true,
    });
  }
}
