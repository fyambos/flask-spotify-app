import { Component, OnInit } from '@angular/core';
import { Stats, StatsService } from 'src/app/services/stats.service';
import { StatusService } from 'src/app/services/status.service';
import { TrackService } from 'src/app/services/track.service';

/** A bar, a point or a column under the pointer: what the tooltip says, where (in % of the chart). */
interface Hover {
  chart: string;
  x: number;
  y: number;
  title: string;
  detail: string;
}

/** What the playlists say about your taste, from whatever the app has (Spotify, an export, a file). */
@Component({
  selector: 'app-stats',
  templateUrl: './stats.component.html',
})
export class StatsComponent implements OnInit {
  stats: Stats | null = null;
  playlist = '';
  loading = true;
  hover: Hover | null = null;

  /** Spotify's own top tracks and recent plays, when Spotify is connected. */
  tab: 'top' | 'recent' = 'top';
  topTracks: any[] = [];
  recentTracks: any[] = [];
  spotify = false;

  readonly scaleWords: { [key: string]: [string, string] } = {
    valence: ['Sad', 'Happy'],
    energy: ['Calm', 'Energetic'],
    danceability: ['Not for dancing', 'Danceable'],
    acousticness: ['Electronic', 'Acoustic'],
  };

  // Chart geometry, computed once per load (viewBox units).
  readonly W = 600;
  readonly H = 160;
  years: { x: number; y: number; w: number; h: number; year: number; songs: number; inRange: boolean }[] = [];
  yearTicks: { x: number; label: number }[] = [];
  yearRange = { x: 0, w: 0 };
  added = { line: '', area: '', peak: { x: 0, y: 0 }, ticks: [] as { x: number; label: string }[] };
  moodPoints: { x: number; y: number; title: string; artist: string }[] = [];
  moodAverage = { x: 50, y: 50 };

  constructor(private statsService: StatsService, private trackService: TrackService, private statusService: StatusService) { }

  ngOnInit(): void {
    this.load();
    this.statusService.status$.subscribe(status => {
      const connected = !!status?.spotify?.connected && !status.spotify.limit;
      if (connected && !this.spotify) {
        this.trackService.getTopTracks().subscribe(tracks => this.topTracks = tracks);
        this.trackService.getRecentlyPlayedTracks().subscribe(tracks => this.recentTracks = tracks);
      }
      this.spotify = connected;
    });
  }

  load(): void {
    this.loading = true;
    this.statsService.getStats(this.playlist).subscribe({
      next: stats => { this.stats = stats; this.loading = false; this.layout(); },
      error: () => this.loading = false,
    });
  }

  get tracks(): any[] {
    return this.tab === 'top' ? this.topTracks : this.recentTracks;
  }

  /** Width of a bar, in % of the largest one. */
  width(value: number, values: number[]): number {
    return Math.max(3, (100 * value) / Math.max(...values, 1));
  }

  values<T>(items: T[], key: keyof T): number[] {
    return items.map(item => Number(item[key]));
  }

  percent(part: number, total: number): number {
    return total ? Math.round((100 * part) / total) : 0;
  }

  /** '2021-04' as 'April 2021' (short: 'Apr 2021'). */
  monthName(month: string, short = false): string {
    const [year, m] = month.split('-').map(Number);
    return new Date(year, m - 1, 1).toLocaleString('en', { month: short ? 'short' : 'long', year: 'numeric' });
  }

  private layout(): void {
    const p = this.stats?.parts;
    this.hover = null;

    // Years: one column per year, the years most songs came out in stand out.
    const perYear = p?.years?.per_year || [];
    const maxYear = Math.max(...perYear.map(y => y.songs), 1);
    const step = this.W / Math.max(perYear.length, 1);
    this.years = perYear.map((y, i) => {
      const h = (y.songs / maxYear) * (this.H - 8);
      return { x: i * step + 1, y: this.H - h, w: Math.max(step - 2, 1), h, year: y.year, songs: y.songs,
               inRange: !!p?.years && y.year >= p.years.from && y.year <= p.years.to };
    });
    this.yearTicks = perYear.map((y, i) => ({ x: i * step + step / 2, label: y.year })).filter(t => t.label % 10 === 0);
    const first = this.years.find(y => y.inRange);
    const last = [...this.years].reverse().find(y => y.inRange);
    this.yearRange = first && last ? { x: first.x - 1, w: last.x + last.w - first.x + 2 } : { x: 0, w: 0 };

    // Songs added per month: an area, its peak marked.
    const months = p?.added?.per_month || [];
    const maxMonth = Math.max(...months.map(m => m.songs), 1);
    const xOf = (i: number) => (months.length > 1 ? (i / (months.length - 1)) * this.W : this.W / 2);
    const yOf = (n: number) => this.H - (n / maxMonth) * (this.H - 12);
    const points = months.map((m, i) => `${xOf(i).toFixed(1)},${yOf(m.songs).toFixed(1)}`);
    this.added.line = points.length ? 'M' + points.join('L') : '';
    this.added.area = points.length ? `M0,${this.H}L${points.join('L')}L${this.W},${this.H}Z` : '';
    const peak = months.findIndex(m => m.month === p?.added?.busiest);
    this.added.peak = peak >= 0 ? { x: xOf(peak), y: yOf(months[peak].songs) } : { x: 0, y: 0 };
    this.added.ticks = months.map((m, i) => ({ x: xOf(i), label: m.month.slice(0, 4) }))
      .filter((t, i) => months[i].month.endsWith('-01'));

    // Mood map: every song by how happy (x) and how energetic (y) it is.
    this.moodPoints = (p?.mood?.points || []).map(([valence, energy, title, artist]) =>
      ({ x: valence * 100, y: 100 - energy * 100, title, artist }));
    const scale = (key: string) => p?.mood?.scales.find(s => s.key === key)?.average ?? 0.5;
    this.moodAverage = { x: scale('valence') * 100, y: 100 - scale('energy') * 100 };
  }

  /** The column, month or song under the pointer, for the tooltip. */
  onHover(chart: 'years' | 'added' | 'mood', event: MouseEvent): void {
    const box = (event.currentTarget as Element).getBoundingClientRect();
    const fx = (event.clientX - box.left) / box.width;
    const fy = (event.clientY - box.top) / box.height;
    const p = this.stats?.parts;
    if (chart === 'years' && this.years.length) {
      const column = this.years[Math.min(this.years.length - 1, Math.floor(fx * this.years.length))];
      this.hover = { chart, x: ((column.x + column.w / 2) / this.W) * 100, y: (column.y / this.H) * 100,
                     title: String(column.year), detail: `${column.songs} songs` };
    } else if (chart === 'added' && p?.added) {
      const months = p.added.per_month;
      const i = Math.round(fx * (months.length - 1));
      const yOf = (n: number) => 100 - (n / Math.max(...months.map(m => m.songs), 1)) * ((this.H - 12) / this.H) * 100;
      this.hover = { chart, x: months.length > 1 ? (i / (months.length - 1)) * 100 : 50, y: yOf(months[i].songs),
                     title: this.monthName(months[i].month), detail: `${months[i].songs} songs` };
    } else if (chart === 'mood' && this.moodPoints.length) {
      let best = this.moodPoints[0];
      let distance = Infinity;
      for (const point of this.moodPoints) {
        const d = (point.x - fx * 100) ** 2 + (point.y - fy * 100) ** 2;
        if (d < distance) { distance = d; best = point; }
      }
      this.hover = distance < 9 ? { chart, x: best.x, y: best.y, title: best.title, detail: best.artist } : null;
    }
  }
}
