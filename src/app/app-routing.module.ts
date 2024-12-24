import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { SpotifySorterComponent } from './pages/spotify-sorter/spotify-sorter.component';
import { SpotifyStatsComponent } from './pages/spotify-stats/spotify-stats.component';
import { HomeComponent } from './pages/home/home.component';

const routes: Routes = [
  { path: '' , redirectTo: '/home', pathMatch: 'full'},
  { path: 'sorter', component: SpotifySorterComponent},
  { path: 'stats', component: SpotifyStatsComponent},
  { path: 'home', component: HomeComponent}
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
