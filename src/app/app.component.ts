import { errorText } from './services/errors';
import { Component, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { PlaylistService, SetupStatus } from './services/playlist.service';
import { StatusService } from './services/status.service';
import { NoticeService } from './services/notice.service';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  status: SetupStatus | null = null;
  backendDown = false;
  inSetup = false;
  nav: { path: string; label: string; icon: string }[] = [];

  constructor(private statusService: StatusService, private playlistService: PlaylistService, private router: Router,
              public notice: NoticeService) { }

  dismissReminder(): void {
    this.playlistService.updateSettings({ import_reminder: false }).subscribe(() => this.statusService.refresh());
  }

  ngOnInit(): void {
    this.router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe((e) => {
      this.inSetup = (e as NavigationEnd).urlAfterRedirects.startsWith('/setup');
    });
    this.buildNav();
    let first = true;
    this.statusService.backendDown$.subscribe(down => {
      this.backendDown = down;
      if (down && first) this.router.navigate(['/setup']);
    });
    this.statusService.status$.subscribe(status => {
      if (!status) return;
      this.status = status;
      this.buildNav();
      if (first) {
        first = false;
        if (status.spotify.limit) this.notice.show(errorText('spotify_limit', { until: status.spotify.limit }));
        // First launch: no playlists yet, start with the Welcome screen.
        if (!status.playlists && !status.spotify.connected) this.router.navigate(['/setup']);
      }
    });
    this.statusService.refresh();
  }

  private buildNav(): void {
    this.nav = [
      { path: '/home', label: 'Home', icon: 'home' },
      { path: '/library', label: 'Library', icon: 'hard-drive' },
      { path: '/sort', label: 'Sort Playlists', icon: 'list-music' },
      // Stats come from the playlists, whatever their source.
      ...(this.status?.playlists || this.status?.spotify?.connected ? [{ path: '/stats', label: 'Stats', icon: 'bar-chart-3' }] : []),
      { path: '/settings', label: 'Settings', icon: 'settings' },
    ];
  }
}
