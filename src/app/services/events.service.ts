import { Injectable, NgZone } from '@angular/core';
import { Observable, Subject, filter, map } from 'rxjs';
import { API_URL } from './api';
import { JobState } from './playlist.service';

interface BackendEvent {
  topic: string;
  data: any;
}

/** The backend's one stream (GET /events): each job's state at every step, so no page asks again and again. */
@Injectable({
  providedIn: 'root'
})
export class EventsService {
  private events$ = new Subject<BackendEvent>();

  constructor(zone: NgZone) {
    // EventSource reconnects by itself when the backend restarts.
    const source = new EventSource(`${API_URL}/events`);
    source.onmessage = message => zone.run(() => this.events$.next(JSON.parse(message.data)));
  }

  /** The state of a job ('library', 'apple', 'chosen', 'likes'...) each time it changes. */
  job(topic: string): Observable<JobState> {
    return this.on(topic);
  }

  on<T = any>(topic: string): Observable<T> {
    return this.events$.pipe(filter(e => e.topic === topic), map(e => e.data as T));
  }
}
