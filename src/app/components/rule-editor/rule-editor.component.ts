import { Component, EventEmitter, HostListener, Input, OnChanges, Output } from '@angular/core';
import { GenrePlaylist } from 'src/app/services/playlist.service';

/** Side panel to edit the rules of one genre playlist. */
@Component({
  selector: 'app-rule-editor',
  templateUrl: './rule-editor.component.html',
})
export class RuleEditorComponent implements OnChanges {
  @Input() playlist: GenrePlaylist | null = null;
  @Output() save = new EventEmitter<GenrePlaylist>();
  @Output() close = new EventEmitter<void>();
  draft: GenrePlaylist | null = null;

  ngOnChanges(): void {
    this.draft = this.playlist ? JSON.parse(JSON.stringify(this.playlist)) : null;
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.draft) {
      this.close.emit();
    }
  }

  submit(): void {
    if (this.draft) {
      this.save.emit({ ...this.draft, name: this.draft.name.trim() || this.playlist!.name });
    }
  }
}
