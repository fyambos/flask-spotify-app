import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

/** One message shown at the top of the app (errors from the backend). */
@Injectable({ providedIn: 'root' })
export class NoticeService {
  readonly message$ = new BehaviorSubject<string | null>(null);

  show(message: string): void {
    this.message$.next(message);
  }

  clear(): void {
    this.message$.next(null);
  }
}
