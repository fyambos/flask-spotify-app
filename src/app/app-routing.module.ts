import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LikedSongsComponent } from './pages/liked-songs/liked-songs.component';
import { SetupComponent } from './pages/setup/setup.component';
import { GenresComponent } from './pages/genres/genres.component';
import { StatsComponent } from './pages/stats/stats.component';
import { SettingsComponent } from './pages/settings/settings.component';
import { LibraryComponent } from './pages/library/library.component';

const routes: Routes = [
  { path: '', redirectTo: '/likes', pathMatch: 'full' },
  { path: 'setup', component: SetupComponent },
  { path: 'likes', component: LikedSongsComponent },
  { path: 'genres', component: GenresComponent },
  { path: 'library', component: LibraryComponent },
  { path: 'stats', component: StatsComponent },
  { path: 'settings', component: SettingsComponent },
  { path: '**', redirectTo: '/likes' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
