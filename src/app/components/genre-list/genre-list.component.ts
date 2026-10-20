import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';
import { GenrePlaylist, MisplacedSong, PlaylistStats, RuleSuggestion, SpotifyPlaylist } from 'src/app/services/playlist.service';
import { suggestionKey, suggestionLabel } from 'src/app/services/rule-suggestions';

const FIRST_PAGE = 5;
const NEXT_PAGE = 10;

/** Genre playlists in priority order: drag to reorder, edit or remove. */
@Component({
  selector: 'app-genre-list',
  templateUrl: './genre-list.component.html',
})
export class GenreListComponent {
  @Input() playlists: GenrePlaylist[] = [];
  @Input() stats: { [id: string]: PlaylistStats } | null = null;
  @Input() spotify: { [playlistId: string]: SpotifyPlaylist } = {};
  @Input() removable = true;
  @Input() applied = new Set<string>();
  @Output() suggest = new EventEmitter<RuleSuggestion>();
  open = new Set<string>();
  shown: { [id: string]: number } = {};
  @Output() reordered = new EventEmitter<GenrePlaylist[]>();
  @Output() edit = new EventEmitter<GenrePlaylist>();
  @Output() remove = new EventEmitter<GenrePlaylist>();

  drop(event: CdkDragDrop<GenrePlaylist[]>): void {
    if (event.previousIndex === event.currentIndex) {
      return;
    }
    const list = [...this.playlists];
    moveItemInArray(list, event.previousIndex, event.currentIndex);
    this.reordered.emit(list);
  }

  toggle(id: string): void {
    if (this.open.has(id)) {
      this.open.delete(id);
    } else {
      this.open.add(id);
      this.shown[id] = FIRST_PAGE;
    }
  }

  visibleSongs(id: string): MisplacedSong[] {
    return (this.stats?.[id]?.misplaced || []).slice(0, this.shown[id] || FIRST_PAGE);
  }

  remaining(id: string): number {
    return (this.stats?.[id]?.misplaced?.length || 0) - (this.shown[id] || FIRST_PAGE);
  }

  showMore(id: string): void {
    this.shown[id] = (this.shown[id] || FIRST_PAGE) + NEXT_PAGE;
  }

  label(s: RuleSuggestion): string {
    return suggestionLabel(s, this.playlists);
  }

  isApplied(s: RuleSuggestion): boolean {
    return this.applied.has(suggestionKey(s));
  }

  playlistName(id: string | null): string {
    return this.playlists.find(p => p.id === id)?.name || '—';
  }

  ruleCount(p: GenrePlaylist): number {
    return p.genre_names.length + p.album_keywords.length + p.title_keywords.length;
  }

  accuracyClass(value: number): string {
    if (value >= 0.85) return 'bg-brand-50 text-brand-700 ring-brand-600/20';
    if (value >= 0.65) return 'bg-amber-50 text-amber-700 ring-amber-600/20';
    return 'bg-rose-50 text-rose-700 ring-rose-600/20';
  }

  elsewhere(stats: PlaylistStats): string {
    return Object.entries(stats.goes_elsewhere).map(([name, n]) => `${n} → ${name}`).join(', ');
  }
}
