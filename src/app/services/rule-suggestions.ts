import { GenrePlaylist, RuleSuggestion } from './playlist.service';

export function suggestionKey(s: RuleSuggestion): string {
  return `${s.type}|${s.playlist}|${s.value}`;
}

export function suggestionLabel(s: RuleSuggestion, playlists: GenrePlaylist[]): string {
  const name = (id: string) => playlists.find(p => p.id === id)?.name || '—';
  switch (s.type) {
    case 'add_genre': return `Add genre “${s.value}” to ${name(s.playlist)}`;
    case 'exclude_genre': return `Exclude “${s.value}” from ${name(s.playlist)}`;
    case 'album_keyword': return `Add album keyword “${s.value}” to ${name(s.playlist)}`;
    case 'title_keyword': return `Add title keyword “${s.value}” to ${name(s.playlist)}`;
    case 'move_above': return `Move ${name(s.playlist)} above ${name(s.value)}`;
    case 'multi_playlist': return 'Allow songs in several playlists';
    case 'artist': return `Always sort ${s.artist} into ${name(s.playlist)}`;
  }
}

/** True when the suggestion is already part of the current rules. */
export function isInRules(s: RuleSuggestion, playlists: GenrePlaylist[],
                          artistRules: { [id: string]: { playlist: string } }, multiPlaylist: boolean): boolean {
  const target = playlists.find(p => p.id === s.playlist);
  switch (s.type) {
    case 'artist': return artistRules[s.value]?.playlist === s.playlist;
    case 'multi_playlist': return multiPlaylist;
    case 'add_genre': return !!target?.genre_names.includes(s.value);
    case 'exclude_genre': return !!target?.exclude_genres.includes(s.value);
    case 'album_keyword': return !!target?.album_keywords.includes(s.value);
    case 'title_keyword': return !!target?.title_keywords.includes(s.value);
    case 'move_above': {
      const ids = playlists.map(p => p.id);
      return ids.indexOf(s.playlist) >= 0 && ids.indexOf(s.playlist) < ids.indexOf(s.value);
    }
  }
}

/** Rules after applying a suggestion. Artist and multi-playlist suggestions are handled by the caller. */
export function applySuggestion(playlists: GenrePlaylist[], s: RuleSuggestion): GenrePlaylist[] {
  const list = playlists.map(p => ({ ...p }));
  const target = list.find(p => p.id === s.playlist);
  if (!target) return list;
  const add = (values: string[]) => values.includes(s.value) ? values : [...values, s.value];
  if (s.type === 'add_genre') target.genre_names = add(target.genre_names);
  if (s.type === 'exclude_genre') target.exclude_genres = add(target.exclude_genres);
  if (s.type === 'album_keyword') target.album_keywords = add(target.album_keywords);
  if (s.type === 'title_keyword') target.title_keywords = add(target.title_keywords);
  if (s.type === 'move_above') {
    const from = list.indexOf(target);
    list.splice(from, 1);
    const to = list.findIndex(p => p.id === s.value);
    list.splice(to < 0 ? list.length : to, 0, target);
  }
  return list;
}
