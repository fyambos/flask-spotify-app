import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { ReactiveFormsModule } from '@angular/forms';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { SortPlaylistComponent } from './components/sort-playlist/sort-playlist.component';
import { HttpClientModule } from '@angular/common/http';
import { SetPlaylistsComponent } from './components/set-playlists/set-playlists.component';
import { provideFirebaseApp, initializeApp } from '@angular/fire/app';
import { provideFirestore, getFirestore } from '@angular/fire/firestore';
import { provideAuth, getAuth } from '@angular/fire/auth';
import { environment } from 'src/environments/env.dev';
import { PlaylistDisplayComponent } from './components/playlist-display/playlist-display.component';
import { PlaylistEditDialogComponent } from './components/playlist-edit-dialog/playlist-edit-dialog.component';
import { ConfirmDialogComponent } from './components/confirm-dialog/confirm-dialog.component';
import { TopTracksComponent } from './components/top-tracks/top-tracks.component';
import { SpotifySorterComponent } from './pages/spotify-sorter/spotify-sorter.component';
import { SpotifyStatsComponent } from './pages/spotify-stats/spotify-stats.component';
import { HomeComponent } from './pages/home/home.component';
import { HeaderComponent } from './components/header/header.component';
import { RecentlyPlayedComponent } from './components/recently-played/recently-played.component';

@NgModule({
  declarations: [
    AppComponent,
    SortPlaylistComponent,
    SetPlaylistsComponent,
    PlaylistDisplayComponent,
    PlaylistEditDialogComponent,
    ConfirmDialogComponent,
    TopTracksComponent,
    SpotifySorterComponent,
    SpotifyStatsComponent,
    HomeComponent,
    HeaderComponent,
    RecentlyPlayedComponent,
  ],
  imports: [
    BrowserModule,
    AppRoutingModule,
    BrowserAnimationsModule,
    HttpClientModule,
    FormsModule,
    provideFirebaseApp(() => initializeApp(environment.firebase)),
    provideFirestore(() => getFirestore()),
    provideAuth(() => getAuth()),
    MatCardModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    ReactiveFormsModule,
    MatSelectModule,
    MatFormFieldModule,
    
  ],
  providers: [],
  bootstrap: [AppComponent]
})
export class AppModule { }
