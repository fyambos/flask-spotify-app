import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';
import { AppConfig, LayoutExample, LayoutPreset, PlaylistService, SpotifyPlaylist } from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

@Component({
  selector: 'app-settings',
  templateUrl: './settings.component.html',
})
export class SettingsComponent implements OnInit, OnDestroy {
  config: AppConfig | null = null;
  playlists: SpotifyPlaylist[] = [];
  savedAt = 0;
  rememberedArtists: { id: string; name: string; playlist: string }[] = [];
  /** Names of the downloaded playlists, for the folders. */
  playlistNames: { [id: string]: string } = {};
  downloadChoices: SpotifyPlaylist[] = [];
  /** Downloaded playlists in "First playlist" order. */
  layoutOrder: SpotifyPlaylist[] = [];
  downloadSearch = '';
  downloadShown = 8;
  example: LayoutExample | null = null;
  fromFile = false;
  downloadModes: { id: 'all' | 'selected'; label: string; hint: string }[] = [
    { id: 'all', label: 'All my playlists', hint: 'Your playlists and Liked Songs.' },
    { id: 'selected', label: 'Choose playlists', hint: 'The playlists you check below.' },
  ];
  layouts: { id: LayoutPreset; label: string }[] = [
    { id: 'artist_album', label: 'Artist / Album' },
    { id: 'artist', label: 'Artist' },
    { id: 'one_folder', label: 'One folder' },
    { id: 'first_playlist', label: 'First playlist' },
  ];
  private statusSub: any;

  constructor(private playlistService: PlaylistService, private statusService: StatusService, private route: ActivatedRoute) { }

  ngOnInit(): void {
    this.playlistService.getConfig().subscribe(config => {
      this.config = config;
      this.computeLists();
      // Links like /settings#downloads open the page at that section.
      const fragment = this.route.snapshot.fragment;
      if (fragment) setTimeout(() => document.getElementById(fragment)?.scrollIntoView({ block: 'start' }));
    });
    this.playlistService.getPlaylists().subscribe(playlists => {
      this.playlists = playlists;
      this.computeLists();
    });
    this.statusSub = this.statusService.status$.subscribe(status => {
      this.fromFile = status?.import.source === 'tunemymusic' || status?.import.source === 'spotify-export';
    });
    this.statusService.refresh();
    this.loadExample();
  }

  ngOnDestroy(): void {
    this.statusSub?.unsubscribe();
    // The playlists shown here are no longer "New".
    if (this.playlists.length) {
      this.playlistService.markPlaylistsSeen(this.playlists.map(p => p.id)).subscribe();
    }
  }

  /** Lists shown on the page, computed once (not at every change detection). */
  private computeLists(): void {
    if (!this.config) return;
    const config = this.config;
    this.rememberedArtists = Object.entries(config.artist_rules).map(([id, rule]) => ({
      id, name: rule.name, playlist: config.playlists.find(p => p.id === rule.playlist)?.name || '—',
    })).sort((a, b) => a.name.localeCompare(b.name));
    // New playlists first, then yours, then the ones of other users.
    this.downloadChoices = [...this.playlists].sort((a, b) =>
      Number(b.new) - Number(a.new) || Number(a.owned === false) - Number(b.owned === false)
      || Number(b.id === 'liked') - Number(a.id === 'liked') || a.name.localeCompare(b.name));
    const downloaded = this.downloadedPlaylists();
    this.playlistNames = Object.fromEntries(downloaded.map(p => [p.id, p.name]));
    const order = config.layout.order;
    this.layoutOrder = [...downloaded].sort((a, b) => {
      const ia = order.indexOf(a.id), ib = order.indexOf(b.id);
      return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib);
    });
  }

  private downloadedPlaylists(): SpotifyPlaylist[] {
    const download = this.config!.download;
    return this.playlists.filter(p => download.mode === 'all' ? p.owned !== false : download.playlists.includes(p.id));
  }

  private loadExample(): void {
    this.playlistService.getLayoutExample().subscribe(example => this.example = example);
  }

  get modeHint(): string {
    return this.downloadModes.find(m => m.id === this.config?.download.mode)?.hint || '';
  }

  get visibleChoices(): SpotifyPlaylist[] {
    const term = this.downloadSearch.trim().toLowerCase();
    const list = term ? this.downloadChoices.filter(c => c.name.toLowerCase().includes(term)) : this.downloadChoices;
    return term ? list : list.slice(0, this.downloadShown);
  }

  get newCount(): number {
    return this.playlists.filter(p => p.new).length;
  }

  /** Where a file goes with a layout, from a real song of your playlists. */
  examplePath(preset: LayoutPreset): string {
    const e = this.example;
    if (!e || !this.config) return '';
    const sep = e.separator;
    const first = this.layoutOrder[0]?.name || e.first_playlist || 'Liked Songs';
    const parts = {
      artist_album: [e.album_artist, e.album],
      artist: [e.album_artist],
      one_folder: [],
      first_playlist: [first],
    }[preset];
    return [e.music_dir, this.config.layout.folder || 'Music Sorter', ...parts, e.file].join(sep);
  }

  setMode(mode: 'all' | 'selected'): void {
    if (!this.config) return;
    this.config.download = { ...this.config.download, mode };
    this.saveSettings();
    this.computeLists();
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
    this.computeLists();
  }

  setLayout(preset: LayoutPreset): void {
    if (!this.config) return;
    this.config.layout = { ...this.config.layout, preset };
    this.saveSettings();
  }

  dropOrder(event: CdkDragDrop<SpotifyPlaylist[]>): void {
    if (!this.config) return;
    moveItemInArray(this.layoutOrder, event.previousIndex, event.currentIndex);
    this.config.layout = { ...this.config.layout, order: this.layoutOrder.map(p => p.id) };
    this.saveSettings();
  }

  trackById(_: number, item: { id: string }): string {
    return item.id;
  }

  saveSettings(): void {
    if (!this.config) return;
    const { music_dir, audio_format, artist_history, multi_playlist, download, layout, removed, youtube_cookies, import_reminder } = this.config;
    this.playlistService.updateSettings({ music_dir, audio_format, artist_history, multi_playlist, download, layout, removed, youtube_cookies, import_reminder }).subscribe(() => {
      this.savedAt = Date.now();
      setTimeout(() => this.savedAt = 0, 2000);
      this.loadExample();
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
}
