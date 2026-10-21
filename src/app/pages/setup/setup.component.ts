import { Subscription } from 'rxjs';
import { EventsService } from 'src/app/services/events.service';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import {
  GenrePlaylist, JobState, PlaylistService, PlaylistStats, RuleSuggestion, SetupStatus, SpotifyPlaylist,
} from 'src/app/services/playlist.service';
import { applySuggestion, suggestionKey } from 'src/app/services/rule-suggestions';
import { APP_TITLE, FEATURES } from 'src/app/services/features';

type Step = 'welcome' | 'choose' | 'analysing' | 'review';

@Component({
  selector: 'app-setup',
  templateUrl: './setup.component.html',
})
export class SetupComponent implements OnInit, OnDestroy {
  step: Step = 'welcome';
  appTitle = APP_TITLE;
  features = FEATURES;
  steps: { id: Step; label: string }[] = [
    { id: 'welcome', label: 'Connect' },
    { id: 'choose', label: 'Choose playlists' },
    { id: 'review', label: 'Review rules' },
  ];
  status: SetupStatus | null = null;
  playlists: SpotifyPlaylist[] = [];
  byId: { [id: string]: SpotifyPlaylist } = {};
  selected = new Set<string>();
  private initiallySelected = new Set<string>();
  search = '';
  reconfiguring = false;

  job: JobState | null = null;
  proposal: GenrePlaylist[] = [];
  stats: { [id: string]: PlaylistStats } = {};
  fallbackGenre = '';
  multiPlaylist = false;
  editing: GenrePlaylist | null = null;
  saving = false;
  applied = new Set<string>();
  artistRules: { [id: string]: { name: string; playlist: string } } = {};
  rulesEdited = false;
  evaluation: JobState | null = null;
  private subscriptions: Subscription[] = [];

  constructor(private playlistService: PlaylistService, private router: Router, private route: ActivatedRoute,
              private events: EventsService) { }

  ngOnInit(): void {
    this.loadStatus();
    // The analyses and the Spotify login report through the backend's stream.
    this.subscriptions.push(
      this.events.job('setup').subscribe(job => {
        this.job = job;
        if (!job.running) this.analysisDone();
      }),
      this.events.job('reevaluate').subscribe(job => {
        this.evaluation = job;
        if (!job.running) this.evaluationDone();
      }),
      this.events.on('status').subscribe(() => this.loadStatus()),
    );
    this.playlistService.getConfig().subscribe(config => {
      config.playlists.forEach(p => {
        const id = p.playlist_id || 'app:' + p.id;
        this.selected.add(id);
        this.initiallySelected.add(id);
      });
      this.fallbackGenre = config.fallback_genre;
      this.multiPlaylist = config.multi_playlist;
      this.artistRules = config.artist_rules;
    });
    this.playlistService.getSetupAnalysis().subscribe(state => {
      if (state.job.running) {
        this.step = 'analysing';
        this.job = state.job;
      }
    });
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach(s => s.unsubscribe());
  }

  backendDown = false;

  loadStatus(): void {
    this.playlistService.getSetupStatus().subscribe({
      next: status => {
        this.backendDown = false;
        this.status = status;
        this.reconfiguring = status.configured;
        // Sorting setup (from Sort Playlists): needs playlists, from Spotify or an imported file.
        if (status.spotify.connected || status.playlists) {
          if (!this.playlists.length) this.loadPlaylists();
          if (this.route.snapshot.queryParamMap.get('step') === 'choose') {
            this.step = 'choose';
          }
        }
      },
      error: () => this.backendDown = true,
    });
  }

  login(): void {
    this.playlistService.spotifyLogin().subscribe(() => {
      if (this.status) this.status.spotify.logging_in = true;
    });
  }

  loadPlaylists(): void {
    this.playlistService.getPlaylists().subscribe(playlists => {
      this.playlists = playlists;
      this.byId = Object.fromEntries(playlists.map(p => [p.id, p]));
    });
  }

  stepIndex(step: Step): number {
    return step === 'analysing' ? 2 : this.steps.findIndex(s => s.id === step);
  }

