import { Injectable } from '@angular/core';
import { HttpErrorResponse, HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Observable, catchError, throwError } from 'rxjs';
import { NoticeService } from './notice.service';

/** Shows the backend's error message instead of leaving the page empty. */
@Injectable()
export class ErrorInterceptor implements HttpInterceptor {
  constructor(private notice: NoticeService) { }

  intercept(request: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    return next.handle(request).pipe(
      catchError((error: HttpErrorResponse) => {
        const message = typeof error.error?.error === 'string' ? error.error.error : null;
        if (message && error.status !== 409) {
          this.notice.show(message);
        }
        return throwError(() => error);
      }),
    );
  }
}
