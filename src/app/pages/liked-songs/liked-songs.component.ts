import { Component, OnDestroy, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import {
  GenrePlaylist, LikeItem, LikesState, PlaylistService, SetupStatus, SpotifyPlaylist, SpotifySyncChange,
} from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

type Filter = 'review' | 'planned' | 'applied' | 'already';

@Component({
  selector: 'app-liked-songs',
  templateUrl: './liked-songs.component.html',
})
export class LikedSongsComponent implements OnInit, OnDestroy {
  state: LikesState | null = null;
  playlists: GenrePlaylist[] = [];
  fallbackId: string | null = null;
  filter: Filter = 'review';
  genreFilter = '';
  search = '';
  choices: { [trackId: string]: string } = {};
  remember: { [trackId: string]: boolean } = {};
  message = '';
  applying = false;
  tabs: { id: Filter; label: string }[] = [
    { id: 'review', label: 'To review' },
    { id: 'planned', label: 'Ready' },
    { id: 'applied', label: 'Added' },
    { id: 'already', label: 'Already sorted' },
  ];
  private poll: any = null;

  config_loaded = false;
  /** "Sort from" playlists. */
  sources: string[] = [];
  allPlaylists: SpotifyPlaylist[] = [];
  addingSource = '';
  status: SetupStatus | null = null;
  sync: { changes: SpotifySyncChange[]; loading: boolean; running: boolean } | null = null;
  private syncPoll: any = null;

  constructor(private playlistService: PlaylistService, private dialog: MatDialog, private statusService: StatusService) { }

  ngOnInit(): void {
    this.playlistService.getConfig().subscribe(config => {
      this.config_loaded = true;
      this.playlists = config.playlists;
      this.sources = config.sort_from;
      this.fallbackId = config.playlists.find(p => p.name === config.fallback_genre)?.id || null;
      this.refresh();
    });
    // Playlists of other users can't be sorted (Spotify doesn't let the app change them).
    this.playlistService.getPlaylists().subscribe(list => this.allPlaylists = list.filter(p => p.owned !== false));
    this.statusService.status$.subscribe(status => this.status = status);
    this.statusService.refresh();
  }

  get spotifyReady(): boolean {
    return this.statusService.spotifyReady;
  }

  get pending(): number {
    return this.status?.sort?.pending || 0;
  }

  sourceName(id: string): string {
    return this.allPlaylists.find(p => p.id === id)?.name || (id === 'liked' ? 'Liked Songs' : '—');
  }

  get sourceChoices(): SpotifyPlaylist[] {
    return this.allPlaylists.filter(p => !this.sources.includes(p.id));
  }

  setSources(sources: string[]): void {
    this.sources = sources;
    this.addingSource = '';
    this.playlistService.updateSettings({ sort_from: sources }).subscribe(() => this.startPreview());
  }

  addSource(id: string): void {
    if (id && !this.sources.includes(id)) this.setSources([...this.sources, id]);
  }

  removeSource(id: string): void {
    if (this.sources.length > 1) this.setSources(this.sources.filter(s => s !== id));
  }

  addingInto = '';
  creatingInto = false;
  newIntoName = '';

  /** Your playlists that can receive songs (not Liked Songs, not playlists of other users). */
  get intoChoices(): SpotifyPlaylist[] {
    const taken = new Set(this.playlists.map(p => p.playlist_id || 'app:' + p.id));
    return this.allPlaylists.filter(p => p.id !== 'liked' && !p.app_only && !taken.has(p.id));
  }

  addInto(id: string): void {
    if (id === '__new') {
      this.creatingInto = true;
      this.newIntoName = '';
      this.addingInto = '';
      return;
    }
    const playlist = this.allPlaylists.find(p => p.id === id);
    if (!playlist) return;
    this.playlistService.addGenrePlaylist({ name: playlist.name, playlist_id: playlist.id, genre_names: [] }).subscribe(entry => {
      this.playlists = [...this.playlists, entry];
      this.addingInto = '';
    });
  }

  /** A playlist that only exists in the app until the next Sync with Spotify. */
  createInto(): void {
    const name = this.newIntoName.trim();
    if (!name) return;
    this.playlistService.addGenrePlaylist({ name, playlist_id: null, genre_names: [] }).subscribe(entry => {
      this.playlists = [...this.playlists, entry];
      this.creatingInto = false;
    });
  }

  get onlyLiked(): boolean {
    return this.sources.length === 1 && this.sources[0] === 'liked';
  }

  openSync(): void {
    this.sync = { changes: [], loading: true, running: false };
    this.playlistService.getSpotifySync().subscribe({
      next: res => this.sync = { changes: res.changes, loading: false, running: res.job.running },
      error: () => this.sync = null,
    });
  }

  runSync(): void {
    if (!this.sync) return;
    this.sync.running = true;
    this.playlistService.runSpotifySync().subscribe(() => {
      clearInterval(this.syncPoll);
      this.syncPoll = setInterval(() => this.playlistService.getSpotifySync().subscribe(res => {
        if (res.job.running) return;
        clearInterval(this.syncPoll);
        this.sync = null;
        this.message = res.job.error || 'Synced with Spotify.';
        this.statusService.refresh();
      }), 1500);
    });
  }

  get syncTotals(): { add: number; removed: number; create: number } {
    const changes = this.sync?.changes || [];
    return {
      add: changes.reduce((n, c) => n + c.to_add.length, 0),
      removed: changes.reduce((n, c) => n + c.removed_on_spotify.length, 0),
      create: changes.filter(c => c.create).length,
    };
  }

  ngOnDestroy(): void {
    clearInterval(this.poll);
    clearInterval(this.syncPoll);
  }

  refresh(): void {
    this.playlistService.getLikesState().subscribe({
      next: (state) => {
        this.state = state;
        for (const item of state.preview?.items || []) {
          const preset = item.suggestion || this.fallbackId;
          if (item.status === 'review' && preset && !(item.track_id in this.choices)) {
            this.choices[item.track_id] = preset;
          }
        }
        if (state.job.running && !this.poll) {
          this.poll = setInterval(() => this.refresh(), 1500);
        } else if (!state.job.running && this.poll) {
          clearInterval(this.poll);
          this.poll = null;
        }
        if (!this.count('review') && this.filter === 'review' && this.count('planned')) {
          this.filter = 'planned';
        }
      },
      error: (error) => console.error('Error fetching likes preview:', error),
    });
  }

  startPreview(): void {
    this.message = '';
    this.playlistService.startLikesPreview().subscribe({
      next: () => this.refresh(),
      error: () => this.refresh(),
    });
  }

  get items(): LikeItem[] {
    return this.state?.preview?.items || [];
  }

  count(filter: Filter): number {
    return this.items.filter(item => this.matchesStatus(item, filter)).length;
  }

  get distribution(): { id: string; name: string; planned: number }[] {
    return this.playlists
      .map(p => ({
        id: p.id,
        name: p.name,
        planned: this.items.filter(i => (i.playlist === p.id || i.also?.includes(p.id)) && (i.status === 'auto' || i.status === 'manual')).length,
      }))
      .filter(d => d.planned)
      .sort((a, b) => b.planned - a.planned);
  }

  get visibleItems(): LikeItem[] {
    const search = this.search.trim().toLowerCase();
    return this.items.filter(item =>
      this.matchesStatus(item, this.filter)
      && (!this.genreFilter || item.playlist === this.genreFilter || !!item.also?.includes(this.genreFilter))
      && (!search || `${item.name} ${item.artists.join(' ')} ${item.album}`.toLowerCase().includes(search))
    ).slice(0, 300);
  }

  private matchesStatus(item: LikeItem, filter: Filter): boolean {
    if (filter === 'planned') {
      return item.status === 'auto' || item.status === 'manual';
    }
    return item.status === filter;
  }

  playlistName(id: string | null): string {
    return this.playlists.find(p => p.id === id)?.name || '—';
  }

  choose(item: LikeItem): void {
    const playlist = this.choices[item.track_id];
    if (!playlist) {
      return;
    }
    this.playlistService.resolveLike(item.track_id, playlist, !!this.remember[item.track_id]).subscribe({
      next: () => {
        delete this.choices[item.track_id];
        this.refresh();
      },
      error: (error) => console.error('Error saving choice:', error),
    });
  }

  apply(): void {
    const planned = this.count('planned');
    const from = this.onlyLiked ? 'your Liked Songs' : 'the playlists you sort from';
    this.dialog.open(ConfirmDialogComponent, {
      data: this.spotifyReady ? {
        title: `Add ${planned} songs to Spotify?`,
        message: `Songs will be added to their specific playlists. This will not modify ${from}.`,
        confirmLabel: 'Add to Spotify',
      } : {
        title: `Save ${planned} songs?`,
        message: `Songs are added to Spotify at the next Sync with Spotify. This will not modify ${from}.`,
        confirmLabel: 'Save',
      },
    }).afterClosed().subscribe((confirmed) => {
      if (!confirmed) {
        return;
      }
      this.applying = true;
      this.playlistService.applyLikes().subscribe({
        next: (result) => {
          this.applying = false;
          const total = Object.values(result.added).reduce((a, b) => a + b, 0);
          this.message = !total ? 'Nothing to add.'
            : result.spotify === 'written' ? `${total} songs added to your playlists.`
            : `${total} songs saved. Not synced with Spotify.`;
          this.refresh();
          this.statusService.refresh();
        },
        error: (error) => {
          this.applying = false;
          this.message = 'Something went wrong while saving the songs.';
          console.error(error);
        },
      });
    });
  }
}
