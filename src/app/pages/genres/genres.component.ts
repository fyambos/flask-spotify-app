import { Component, OnDestroy, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import { AccuracyState, GenrePlaylist, PlaylistService, PlaylistStats, RuleSuggestion, SpotifyPlaylist } from 'src/app/services/playlist.service';
import { applySuggestion, suggestionKey } from 'src/app/services/rule-suggestions';

@Component({
  selector: 'app-genres',
  templateUrl: './genres.component.html',
})
export class GenresComponent implements OnInit, OnDestroy {
  playlists: GenrePlaylist[] = [];
  spotify: { [id: string]: SpotifyPlaylist } = {};
  accuracy: AccuracyState | null = null;
  editing: GenrePlaylist | null = null;
  loading = true;
  applied = new Set<string>();
  private poll: any = null;

  constructor(private playlistService: PlaylistService, private dialog: MatDialog) { }

  ngOnInit(): void {
    this.playlistService.getConfig().subscribe(config => {
      this.playlists = config.playlists;
      this.loading = false;
    });
    this.playlistService.getPlaylists().subscribe(playlists => {
      this.spotify = Object.fromEntries(playlists.map(p => [p.id, p]));
    });
    this.refreshAccuracy();
  }

  ngOnDestroy(): void {
    clearInterval(this.poll);
  }

  /** Results of the last accuracy check (they may be from older rules, see accuracyOutdated). */
  get stats(): { [id: string]: PlaylistStats } | null {
    return this.accuracy?.result?.stats || null;
  }

  get accuracyOutdated(): boolean {
    const a = this.accuracy;
    return !!a?.result && a.result.rules_hash !== a.rules_hash;
  }

  applyRuleSuggestion(s: RuleSuggestion): void {
    this.applied = new Set(this.applied).add(suggestionKey(s));
    if (s.type === 'artist') {
      this.playlistService.addArtistRule(s.value, s.artist || '', s.playlist).subscribe();
      return;
    }
    if (s.type === 'multi_playlist') {
      this.playlistService.updateSettings({ multi_playlist: true }).subscribe(() => this.refreshAccuracy());
      return;
    }
    const updated = applySuggestion(this.playlists, s);
    if (s.type === 'move_above') {
      this.reorder(updated);
      return;
    }
    const changed = updated.find(p => p.id === s.playlist)!;
    this.save(changed);
  }

  refreshAccuracy(): void {
    this.playlistService.getAccuracy().subscribe(state => {
      this.accuracy = state;
      if (state.job.running && !this.poll) {
        this.poll = setInterval(() => this.refreshAccuracy(), 1500);
      } else if (!state.job.running && this.poll) {
        clearInterval(this.poll);
        this.poll = null;
      }
    });
  }

  checkAccuracy(): void {
    this.playlistService.startAccuracyCheck().subscribe({
      next: () => this.refreshAccuracy(),
      error: () => this.refreshAccuracy(),
    });
  }

  reorder(list: GenrePlaylist[]): void {
    this.playlists = list;
    this.playlistService.reorderGenrePlaylists(list.map(p => p.id)).subscribe(() => this.refreshAccuracy());
  }

  save(updated: GenrePlaylist): void {
    this.editing = null;
    this.playlistService.updateGenrePlaylist(updated.id, updated).subscribe(saved => {
      this.playlists = this.playlists.map(p => p.id === saved.id ? saved : p);
      this.refreshAccuracy();
    });
  }

  remove(playlist: GenrePlaylist): void {
    this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: `Remove ${playlist.name}?`,
        message: 'Liked songs will no longer be filed into this playlist. The Spotify playlist itself is not deleted.',
        confirmLabel: 'Remove',
        danger: true,
      },
    }).afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.playlistService.deleteGenrePlaylist(playlist.id).subscribe(() => {
          this.playlists = this.playlists.filter(p => p.id !== playlist.id);
          this.refreshAccuracy();
        });
      }
    });
  }
}
