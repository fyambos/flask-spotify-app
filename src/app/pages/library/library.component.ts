import { Component, OnDestroy, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import { LibraryState, PlaylistService } from 'src/app/services/playlist.service';

@Component({
  selector: 'app-library',
  templateUrl: './library.component.html',
})
export class LibraryComponent implements OnInit, OnDestroy {
  state: LibraryState | null = null;
  tab: 'failed' | 'removed' = 'failed';
  shown = 10;
  importPath = '';
  importMode: 'copy' | 'move' = 'copy';
  unmatchedShown = 10;
  showUnmatched = false;
  appleMusicAuto = true;
  private poll: any = null;

  constructor(private playlistService: PlaylistService, private dialog: MatDialog) { }

  ngOnInit(): void {
    this.refresh();
    this.playlistService.getConfig().subscribe(config => this.appleMusicAuto = config.apple_music_auto);
  }

  toggleAppleMusicAuto(): void {
    this.appleMusicAuto = !this.appleMusicAuto;
    this.playlistService.updateSettings({ apple_music_auto: this.appleMusicAuto }).subscribe();
  }

  ngOnDestroy(): void {
    clearInterval(this.poll);
  }

  refresh(): void {
    this.playlistService.getLibrary().subscribe(state => {
      this.state = state;
      if (!this.importPath) {
        this.importPath = state.music_dir;
      }
      const running = state.job.running || state.apple_music.job.running;
      if (running && !this.poll) {
        this.poll = setInterval(() => this.refresh(), 1500);
      } else if (!running && this.poll) {
        clearInterval(this.poll);
        this.poll = null;
      }
    });
  }

  check(): void {
    this.playlistService.checkLibrary().subscribe({ next: () => this.refresh(), error: () => this.refresh() });
  }

  sync(): void {
    const plan = this.state?.plan;
    const message = plan
      ? `${plan.to_download} songs to download, ${plan.to_move} to move, ${plan.to_remove} removed. Playlists are rewritten in the Playlists folder.`
      : 'Downloads new songs, moves changed ones and rewrites the playlists.';
    this.dialog.open(ConfirmDialogComponent, {
      data: { title: 'Sync library?', message, confirmLabel: 'Sync' },
    }).afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.playlistService.syncLibrary().subscribe({ next: () => this.refresh(), error: () => this.refresh() });
      }
    });
  }

  startImport(): void {
    this.playlistService.importLibrary(this.importPath, this.importMode).subscribe({
      next: () => this.refresh(),
      error: () => this.refresh(),
    });
  }

  updateAppleMusic(): void {
    this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Update Apple Music?',
        message: 'Adds the downloaded songs to Apple Music, removes the ones no longer in the library and writes your playlists in a "Music Sorter" folder.',
        confirmLabel: 'Update',
      },
    }).afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.playlistService.updateAppleMusic().subscribe({ next: () => this.refresh(), error: () => this.refresh() });
      }
    });
  }

  reveal(): void {
    this.playlistService.revealLibrary().subscribe();
  }

  get list() {
    return (this.tab === 'failed' ? this.state?.failed : this.state?.removed) || [];
  }
}
