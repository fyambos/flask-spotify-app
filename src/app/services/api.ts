function apiUrl(): string {
  try {
    // Developer override, e.g. to point the app at a second backend.
    return localStorage.getItem('apiUrl') || 'http://localhost:5001';
  } catch {
    return 'http://localhost:5001';
  }
}

export const API_URL = apiUrl();
