import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { SpotifySorterComponent } from './pages/spotify-sorter/spotify-sorter.component';
import { SpotifyStatsComponent } from './pages/spotify-stats/spotify-stats.component';
import { HomeComponent } from './pages/home/home.component';
import { RecentlyPlayedComponent } from './components/recently-played/recently-played.component';
import { TopTracksComponent } from './components/top-tracks/top-tracks.component';

const routes: Routes = [
  { path: '' , redirectTo: '/home', pathMatch: 'full' },
  { path: 'sorter', component: SpotifySorterComponent },
  { path: 'stats', component: SpotifyStatsComponent },
  { path: 'home', component: HomeComponent },
  { path: 'recently-played', component: RecentlyPlayedComponent },
  { path: 'top-tracks', component: TopTracksComponent },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
