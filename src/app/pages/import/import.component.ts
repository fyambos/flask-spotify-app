import { Component, OnDestroy, OnInit } from '@angular/core';
import { ImportState, PlaylistService } from 'src/app/services/playlist.service';
import { StatusService } from 'src/app/services/status.service';

/** Import playlists from a file: TuneMyMusic CSV (any streaming service) or the Spotify data export. */
@Component({
  selector: 'app-import',
  templateUrl: './import.component.html',
})
export class ImportComponent implements OnInit, OnDestroy {
  state: ImportState | null = null;
  folder = '';
  uploading = false;
  uploadError = '';
  private poll: any = null;

  constructor(private playlistService: PlaylistService, private statusService: StatusService) { }

  ngOnInit(): void {
    // While this page is open, the Downloads folder is watched for the exported file.
    this.playlistService.watchDownloads().subscribe(res => this.folder = res.folder);
    this.refresh();
    this.poll = setInterval(() => this.refresh(), 2000);
  }

  ngOnDestroy(): void {
    clearInterval(this.poll);
  }

  refresh(): void {
    const wasRunning = this.state?.job.running;
    this.playlistService.getImport().subscribe(state => {
      this.state = state;
      if (wasRunning && !state.job.running) this.statusService.refresh();
    });
  }

  upload(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    this.uploading = true;
    this.uploadError = '';
    this.playlistService.uploadPlaylistsFile(file).subscribe({
      next: () => { this.uploading = false; this.refresh(); },
      error: (e) => { this.uploading = false; this.uploadError = e?.error?.error || 'This file could not be imported.'; },
    });
  }
}
