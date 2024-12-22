import { Component, Inject } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { FormBuilder, FormGroup } from '@angular/forms';

@Component({
  selector: 'app-playlist-edit-dialog',
  templateUrl: './playlist-edit-dialog.component.html',
})
export class PlaylistEditDialogComponent {
  genreForm: FormGroup;

  constructor(
    public dialogRef: MatDialogRef<PlaylistEditDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: any,
    private fb: FormBuilder
  ) {
    // Initialize form with the current genres
    this.genreForm = this.fb.group({
      genres: [data.genre_names.join(', ')],
    });
  }

  onClose(): void {
    this.dialogRef.close();
  }

  onSubmit(): void {
    const updatedGenres = this.genreForm.value.genres.split(',').map((genre: string) => genre.trim());
    this.dialogRef.close(updatedGenres);
  }
}
