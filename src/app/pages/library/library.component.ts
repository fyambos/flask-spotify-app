import { Component, OnDestroy, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import { LibraryState, PlaylistService } from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

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
  fromFile = false;
  showImport = false;
  layoutLabel = '';
  private poll: any = null;


  constructor(private playlistService: PlaylistService, private dialog: MatDialog, private statusService: StatusService) { }

  ngOnInit(): void {
    this.refresh();
    this.statusService.status$.subscribe(status => {
      this.fromFile = status?.import.source === 'tunemymusic' || status?.import.source === 'spotify-export';
    });
    this.statusService.refresh();
    this.playlistService.getConfig().subscribe(config => {
      this.appleMusicAuto = config.apple_music_auto;
      const labels = { artist_album: 'Artist / Album', artist: 'Artist', one_folder: 'One folder', first_playlist: 'First playlist' };
      this.layoutLabel = labels[config.layout.preset];
    });
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
      this.trackDone();
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
    const moves = plan?.moves_folder ? ` Your files are moved to ${this.state?.music_dir}.` : '';
    const wrong = plan?.wrong_length ? ` ${plan.wrong_length} of them replace files of another version (wrong length).` : '';
    const message = plan
      ? `${plan.to_download} songs to download, ${plan.to_move} to move, ${plan.to_remove} removed.${wrong} Playlists are rewritten in the Playlists folder.${moves}`
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
    const app = this.state?.apple_music?.app || 'Apple Music';
    this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: `Update ${app}?`,
        message: `Adds the downloaded songs to ${app}, removes the ones no longer in the library and writes your playlists in a "Music Sorter" folder.`,
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

  /** The song that was downloaded last (it left the songs in progress). */
  currentSong = '';
  private previous: string[] = [];

  private trackDone(): void {
    const job = this.state?.job;
    if (!job?.running || job.step !== 'Downloading songs') {
      this.previous = [];
      this.currentSong = '';
      return;
    }
    const current = job.current || [];
    const done = this.previous.filter(name => !current.includes(name));
    if (done.length) this.currentSong = done[done.length - 1];
    this.previous = current;
  }

  get list() {
    return (this.tab === 'failed' ? this.state?.failed : this.state?.removed) || [];
  }
}
