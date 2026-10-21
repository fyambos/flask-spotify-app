import { errorText } from 'src/app/services/errors';
import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { Subscription, merge } from 'rxjs';
import { map } from 'rxjs/operators';
import { EventsService } from 'src/app/services/events.service';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import {
  Devices, LibraryPlaylist, LibrarySong, LibraryState, LibraryTrack, PlaylistService, YouTubeMatch,
} from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

@Component({
  selector: 'app-library',
  templateUrl: './library.component.html',
})
export class LibraryComponent implements OnInit, OnDestroy {
  state: LibraryState | null = null;
  tab: 'failed' | 'removed' | 'ignored' = 'failed';
  shown = 10;
  importPath = '';
  importMode: 'copy' | 'move' = 'copy';
  unmatchedShown = 10;
  showUnmatched = false;
  appleMusicAuto = true;
  fromFile = false;
  showImport = false;
  layoutLabel = '';
  private jobs?: Subscription;


  constructor(private playlistService: PlaylistService, private dialog: MatDialog, private statusService: StatusService,
              private events: EventsService) { }

  /** Where the playlists are in Apple Music or iTunes: 'in your folders Eras, Genres and Moods'. */
  get whereInPlayer(): string {
    const folders = this.state?.player_folders || [];
    if (!folders.length) return '';
    return folders.length === 1 ? `, in a “${folders[0]}” folder` : `, in your folders ${this.joinNames(folders)}`;
  }

  /** What to check when syncing the iPhone: 'the folders Eras, Genres and Moods'. */
  get toCheck(): string {
    const folders = this.state?.player_folders || [];
    if (!folders.length) return 'your playlists';
    return folders.length === 1 ? `the folder ${folders[0]}` : `the folders ${this.joinNames(folders)}`;
  }

  private joinNames(names: string[]): string {
    return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  }

  /** Apple Music subscription and iPhone plugged in, for the iPhone card. */
  devices: Devices | null = null;

  loadDevices(): void {
    this.playlistService.getDevices().subscribe(devices => this.devices = devices);
  }

  openMusic(): void {
    this.playlistService.openMusic().subscribe();
  }

  openFinder(): void {
    this.playlistService.openFinder().subscribe(() => this.loadDevices());
  }

  ngOnInit(): void {
    this.refresh();
    this.loadDevices();
    // Each step of a job comes from the backend; the page is read again once a job is done.
    this.jobs = merge(
      merge(this.events.job('library'), this.events.job('file_import'), this.events.job('import')).pipe(map(job => ({ key: 'job', job }))),
      this.events.job('apple').pipe(map(job => ({ key: 'apple', job }))),
      this.events.job('chosen').pipe(map(job => ({ key: 'chosen', job }))),
    ).subscribe(({ key, job }) => {
      if (!this.state) return;
      if (key === 'job') this.state = { ...this.state, job };
      else if (key === 'apple') this.state = { ...this.state, apple_music: { ...this.state.apple_music, job } };
      else this.state = { ...this.state, chosen: job };
      this.trackDone();
      if (!job.running) this.refresh();
    });
    this.statusService.status$.subscribe(status => {
      this.fromFile = !!status?.import.from_file;
    });
    this.statusService.refresh();
    this.playlistService.getConfig().subscribe(config => {
      this.appleMusicAuto = config.apple_music_auto;
      const labels = { artist_album: 'Artist / Album', artist: 'Artist', one_folder: 'One folder', first_playlist: 'First playlist a song is in' };
      this.layoutLabel = labels[config.layout.preset];
    });
  }

  toggleAppleMusicAuto(): void {
    this.appleMusicAuto = !this.appleMusicAuto;
    this.playlistService.updateSettings({ apple_music_auto: this.appleMusicAuto }).subscribe();
  }

  ngOnDestroy(): void {
    this.jobs?.unsubscribe();
  }

  /** Sync was clicked: the dialog opens once the check that comes first is done. */
  private syncAsked = false;

  /** The downloaded playlists, and the one open below them. */
  playlists: LibraryPlaylist[] = [];
  open: { playlist: LibraryPlaylist; songs: LibrarySong[] | null } | null = null;

  /** Playlists shown in the grid: 12 at a time, the last place says how many more there are. */
  playlistLimit = 12;

  get shownPlaylists(): LibraryPlaylist[] {
    return this.playlists.length <= this.playlistLimit ? this.playlists : this.playlists.slice(0, this.playlistLimit - 1);
  }

  get morePlaylists(): number {
    return Math.min(12, this.playlists.length - this.shownPlaylists.length);
  }

  get covers(): string[] {
    return this.playlists.map(p => p.image_url).filter((url): url is string => !!url).slice(0, 12);
  }

  openPlaylist(playlist: LibraryPlaylist): void {
    if (this.open?.playlist.id === playlist.id) {
      this.open = null;
      return;
    }
    this.open = { playlist, songs: null };
    this.playlistService.getLibraryPlaylist(playlist.id).subscribe(res => {
      if (this.open?.playlist.id === playlist.id) this.open = { playlist, songs: res.songs };
    });
  }

