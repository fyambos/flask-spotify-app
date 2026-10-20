import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LikedSongsComponent } from './pages/liked-songs/liked-songs.component';
import { SetupComponent } from './pages/setup/setup.component';
import { GenresComponent } from './pages/genres/genres.component';
import { StatsComponent } from './pages/stats/stats.component';
import { SettingsComponent } from './pages/settings/settings.component';
import { LibraryComponent } from './pages/library/library.component';
import { HomeComponent } from './pages/home/home.component';
import { ImportComponent } from './pages/import/import.component';

const routes: Routes = [
  { path: '', redirectTo: '/home', pathMatch: 'full' },
  { path: 'home', component: HomeComponent },
  { path: 'setup', component: SetupComponent },
  { path: 'sort', component: LikedSongsComponent },
  { path: 'sort/rules', component: GenresComponent },
  { path: 'import', component: ImportComponent },
  { path: 'likes', redirectTo: '/sort' },
  { path: 'genres', redirectTo: '/sort/rules' },
  { path: 'library', component: LibraryComponent },
  { path: 'stats', component: StatsComponent },
  { path: 'settings', component: SettingsComponent },
  { path: '**', redirectTo: '/home' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
