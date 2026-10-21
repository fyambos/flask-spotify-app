import { Pipe, PipeTransform } from '@angular/core';
import { errorText } from '../services/errors';

/** {{ job.error | errorText: job.error_params }}: the text of a backend error code. */
@Pipe({ name: 'errorText' })
export class ErrorTextPipe implements PipeTransform {
  transform(code: string | null | undefined, params?: { [key: string]: string } | null): string {
    return errorText(code, params);
  }
}
