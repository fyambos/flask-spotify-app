import { Component, OnInit } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { ConfirmDialogComponent } from 'src/app/components/confirm-dialog/confirm-dialog.component';
import { AppConfig, PlaylistService, SpotifyPlaylist } from 'src/app/services/playlist.service';

const INVISIBLE = /^[\s\u2800\u3164\u200b]+|[\s\u2800\u3164\u200b]+$/g;

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
  playlistNames: { [id: string]: string } = {};
  appleFolders: { id: string; name: string }[] = [];
  folderNames: string[] = [];
  rememberedArtists: { id: string; name: string; playlist: string }[] = [];

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
    this.appleFolders = Object.entries(this.playlistNames)
      .map(([id, name]) => ({ id, name: name.replace(INVISIBLE, '') }))
      .sort((a, b) => (config.apple_folders[a.id] || '').localeCompare(config.apple_folders[b.id] || '')
        || a.name.localeCompare(b.name));
    this.folderNames = [...new Set(Object.values(config.apple_folders || {}).filter(Boolean))].sort();
  }

  trackById(_: number, item: { id: string }): string {
    return item.id;
  }

  saveSettings(): void {
    if (!this.config) return;
    const { music_dir, audio_format, artist_history, multi_playlist, non_liked, removed, youtube_cookies } = this.config;
    this.playlistService.updateSettings({ music_dir, audio_format, artist_history, multi_playlist, non_liked, removed, youtube_cookies }).subscribe(() => {
      this.savedAt = Date.now();
      setTimeout(() => this.savedAt = 0, 2000);
    });
  }

  setFolder(id: string, folder: string): void {
    if (!this.config) return;
    this.config.apple_folders = { ...this.config.apple_folders, [id]: folder.trim() };
    this.folderNames = [...new Set(Object.values(this.config.apple_folders).filter(Boolean))].sort();
    this.playlistService.updateSettings({ apple_folders: this.config.apple_folders }).subscribe(() => {
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
