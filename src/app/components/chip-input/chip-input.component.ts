import { Component, EventEmitter, Input, Output } from '@angular/core';

/** A list of keywords shown as removable chips, with an input to add more (Enter or comma). */
@Component({
  selector: 'app-chip-input',
  templateUrl: './chip-input.component.html',
})
export class ChipInputComponent {
  @Input() values: string[] = [];
  @Input() placeholder = 'Add…';
  @Output() valuesChange = new EventEmitter<string[]>();
  draft = '';

  add(): void {
    const added = this.draft.split(',').map(v => v.trim().toLowerCase()).filter(v => v && !this.values.includes(v));
    this.draft = '';
    if (added.length) {
      this.valuesChange.emit([...this.values, ...added]);
    }
  }

  remove(value: string): void {
    this.valuesChange.emit(this.values.filter(v => v !== value));
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      this.add();
    } else if (event.key === 'Backspace' && !this.draft && this.values.length) {
      this.remove(this.values[this.values.length - 1]);
    }
  }
}