  get visiblePlaylists(): SpotifyPlaylist[] {
    const search = this.search.trim().toLowerCase();
    return this.playlists
      .filter(p =>
        // Spotify doesn't let the app add songs to playlists of other users.
        (p.owned !== false && p.id !== 'liked' || this.selected.has(p.id))
        && (!search || p.name.toLowerCase().includes(search)))
      // Playlists already configured first (stable while you click).
      .sort((a, b) => Number(this.initiallySelected.has(b.id)) - Number(this.initiallySelected.has(a.id)));
  }

  toggle(p: SpotifyPlaylist): void {
    this.selected.has(p.id) ? this.selected.delete(p.id) : this.selected.add(p.id);
  }

  analyse(): void {
    const chosen = this.playlists
      .filter(p => this.selected.has(p.id))
      .map(p => ({ playlist_id: p.id, name: p.name.trim() }));
    this.step = 'analysing';
    this.job = { running: true, step: 'Starting' };
    this.playlistService.startSetupAnalysis(chosen, this.multiPlaylist).subscribe({
      error: () => this.analysisDone(),
    });
  }

  /** The analysis is done (or could not start): its proposal is read once. */
  private analysisDone(): void {
    this.playlistService.getSetupAnalysis().subscribe(state => {
      this.job = state.job;
      if (!state.job.running && !state.job.error && state.proposal) {
        this.proposal = state.proposal.playlists;
        this.stats = state.proposal.stats;
        this.multiPlaylist = !!state.proposal.multi_playlist;
        if (!this.proposal.some(p => p.name === this.fallbackGenre)) {
          this.fallbackGenre = this.proposal.find(p => p.name.toLowerCase() === 'other')?.name || '';
        }
        this.step = 'review';
      }
    });
  }

  get averageAccuracy(): number {
    const values = Object.values(this.stats);
    const tracks = values.reduce((n, s) => n + s.track_count, 0) || 1;
    return values.reduce((n, s) => n + s.accuracy * s.track_count, 0) / tracks;
  }

  get weakPlaylists(): GenrePlaylist[] {
    return this.proposal.filter(p => this.stats[p.id] && this.stats[p.id].track_count > 0 && this.stats[p.id].accuracy < 0.65);
  }

  get weakNames(): string {
    return this.weakPlaylists.map(p => p.name).join(', ');
  }

  saveEdit(updated: GenrePlaylist): void {
    this.proposal = this.proposal.map(p => p.id === updated.id ? updated : p);
    this.editing = null;
    this.rulesEdited = true;
  }

  reorderProposal(list: GenrePlaylist[]): void {
    this.proposal = list;
    this.rulesEdited = true;
  }

  applyRuleSuggestion(s: RuleSuggestion): void {
    this.applied = new Set(this.applied).add(suggestionKey(s));
    if (s.type === 'artist') {
      this.playlistService.addArtistRule(s.value, s.artist || '', s.playlist).subscribe(() => {
        this.artistRules = { ...this.artistRules, [s.value]: { name: s.artist || '', playlist: s.playlist } };
      });
      return;
    }
    if (s.type === 'multi_playlist') {
      this.multiPlaylist = true;
    } else {
      this.proposal = applySuggestion(this.proposal, s);
    }
    this.rulesEdited = true;
  }

  recheck(): void {
    this.evaluation = { running: true, step: 'Starting' };
    this.playlistService.evaluateSetup(this.proposal, this.multiPlaylist).subscribe({
      error: () => this.evaluationDone(),
    });
  }

  private evaluationDone(): void {
    this.playlistService.getSetupAnalysis().subscribe(state => {
      this.evaluation = state.evaluation;
      if (!state.evaluation.running && !state.evaluation.error && state.proposal) {
        this.stats = state.proposal.stats;
        this.applied = new Set();
        this.rulesEdited = false;
      }
    });
  }

  removeFromProposal(p: GenrePlaylist): void {
    this.proposal = this.proposal.filter(x => x.id !== p.id);
    this.rulesEdited = true;
  }

  finish(): void {
    this.saving = true;
    this.playlistService.applySetup(this.proposal, this.fallbackGenre, this.multiPlaylist).subscribe({
      next: () => window.location.assign('/sort'),
      error: () => this.saving = false,
    });
  }
}
