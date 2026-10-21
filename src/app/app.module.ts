import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { HTTP_INTERCEPTORS, HttpClientModule } from '@angular/common/http';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialogModule } from '@angular/material/dialog';
import { DragDropModule } from '@angular/cdk/drag-drop';
import {
  LucideAngularModule, AlertCircle, AlertTriangle, ArrowDownCircle, ArrowRight, BarChart3, Check, CheckCircle2, ChevronLeft,
  ChevronRight, Download, ExternalLink, EyeOff, FolderTree, GripVertical, HardDrive, Heart, Home, Info, Laptop, ListMusic,
  Loader2, LogIn, Monitor, Music2, Pencil, Plus, RefreshCw, Search, Settings, Smartphone, Sparkles, TabletSmartphone, Trash2,
  Wand2, X,
} from 'lucide-angular';

import { AppRoutingModule } from './app-routing.module';
import { ErrorTextPipe } from './pipes/error-text.pipe';
import { AppComponent } from './app.component';
import { ErrorInterceptor } from './services/error.interceptor';
import { ConfirmDialogComponent } from './components/confirm-dialog/confirm-dialog.component';
import { ChipInputComponent } from './components/chip-input/chip-input.component';
import { GenreListComponent } from './components/genre-list/genre-list.component';
import { RuleEditorComponent } from './components/rule-editor/rule-editor.component';
import { PlaylistFoldersComponent } from './components/playlist-folders/playlist-folders.component';
import { LikedSongsComponent } from './pages/liked-songs/liked-songs.component';
import { SetupComponent } from './pages/setup/setup.component';
import { GenresComponent } from './pages/genres/genres.component';
import { StatsComponent } from './pages/stats/stats.component';
import { SettingsComponent } from './pages/settings/settings.component';
import { LibraryComponent } from './pages/library/library.component';
import { HomeComponent } from './pages/home/home.component';
import { ImportComponent } from './pages/import/import.component';

@NgModule({
  declarations: [
    AppComponent,
    ConfirmDialogComponent,
    ChipInputComponent,
    GenreListComponent,
    RuleEditorComponent,
    PlaylistFoldersComponent,
    LikedSongsComponent,
    SetupComponent,
    GenresComponent,
    StatsComponent,
    SettingsComponent,
    LibraryComponent,
    HomeComponent,
    ImportComponent,
    ErrorTextPipe,
  ],
  imports: [
    BrowserModule,
    AppRoutingModule,
    BrowserAnimationsModule,
    HttpClientModule,
    FormsModule,
    MatDialogModule,
    DragDropModule,
    LucideAngularModule.pick({
      AlertCircle, AlertTriangle, ArrowDownCircle, ArrowRight, BarChart3, Check, CheckCircle2, ChevronLeft, ChevronRight, Download, ExternalLink, GripVertical,
      EyeOff, FolderTree, HardDrive, Heart, Home, Laptop, LogIn, Monitor, Smartphone, TabletSmartphone,
      Info, ListMusic, Loader2, Music2, Pencil, Plus, RefreshCw, Search, Settings, Sparkles, Trash2, Wand2, X,
    }),
  ],
  providers: [{ provide: HTTP_INTERCEPTORS, useClass: ErrorInterceptor, multi: true }],
  bootstrap: [AppComponent]
})
export class AppModule { }