  @HostListener('document:keydown.escape')
  closePlaylist(): void {
    this.open = null;
  }

  trackBySong(_: number, song: LibrarySong): string {
    return song.track_id;
  }

  refresh(): void {
    this.playlistService.getLibraryPlaylists().subscribe(playlists => {
      this.playlists = playlists;
      const open = this.open && playlists.find(p => p.id === this.open?.playlist.id);
      if (open) this.playlistService.getLibraryPlaylist(open.id).subscribe(res => this.open = { playlist: open, songs: res.songs });
    });
    this.playlistService.getLibrary().subscribe(state => {
      const checked = this.syncAsked && !state.job.running;
      this.state = state;
      if (checked) {
        this.syncAsked = false;
        if (!state.job.error) this.confirmSync();
      }
      this.trackDone();
      if (!state.chosen.running) {
        // Still in Not found: the chosen video did not download either (the line below says why).
        for (const id of Object.keys(this.chosen)) {
          this.chosen[id] = state.failed.some(t => t.track_id === id) ? (state.chosen.error ? errorText(state.chosen.error, state.chosen.error_params) : 'Not downloaded') : '';
        }
      }
      if (!this.importPath) {
        this.importPath = state.music_dir;
      }
    });
  }

  /** Checks first, so the dialog shows what the Sync will do now. */
  /** The last Sync click found nothing to do: said on the card, no dialog. */
  upToDate = false;

  sync(): void {
    this.syncAsked = true;
    this.upToDate = false;
    this.playlistService.checkLibrary().subscribe({
      next: () => this.refresh(),
      error: () => { this.syncAsked = false; this.refresh(); },
    });
  }

  private confirmSync(): void {
    const plan = this.state?.plan;
    const songs = (n: number) => `${n} ${n === 1 ? 'song' : 'songs'}`;
    const message = plan
      ? [
          // The corrected songs are downloads too: counted once, in Corrects.
          plan.to_download - plan.wrong_length ? `Downloads ${songs(plan.to_download - plan.wrong_length)}.` : '',
          plan.wrong_length ? `Corrects ${songs(plan.wrong_length)} (wrong length).` : '',
          plan.to_move ? `Moves ${songs(plan.to_move)}.` : '',
          plan.to_remove ? `Removes ${songs(plan.to_remove)} no longer in playlists.` : '',
          plan.duplicates ? `Cleans ${plan.duplicates} ${plan.duplicates === 1 ? 'duplicate' : 'duplicates'}.` : '',
          plan.moves_folder ? `Your files are moved to ${this.state?.music_dir}.` : '',
        ].filter(Boolean).join(' ')
      : '';
    if (!message) {
      this.upToDate = true;
      return;
    }
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

  /** A song not found: its YouTube Music results, to choose the right one by hand. */
  matching: { trackId: string; loading: boolean; results: YouTubeMatch[]; error: string } | null = null;
  matchUrl = '';
  chosen: { [trackId: string]: string } = {};

  openMatch(t: LibraryTrack): void {
    this.matching = { trackId: t.track_id, loading: true, results: [], error: '' };
    this.matchUrl = '';
    this.playlistService.getMatches(t.track_id).subscribe({
      next: res => { if (this.matching?.trackId === t.track_id) this.matching = { ...this.matching, loading: false, results: res.results }; },
      error: () => { if (this.matching) this.matching = { ...this.matching, loading: false }; },
    });
  }

  useMatch(t: LibraryTrack, url: string): void {
    if (!this.matching || !url.trim()) return;
    this.playlistService.chooseMatch(t.track_id, url.trim()).subscribe({
      next: () => { this.chosen[t.track_id] = 'Downloading'; this.matching = null; this.refresh(); },
      // The backend's own message is already shown at the top of the page.
      error: e => { if (this.matching && !e?.error?.error) this.matching = { ...this.matching, error: 'This link could not be used.' }; },
    });
  }

  trackByTrack(_: number, t: LibraryTrack): string {
    return t.track_id;
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
    return (this.tab === 'failed' ? this.state?.failed : this.tab === 'removed' ? this.state?.removed : this.state?.ignored) || [];
  }

  setIgnored(t: LibraryTrack, ignored: boolean): void {
    // Moved to the other tab at once; the page is read again once the backend has saved it.
    if (this.state) {
      const from = ignored ? this.state.failed : this.state.ignored;
      const to = ignored ? this.state.ignored : this.state.failed;
      this.state = {
        ...this.state,
        failed: ignored ? from.filter(x => x.track_id !== t.track_id) : [...to, { ...t, status: 'failed' }],
        ignored: ignored ? [...to, { ...t, status: 'ignored' }] : from.filter(x => x.track_id !== t.track_id),
      };
    }
    this.matching = null;
    this.playlistService.ignoreTrack(t.track_id, ignored).subscribe({ next: () => this.refresh(), error: () => this.refresh() });
  }
}
