import { Component, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import { AppConfig, PlaylistService, SpotifyPlaylist } from 'src/app/services/playlist.service';

@Component({
  selector: 'app-settings',
  templateUrl: './settings.component.html',
})
export class SettingsComponent implements OnInit {
  config: AppConfig | null = null;
  playlists: SpotifyPlaylist[] = [];
  savedAt = 0;
  sortSource = '';
  sorting = false;
  sortMessage = '';
  rememberedArtists: { id: string; name: string; playlist: string }[] = [];
  playlistNames: { [id: string]: string } = {};
  downloadChoices: { id: string; name: string; genre: boolean }[] = [];
  downloadSearch = '';
  downloadShown = 8;
  downloadModes: { id: 'all' | 'liked' | 'selected'; label: string; hint: string }[] = [
    { id: 'all', label: 'All playlists', hint: 'Every song of your playlists.' },
    { id: 'liked', label: 'Liked Songs only', hint: 'Only the songs in your Liked Songs.' },
    { id: 'selected', label: 'Choose playlists', hint: 'Your genre playlists and the playlists you check below.' },
  ];

  constructor(private playlistService: PlaylistService, private dialog: MatDialog) { }

  ngOnInit(): void {
    this.playlistService.getConfig().subscribe(config => {
      this.config = config;
      this.computeLists();
    });
    this.playlistService.getPlaylists().subscribe(playlists => this.playlists = playlists.filter(p => p.owned));
    this.playlistService.getLibrary().subscribe(state => {
      this.playlistNames = state.playlist_names;
      this.computeLists();
    });

  }

  /** Lists shown on the page, computed once (not at every change detection). */
  private computeLists(): void {
    if (!this.config) return;
    const config = this.config;
    this.rememberedArtists = Object.entries(config.artist_rules).map(([id, rule]) => ({
      id, name: rule.name, playlist: config.playlists.find(p => p.id === rule.playlist)?.name || '—',
    })).sort((a, b) => a.name.localeCompare(b.name));
    const genreIds = new Set(config.playlists.map(p => p.playlist_id));
    this.downloadChoices = Object.entries(this.playlistNames)
      .filter(([id]) => id !== 'liked')
      .map(([id, name]) => ({ id, name: name.replace(/^[\s\u2800\u3164\u200b]+|[\s\u2800\u3164\u200b]+$/g, ''), genre: genreIds.has(id) }))
      .sort((a, b) => Number(b.genre) - Number(a.genre) || a.name.localeCompare(b.name));
  }

  get modeHint(): string {
    return this.downloadModes.find(m => m.id === this.config?.download.mode)?.hint || '';
  }

  get visibleChoices() {
    const term = this.downloadSearch.trim().toLowerCase();
    const list = term ? this.downloadChoices.filter(c => c.name.toLowerCase().includes(term)) : this.downloadChoices;
    return term ? list : list.slice(0, this.downloadShown);
  }

  setMode(mode: 'all' | 'liked' | 'selected'): void {
    if (!this.config) return;
    this.config.download = { ...this.config.download, mode };
    this.saveSettings();
  }

  isChosen(id: string): boolean {
    return !!this.config?.download.playlists.includes(id);
  }

  toggleChoice(id: string): void {
    if (!this.config) return;
    const chosen = new Set(this.config.download.playlists);
    chosen.has(id) ? chosen.delete(id) : chosen.add(id);
    this.config.download = { ...this.config.download, playlists: [...chosen] };
    this.saveSettings();
  }

  trackById(_: number, item: { id: string }): string {
    return item.id;
  }

  saveSettings(): void {
    if (!this.config) return;
    const { music_dir, audio_format, artist_history, multi_playlist, non_liked, download, removed, youtube_cookies } = this.config;
    this.playlistService.updateSettings({ music_dir, audio_format, artist_history, multi_playlist, non_liked, download, removed, youtube_cookies }).subscribe(() => {
      this.savedAt = Date.now();
      setTimeout(() => this.savedAt = 0, 2000);
    });
  }

  revealConfig(): void {
    this.playlistService.revealConfig().subscribe();
  }

  forget(artistId: string): void {
    this.playlistService.deleteArtistRule(artistId).subscribe(() => {
      delete this.config!.artist_rules[artistId];
      this.computeLists();
    });
  }

  sortPlaylist(): void {
    const source = this.playlists.find(p => p.id === this.sortSource);
    if (!source) return;
    this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: `Sort ${source.name.trim()}?`,
        message: 'Songs are removed from the old playlist. Unrecognized songs are skipped.',
        confirmLabel: 'Sort playlist',
      },
    }).afterClosed().subscribe(confirmed => {
      if (!confirmed) return;
      this.sorting = true;
      this.sortMessage = '';
      this.playlistService.sortPlaylist(source.id).subscribe({
        next: (res) => { this.sorting = false; this.sortMessage = res.message; },
        error: () => { this.sorting = false; this.sortMessage = 'Something went wrong while sorting.'; },
      });
    });
  }
}
