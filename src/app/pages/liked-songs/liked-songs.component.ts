import { Component, OnDestroy, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import { GenrePlaylist, LikeItem, LikesState, PlaylistService } from 'src/app/services/playlist.service';

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

  constructor(private playlistService: PlaylistService, private dialog: MatDialog) { }

  ngOnInit(): void {
    this.playlistService.getConfig().subscribe(config => {
      this.playlists = config.playlists;
      this.fallbackId = config.playlists.find(p => p.name === config.fallback_genre)?.id || null;
      this.refresh();
    });
  }

  ngOnDestroy(): void {
    clearInterval(this.poll);
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
    this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: `Add ${planned} songs to Spotify?`,
        message: 'Songs will be added to their specific genre playlists. This will not modify your Liked Songs.',
        confirmLabel: 'Add to Spotify',
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
          this.message = total ? `${total} songs added to your genre playlists.` : 'Nothing to add.';
          this.refresh();
        },
        error: (error) => {
          this.applying = false;
          this.message = 'Something went wrong while adding songs to Spotify.';
          console.error(error);
        },
      });
    });
  }
}
