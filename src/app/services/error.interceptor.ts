import { Injectable } from '@angular/core';
import { HttpErrorResponse, HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Observable, catchError, throwError } from 'rxjs';
import { errorText } from './errors';
import { NoticeService } from './notice.service';

/** Shows the text of the backend's error code instead of leaving the page empty. */
@Injectable()
export class ErrorInterceptor implements HttpInterceptor {
  constructor(private notice: NoticeService) { }

  intercept(request: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    return next.handle(request).pipe(
      catchError((error: HttpErrorResponse) => {
        const code = typeof error.error?.error === 'string' ? error.error.error : null;
        if (code && error.status !== 409 && code !== 'forbidden') {
          this.notice.show(errorText(code, error.error?.params));
        }
        return throwError(() => error);
      }),
    );
  }
}
