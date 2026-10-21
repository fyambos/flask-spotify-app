# Music Sorter : spec

Statut : questions réglées le 2026-10-20. Rien n'est codé tant que cette spec n'est pas validée.

L'app tourne sur Mac et sur Windows. Les chemins `~/Music` désignent le dossier Musique du système : `~/Music` sur Mac, `C:\Users\<nom>\Music` sur Windows.

Les textes d'interface entre guillemets sont en anglais, comme dans l'app. Ils suivent la règle des textes (pas de style IA, tes mots repris tels quels, fautes évidentes corrigées). Ceux marqués *(à valider)* sont de moi.

## 1. Ce qu'est l'app

**Spotify Organizer & Music Downloader.**
- Sync with Spotify.
- Download from Spotify as MP3. L'app passe par YouTube Music pour télécharger, mais on n'a jamais affaire à YouTube Music.
- Créer des playlists MP3 qui suivent les playlists Spotify.
- Envoyer les playlists MP3 sur ses ordinateurs et téléphones, pour écouter sans plateforme de streaming.
- Ranger automatiquement les Liked Songs, ou n'importe quelle playlist, dans des playlists Spotify au choix.
- Voir ses stats Spotify.

C'est un outil qui trie une playlist (Liked Songs par défaut) et qui télécharge des playlists. Ce n'est pas un outil qui télécharge seulement les Liked Songs.

**YouTube Music** n'apparaît que dans le réglage de qualité (Settings).

## 2. Ce que chaque fonction demande

Rien n'est bloqué en entier. Chaque page dit ce qui lui manque, sans renvoyer vers l'assistant.

| Fonction | Spotify Premium (API) | Import de fichier |
|---|---|---|
| Télécharger les playlists | oui | oui |
| Playlists MP3, Apple Music, appareils | oui | oui |
| Trier (Sort Playlists) | oui, écrit sur Spotify | oui, en local seulement |
| Stats | oui | non (page masquée) |

- **Premium** : depuis février 2026, le propriétaire d'une app développeur Spotify doit avoir Premium. Chaque personne crée sa propre app.
- **Pas d'API client Spotify** (celle du lecteur web) : contraire aux conditions de Spotify, risque de suspension du compte.
- **Pas d'ytmusicapi** : risque de ban YouTube.
- **Pas d'automatisation du site TuneMyMusic** : pas d'API, et ce serait contourner leurs limites.

## 3. Premier démarrage

