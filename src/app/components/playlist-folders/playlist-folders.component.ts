import { Component, Input, OnChanges, OnInit } from '@angular/core';
import { CdkDragDrop } from '@angular/cdk/drag-drop';
import { AppConfig, PlaylistService } from 'src/app/services/playlist.service';

const INVISIBLE = /^[\s⠀ㅤ​]+|[\s⠀ㅤ​]+$/g;
const FIRST_PAGE = 6;
const NEXT_PAGE = 10;

interface Folder {
  name: string;
  playlists: { id: string; name: string }[];
}

/** Playlists grouped by folder: drag between folders, rename, create, delete. */
@Component({
  selector: 'app-playlist-folders',
  templateUrl: './playlist-folders.component.html',
})
export class PlaylistFoldersComponent implements OnInit, OnChanges {
  @Input() names: { [spotifyPlaylistId: string]: string } = {};
  config: AppConfig | null = null;
  folders: Folder[] = [];
  shown: { [folder: string]: number } = {};
  renaming: string | null = null;
  renameDraft = '';
  creating = false;
  newName = '';
  search = '';

  constructor(private playlistService: PlaylistService) { }

  ngOnInit(): void {
    this.playlistService.getConfig().subscribe(config => {
      this.config = config;
      this.build();
    });
  }

  ngOnChanges(): void {
    this.build();
  }

  get defaultFolder(): string {
    return this.config?.default_folder || 'Music Sorter';
  }

  get dropIds(): string[] {
    return this.folders.map(f => 'folder-' + f.name);
  }

  private folderOf(id: string): string {
    return this.config?.playlist_folders[id] || this.defaultFolder;
  }

  /** Groups computed once per change, not at every change detection. */
  private build(): void {
    if (!this.config) return;
    const groups = new Map<string, Folder>();
    const order = [...(this.config.folders || []), this.defaultFolder];
    for (const name of order) {
      if (!groups.has(name)) groups.set(name, { name, playlists: [] });
    }
    for (const [id, raw] of Object.entries(this.names)) {
      const folder = this.folderOf(id);
      if (!groups.has(folder)) groups.set(folder, { name: folder, playlists: [] });
      groups.get(folder)!.playlists.push({ id, name: raw.replace(INVISIBLE, '') });
    }
    groups.forEach(g => g.playlists.sort((a, b) => a.name.localeCompare(b.name)));
    const known = new Set(order);
    const rest = [...groups.keys()].filter(n => !known.has(n)).sort((a, b) => a.localeCompare(b));
    this.folders = [...order.filter((n, i) => order.indexOf(n) === i && n !== this.defaultFolder), ...rest, this.defaultFolder]
      .map(n => groups.get(n)!);
  }

  visible(folder: Folder) {
    const term = this.search.trim().toLowerCase();
    if (term) {
      return folder.playlists.filter(p => p.name.toLowerCase().includes(term));
    }
    return folder.playlists.slice(0, this.shown[folder.name] || FIRST_PAGE);
  }

  hidden(folder: Folder): number {
    return this.search.trim() ? 0 : folder.playlists.length - (this.shown[folder.name] || FIRST_PAGE);
  }

  showMore(folder: Folder): void {
    this.shown[folder.name] = (this.shown[folder.name] || FIRST_PAGE) + NEXT_PAGE;
  }

  drop(event: CdkDragDrop<Folder>): void {
    if (!this.config || event.previousContainer === event.container) return;
    const playlist = event.item.data as { id: string };
    this.config.playlist_folders = { ...this.config.playlist_folders, [playlist.id]: event.container.data.name };
    this.save();
  }

  startRename(folder: Folder): void {
    this.renaming = folder.name;
    this.renameDraft = folder.name;
  }

  rename(folder: Folder): void {
    const name = this.renameDraft.trim();
    this.renaming = null;
    if (!this.config || !name || name === folder.name || this.folders.some(f => f.name === name)) return;
    const mapping = { ...this.config.playlist_folders };
    for (const p of folder.playlists) mapping[p.id] = name;
    this.config.playlist_folders = mapping;
    this.config.folders = this.folderNames().map(n => n === folder.name ? name : n);
    if (folder.name === this.defaultFolder) this.config.default_folder = name;
    this.save();
  }

  remove(folder: Folder): void {
    if (!this.config || folder.name === this.defaultFolder) return;
    const mapping = { ...this.config.playlist_folders };
    for (const p of folder.playlists) mapping[p.id] = this.defaultFolder;
    this.config.playlist_folders = mapping;
    this.config.folders = this.folderNames().filter(n => n !== folder.name);
    this.save();
  }

  create(): void {
    const name = this.newName.trim();
    this.creating = false;
    this.newName = '';
    if (!this.config || !name || this.folders.some(f => f.name === name)) return;
    this.config.folders = [name, ...this.folderNames()];
    this.save();
  }

  private folderNames(): string[] {
    return this.folders.map(f => f.name).filter(n => n !== this.defaultFolder);
  }

  private save(): void {
    if (!this.config) return;
    if (!this.config.folders?.length) this.config.folders = this.folderNames();
    this.build();
    const { playlist_folders, default_folder, folders } = this.config;
    this.playlistService.updateSettings({ playlist_folders, default_folder, folders }).subscribe();
  }

  trackByName(_: number, folder: Folder): string {
    return folder.name;
  }

  trackById(_: number, playlist: { id: string }): string {
    return playlist.id;
  }
}
