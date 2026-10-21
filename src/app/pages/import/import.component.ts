import { errorText } from 'src/app/services/errors';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { EventsService } from 'src/app/services/events.service';
import { ImportState, PlaylistService } from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

/** Import playlists from a file: TuneMyMusic CSV (any streaming service), Exportify or the Spotify data export. */
@Component({
  selector: 'app-import',
  templateUrl: './import.component.html',
})
export class ImportComponent implements OnInit, OnDestroy {
  state: ImportState | null = null;
  folder = '';
  uploading = false;
  uploadError = '';
  private subscriptions: Subscription[] = [];

  constructor(private playlistService: PlaylistService, private statusService: StatusService, private events: EventsService) { }

  ngOnInit(): void {
    // While this page is open, the Downloads folder is watched for the exported file.
    this.playlistService.watchDownloads().subscribe(res => this.folder = res.folder);
    this.refresh();
    // The import's steps come from the backend; the page is read again once it is done, or when
    // the Downloads watch found a file.
    this.subscriptions.push(
      this.events.job('file_import').subscribe(job => {
        if (this.state) this.state = { ...this.state, job };
        if (!job.running) {
          this.refresh();
          this.statusService.refresh();  // playlists imported: the menu and the other pages change
        }
      }),
      this.events.on('watch').subscribe(() => this.refresh()),
    );
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach(s => s.unsubscribe());
  }

  refresh(): void {
    this.playlistService.getImport().subscribe(state => this.state = state);
  }

  /** The last import is shown only while its file is where the playlists come from. */
  inUse(file: string): boolean {
    const current = this.statusService.status?.import;
    return !!current?.from_file && current.file === file;
  }

  upload(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.uploading = true;
    this.uploadError = '';
    this.playlistService.uploadPlaylistsFile(file).subscribe({
      next: () => { this.uploading = false; this.refresh(); },
      error: (e) => { this.uploading = false; this.uploadError = e?.error?.error ? errorText(e.error.error, e.error.params) : 'This file could not be imported.'; },
    });
  }
}