États dans l'ordre (déjà codés, textes validés) :
1. **Backend arrêté** : « The backend is not running. Start it with `python app.py` in src/backend, then reload. »
2. **Clés Spotify absentes** : trois étapes (créer l'app sur developer.spotify.com/dashboard avec un compte Premium, mettre la Redirect URI, copier les clés dans `src/backend/.env`).
3. **Clés présentes, pas connecté** : « Not connected. », bouton « Log in to Spotify ». Pendant la connexion : « Log in on the Spotify page that opened in your browser. »

**Welcome** reprend l'explication de Home, puis propose deux chemins côte à côte :
- **« Connect Spotify »** (Premium) : synchro directe, tri écrit sur Spotify, stats.
- **« Import from any streaming service »** (sans Premium, mis en avant) : via TuneMyMusic. Marche depuis Spotify gratuit, Apple Music, Deezer, YouTube Music…

Changement à prévoir : l'étape « clés absentes » ne doit plus être la seule entrée. Sans Premium, on passe directement à l'import.

## 4. Menu

Home, Library, Sort Playlists, Stats (seulement si Spotify est connecté), Settings.

## 5. Home

Déjà codé :
- titre « Spotify Organizer & Music Downloader », sous-titre « Sync with Spotify. » ;
- un bandeau avec l'état de la bibliothèque et des raccourcis (Sync, Review) ;
- quatre cartes : Download from Spotify as MP3, Send your MP3 playlists to your computers or phones, Organize Liked Songs, Spotify stats.

La carte « Organize Liked Songs / Automatically organize liked songs into Spotify playlists of your choice. » est validée telle quelle. Dans l'app, on peut trier n'importe quelle playlist, pas seulement Liked Songs.

## 6. Téléchargements

### Playlists téléchargées
Indépendantes du tri. Settings → « Playlists to download » :
- **« All my playlists »** (par défaut) : toutes **tes** playlists, plus Liked Songs. Avec Spotify connecté, les playlists d'autres personnes n'y sont pas. En mode import, l'app ne connaît pas le propriétaire : tout ce qui est dans le fichier est téléchargé, avec le message « Playlists from other users are included. Choose playlists to remove them. »
- **« Choose playlists »** : une liste à cocher, avec recherche. Liked Songs est une playlist comme les autres.
  - Une nouvelle playlist apparaît avec la mention **« New »**. Elle n'est pas cochée automatiquement.
  - Les playlists d'autres personnes peuvent être cochées. Elles portent la mention **« From another user »**.

Disparaissent de l'app : « Liked Songs only », « Non-Liked Songs », « genre playlist ».

### Chansons retirées
Une chanson est retirée quand elle n'est plus dans aucune playlist téléchargée. Réglage existant : la garder, la déplacer dans `_Removed`, ou la supprimer.

### Emplacement des fichiers
Dossier musique par défaut : le dossier Musique du système (`~/Music` sur Mac, `C:\Users\<nom>\Music` sur Windows).

Par défaut : `<dossier musique>/Music Sorter/<Artiste de l'album>/<Album>/<Artiste> - <Titre>.mp3`. Les `.m3u8` vont dans `<dossier musique>/Music Sorter/Playlists/`.
- **Artiste de l'album**, comme Apple Music, iTunes, Plex et MusicBrainz Picard. Un album avec featurings reste dans un dossier, une compilation va dans « Various Artists ». Un seul fichier par chanson, pas de doublon.

Réglage **« File layout »** : des cartes à cliquer, chacune avec un exemple de chemin réel mis à jour en direct.
- **Artist / Album** (par défaut)
- **Artist**
- **One folder**, avec un champ pour le nom du dossier
- **First playlist** : le dossier de la première playlist de la chanson, dans un ordre réglable par glisser-déposer. Recalculé à chaque Sync à partir des identifiants, pas des noms :
  - playlist renommée → dossier renommé ;
  - playlist supprimée ou chanson retirée → la chanson passe dans sa playlist suivante ;
  - plus dans aucune playlist → réglage des chansons retirées ;
  - ordre changé → les fichiers concernés sont déplacés.

**Changer de rangement** : au Sync suivant, les fichiers sont déplacés, jamais retéléchargés. Une confirmation affiche le nombre de fichiers avant de lancer.

### Tes fichiers actuels
- Passent de `~/Music/Spotify/<Genre>/` à `~/Music/Music Sorter/<Artiste de l'album>/<Album>/`. Apple Music suit les nouveaux emplacements.
- Les anciens fichiers de 2022 non reconnus restent dans `~/Music/Spotify/`.
- Sauvegarde avant de déplacer, et confirmation de ta part avant de toucher à tes fichiers.

### Tags
- **Avec Spotify** : métadonnées Spotify. Genre : le premier genre Spotify de l'artiste, sinon Last.fm. Tag `SPOTIFY_ID`.
- **En mode import** : métadonnées de YouTube Music, plus les genres Last.fm. `SPOTIFY_ID` quand le fichier importé le donne (c'est le cas des CSV TuneMyMusic depuis Spotify).

### Qualité
YouTube Music Premium (cookies.txt) pour 256 kbps, sinon environ 130 kbps. Réglage existant.

## 7. Sort Playlists

### Noms
- **« Sort from »** : la ou les playlists à trier. Liked Songs par défaut.
- **« Sort into »** : les playlists qui reçoivent les chansons, chacune avec ses règles.
- Une seule « Sort from » par défaut, plusieurs possibles. Une playlist peut être à la fois « Sort from » et « Sort into ».

### Page
- **En haut** : les playlists « Sort from », modifiables.
- **Contenu principal** : la liste actuelle de la page Liked Songs (to review, ready, added, already sorted).
- **Bouton « Playlists & rules »** : ouvre la page des playlists « Sort into » et de leurs règles (l'actuelle page Genres), avec un retour. Pas d'onglets, « Review » n'a pas de sens comme nom d'onglet.
- La section « Sort another playlist » de Settings disparaît, puisque « Sort from » la remplace.

### Comportement
- La chanson reste dans « Sort from ». Le tri l'ajoute dans sa ou ses playlists « Sort into ».
- La retirer de « Sort from » ne change rien.
- La retirer de « Sort into » **et** de « Sort from » : si elle n'est plus dans aucune playlist téléchargée, le réglage des chansons retirées s'applique.
- On peut **créer une playlist « Sort into » qui n'existe que dans l'app**. Elle est créée sur Spotify à la synchro suivante, si Spotify est connecté.
- Les règles existantes restent : genres, genres exclus, mots-clés d'album et de titre, priorité, historique des artistes, artistes retenus, « Several playlists per song ».

## 8. Tri sans écriture sur Spotify

Trois cas : pas de Premium, quota épuisé, mode import.

- **L'app garde toujours le tri chez elle** : la ou les playlists « Sort into » de chaque chanson sont enregistrées en local. Avec Spotify en Premium, elle les écrit en plus sur Spotify.
- **Sans écriture sur Spotify** : le tri sert aux téléchargements, aux `.m3u8` et à Apple Music. La page affiche « Not synced with Spotify » et le nombre de changements en attente.
- **Quand Spotify redevient disponible**, pour chaque playlist « Sort into », l'app compare trois états :
  1. ce qu'elle avait vu sur Spotify à la dernière synchro ;
  2. ce qu'elle a trié depuis ;
  3. ce qu'il y a sur Spotify maintenant.

  Exemples :
  - triée dans l'app, absente de Spotify → à ajouter sur Spotify ;
  - retirée à la main sur Spotify depuis la dernière synchro → retirée aussi dans l'app (le geste manuel gagne) ;
  - placée à la main sur Spotify → reprise dans l'app ;
  - plus likée → aucun effet sur les « Sort into » (règle du point 7).

  Avant d'appliquer, un écran « Sync with Spotify » montre : X à ajouter sur Spotify, Y retirées sur Spotify qui seront retirées dans l'app. Rien n'est appliqué sans validation.
- **Première connexion, sans historique** : Spotify sert de référence. Ce que l'app a trié de son côté est proposé comme ajouts.
- **En mode import**, « Spotify maintenant » est le dernier fichier importé, et « dernière synchro » le fichier précédent.

## 9. Mode import (sans Premium)

### TuneMyMusic (méthode principale)
Testé : l'export en fichier de toute la bibliothèque passe en une fois (10 906 lignes, 112 playlists, Liked Songs, artistes suivis). La limite de 500 chansons ne concerne pas l'export en fichier.

Colonnes du CSV : `Track name, Artist name, Album, Playlist name, Type, ISRC, Spotify - id`.
- `Type` : `Favorite` (Liked Songs, nom « Favorite Songs »), `Playlist`, `Artist` (artistes suivis, ignorés).
- Le lien avec les fichiers déjà téléchargés et avec le tri se fait par l'ID Spotify. Depuis un autre service, sans ID Spotify : par l'ISRC, puis par artiste + titre.
- Pas de date d'ajout : les nouvelles chansons sont trouvées en comparant avec l'import précédent.
- Pas de dossiers de playlists (comme avec l'API).

Parcours dans l'app :
1. Un guide pas à pas, avec un bouton « Open TuneMyMusic ». **Avant de commencer**, le guide prévient : « Playlists from other users are limited to 500 songs. To leave them out, unselect them in TuneMyMusic. » *(à valider)*
2. Sur TuneMyMusic : choisir le service, se connecter, charger la bibliothèque, désélectionner les playlists à exclure, « Export to file » en CSV.
3. L'app surveille le dossier Téléchargements, repère le fichier, l'importe, compare avec l'import précédent, télécharge ce qui manque, met à jour les playlists MP3 et Apple Music.

Pour mettre à jour, on refait l'export. Il n'y a pas de synchro automatique possible sans Premium.

**Rappel** : quand le dernier import a plus de 7 jours, un bandeau s'affiche : « Last import: {n} days ago. » avec les boutons « Import » et « Don't show again ». *(à valider)*

### Exportify
Gratuit, sans Premium, depuis Spotify seulement. Exportify (exportify.net) passe par l'API Spotify avec sa propre app : un compte gratuit suffit.
- « Export All » donne un zip `spotify_playlists.zip`, un CSV par playlist, nommé d'après la playlist (`Liked_Songs.csv` pour Liked Songs, `Saved_Albums.csv` ignoré).
- Colonnes utilisées : `Track URI, ISRC, Track Name, Album Name, Artist Name(s)` (séparés par `;`), `Release Date, Duration (ms), Added By`.
- Le nom de fichier perd des caractères (« relax/study » → « relaxstudy », espaces → `_`) : la playlist est retrouvée en ignorant ponctuation et espaces, et garde son vrai nom.
- Propriétaire : `Added By` de Liked Songs donne ton compte. Une playlist où aucune chanson n'est ajoutée par toi est celle d'une autre personne.
- Une chanson deux fois dans une playlist y reste deux fois, comme avec l'API.

Texte de la page Import : « Exportify » / « Free. Exports Spotify playlists to a file. », puis « Open Exportify », « Click Get Started and log in to Spotify. », « Click Export All, then save the zip file in your Downloads folder. It is imported automatically. » *(à valider)*

### Si Exportify disparaît
Plan de secours, pas à faire tant qu'Exportify marche : une extension de navigateur (ou un bouton à glisser dans les favoris) sur open.spotify.com, connecté. Elle lit les playlists avec le jeton que le lecteur web de Spotify a déjà obtenu lui-même, puis les passe à Music Sorter.
- Ne fabrique pas le code TOTP et n'extrait aucune clé du lecteur : seulement la session de l'utilisateur, dans son navigateur.
- Utilise les requêtes internes du site, pas l'API officielle : casse quand Spotify change son site, et sans doute contraire à leurs conditions d'utilisation (risque de blocage du compte).

### D'où viennent les playlists
- Spotify connecté et pas bloqué : Check lit Spotify, même après l'import d'un fichier.
- Spotify bloqué ou pas connecté : la dernière lecture Spotify, ou le dernier fichier importé.
- Un fichier d'un autre service (chansons sans ID Spotify) reste la source, même avec Spotify connecté.
- À l'import d'un fichier, une chanson déjà lue sur Spotify garde l'artiste de l'album, la durée et la pochette : elle reste dans le même dossier quelle que soit la source.
- Library affiche sous « Next sync » : « Checked {date}, playlists from Spotify. » ou « …, playlists from {fichier}. »
- Un seul bouton « Sync » : il fait d'abord le Check (lecture des playlists, comparaison avec les fichiers), puis la fenêtre « Sync library? » montre ce qu'il va faire : « Downloads {n} songs. Corrects {n} songs (wrong length). Moves {n} songs. Removes {n} songs no longer in playlists. Cleans {n} duplicates. », seulement les parties non nulles, sinon « Everything up to date. ». Sans rien de téléchargé : « Click Sync to see what will be downloaded. »
- Une chanson dont seule une autre durée a été trouvée garde son fichier et apparaît dans Not found : « Only found in another length: {durée du fichier} instead of {durée Spotify}. » Choose la remplace (l'ancien fichier va à la Corbeille, ou reste si le téléchargement échoue). Un choix fait à la main n'est jamais remplacé par la vérification de durée.
- Not found → Choose → « Ignore this song » : la chanson n'est plus téléchargée par Sync. Onglet « Ignored » (« Not downloaded by Sync. ») avec « Don't ignore ».

### Export de données Spotify (deuxième option)
Proposé aussi : gratuit, sans Premium. Un bouton ouvre la page de ton compte Spotify, tu cliques sur « Demander », Spotify envoie un e-mail quand c'est prêt (jusqu'à 30 jours, en général quelques jours). L'app repère le zip dans Téléchargements et fait le reste.

## 10. Playlists d'autres personnes

Un seul comportement, avec ou sans Premium :
- **téléchargement seulement**. Elles n'apparaissent ni dans « Sort from », ni dans « Sort into ». Spotify ne permet pas d'écrire dans la playlist d'une autre personne ;
- absentes de « All my playlists », cochables dans « Choose playlists », avec la mention « From another user » ;
- **TuneMyMusic n'exporte que 500 chansons** des playlists d'autres personnes. Le guide TuneMyMusic le dit avant l'export (point 9). Sans Premium, l'app ne connaît pas le propriétaire : toute playlist d'exactement 500 chansons est signalée « May be incomplete. TuneMyMusic exports 500 songs max from playlists of other users. »

## 11. Sur tes appareils

- **Mac → iPhone** (fait) : l'app met à jour Apple Music après chaque Sync, avec les dossiers de playlists (dossier par défaut « Music Sorter »). Texte : « With an Apple Music or iTunes Match subscription, turn on Sync Library on the Mac and the iPhone. New songs arrive by themselves. »
- **Windows → iPhone** (choisi le 2026-10-20) : par **iTunes pour Windows**, piloté par COM (pywin32), comme Apple Music sur Mac. L'app Apple Music pour Windows ne peut ni importer de playlists ni être pilotée par script (testé par la session Windows).
  - après chaque Sync : chansons ajoutées à iTunes (sans copie), emplacement mis à jour après un déplacement, playlists vidées et remplies dans l'ordre, rangées dans leur dossier, chansons retirées enlevées d'iTunes ;
  - installer iTunes depuis le Microsoft Store et l'ouvrir une fois (licence à accepter). Ne pas installer Apple Music ni Apple Devices : ils retirent la musique à iTunes ;
  - l'iPhone se synchronise par iTunes (USB ou « Sync with this iPhone over Wi-Fi »).
- **Windows ou Mac → Android** : Syncthing synchronise le dossier musique en Wi-Fi, en arrière-plan, après un appairage à faire une fois. Poweramp lit les `.m3u8`. L'app guide l'installation.
- Windows se teste sur ton PC, dans la session Claude Code ouverte là-bas.

## 12. Ce qui reste comme aujourd'hui

- Config locale dans `data/config.json`, réglable depuis l'interface, aucun ID en dur.
- Protection du quota Spotify et cache.
- Import de fichiers existants.
- Dossiers de playlists pour Apple Music et les `.m3u8` (Settings).
- Library : « Find downloads here: <chemin> ».

## 13. Livraison

Le travail se fait en local sur la branche `music-sorter`. Une fois tout fini, elle est fusionnée dans `main` et poussée. Rien n'est poussé avant.
