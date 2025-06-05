# Playlist Manager
> A web application for managing Spotify playlists with Firestore integration. Users can sort tracks by genre, edit playlists, and delete playlists.

## Features
* Display Saved Playlists: View saved playlists with album artwork and details fetched from Spotify.
* Edit Genres: Edit playlist genres in a user-friendly modal, with real-time updates in Firestore.
* Delete Playlists: Delete playlists with a confirmation dialog to ensure no accidental deletions.
* Sort Playlists: Automatically sort tracks into genre-specific playlists using Spotify data.

## Directory Structure
```plain text
root/
├── src/
│   ├── app/                 # Angular components and services
│   ├── assets/              # Static assets like images and icons
│   ├── environments/        # Environment configurations
├── backend/                 # Backend logic (Python Flask app with Spotify integration)
├── package.json             # Frontend dependencies
└── README.md                # Project documentation
```

## Prerequisites
### Frontend
* Node.js: Install Node.js for the Angular application.
* Angular CLI: Install the Angular CLI globally: npm install -g @angular/cli.

### Backend
* Python: Ensure Python 3.7+ is installed.
* Spotify API: Set up a Spotify Developer Account and retrieve your client ID and client secret.
* Firestore: Configure a Firebase project and download the Firebase Admin SDK JSON.

## Setup
### Frontend Setup
1. Navigate to the src directory:
```bash
cd src
```
2. Install dependencies:
```bash
npm install
```
3. Install angular CLI:
```bash
npm install -g @angular/cli
```
4. Start the development server:
```bash
ng serve
```
5. Access the app at http://localhost:4200.

### Backend Setup
1. Navigate to the backend directory:
```bash
cd backend
```
2. Install required Python packages:
```bash
pip install -r requirements.txt
```
3. Run the Flask server:
```bash
python app.py
```

## Configuration
### Spotify API
Add your Spotify API credentials to the backend configuration:
> Client ID and Client Secret in an .env file (no name) in the same directory as app.py.
```bash
SPOTIFY_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxx
SPOTIFY_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Firebase Firestore
Replace the Firebase Admin SDK JSON path in the backend with your Firebase credentials:
```python
cred = credentials.Certificate('/path/to/firebase-admin-sdk.json')
```
Steps to Obtain Firebase Admin SDK JSON:
1. Go to Firebase Console: Navigate to your Firebase project at https://console.firebase.google.com.
2. Go to Project Settings:
    * In the top left corner, click on the gear icon (⚙️) and select Project Settings.
3. Create a Service Account:
    * Go to the Service accounts tab.
    * Click on Generate new private key. This will download a JSON file to your computer. This file contains all the necessary credentials to allow server-side access to Firebase services.

### Angular Environment
Update src/environments/env.dev.ts with your Firebase configuration:
```typescript
export const environment = {
  production: false,
  firebase: {
    apiKey: "YOUR_API_KEY",
    authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
    projectId: "YOUR_PROJECT_ID",
    storageBucket: "YOUR_PROJECT_ID.appspot.com",
    messagingSenderId: "YOUR_SENDER_ID",
    appId: "YOUR_APP_ID",
  },
};
```

## Usage
1. **Adding and Viewing Playlists**: Navigate to the home page to see saved playlists with album covers, names, and genres.
    * You define how to sort your tracks into specific playlists, for this, simply add those specific playlists via the add button, and define the spotify genres that should be associated with this playlist. This feature helps you categorize your tracks based on their genres.
    * You can find the spotify genres [here](https://gist.github.com/andytlr/4104c667a62d8145aa3a).
    * You can also see the song's genres in the Flask node of app.py when sorting playlists.
2. **Editing Genres**:
    * Click the "Edit" icon to modify genres.
    * Save changes to update Firestore in real-time.
3. **Deleting Playlists**:
    * Click the "Delete" icon to open a confirmation dialog.
    * Confirm to delete the playlist from Firestore.
4. **Sorting Playlists**:
    * Use the /sort-playlist endpoint in the backend to sort tracks into genre-specific playlists.

## Tech Stack
* **Frontend**: Angular, Tailwind CSS
* **Backend**: Python Flask
* **Database**: Firebase Firestore
* **Music API**: Spotify Web API

## Contributing
1. Fork the repository.
2. Create a feature branch: git checkout -b feature-name.
3. Commit your changes: git commit -m "Add feature description".
4. Push to the branch: git push origin feature-name.
5. Open a pull request.

## License
This project is licensed under the MIT License. See the LICENSE file for details.
