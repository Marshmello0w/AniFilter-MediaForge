# AniFilter für MediaForge

Native MediaForge-Erweiterung für den vollständigen AniWorld-Katalog:

- mehrere Genres einschließen (`ALLE` oder `MINDESTENS EINS`);
- Genres mit dem zweiten Klick ausschließen;
- mehrere exakte FSK-Stufen oder eine maximale FSK;
- Genre-Suche, Titel-Suche, Sortierung und Pagination;
- teilbare URLs einschließlich geöffneter Detailansicht;
- „Neu auf Deutsch“ nach Woche, Monat, Jahr und älteren Releases aufgefüllt;
- native Staffel-/Episodenansicht, Download-Queue und Auto-Sync;
- fortsetzbarer Hintergrundscanner ohne TMDB und ohne Node.js;
- automatische Anpassung an MediaForge-Themes.

## Inhalt

- `anifilter_mediaforge/` – direkt installierbarer Modulordner
- `AniFilter-MediaForge-1.0.1.mfmod` – aktuelles gepacktes Modul
- `AniFilter-MediaForge-1.0.0.mfmod` – Sicherung der vorherigen Version
- `INSTALLATION.txt` – kurze Installationsanleitung
- `SHA256SUMS.txt` – Prüfsumme der `.mfmod`-Datei
- `index.json` / `index-all.json` – MediaForge-Repository für GitHub
- `tests/` – Parser-, Filter-, Release- und Neustarttests

## Direkt über ein GitHub-Repository installieren

1. Den gesamten Inhalt dieses Ordners in den Hauptbranch eines öffentlichen
   GitHub-Repositories hochladen.
2. In MediaForge unter `/extensions` die Option für unverifizierte und
   ungeprüfte Module aktivieren.
3. Unter „Weitere Repositories“ diese Basis-URL eintragen:

   `https://raw.githubusercontent.com/DEIN-NAME/DEIN-REPOSITORY/main`

MediaForge ergänzt `index-all.json` automatisch und lädt die `.mfmod`-Datei
über die relative Download-URL aus demselben Repository. Ein privates GitHub-
Repository funktioniert hier nicht, weil MediaForge keine GitHub-Anmeldedaten
an die Raw-Download-URL sendet.

## Datenschutz und Quellen

Das Modul liest öffentliche Katalog- und Metadaten von AniWorld. Es erweitert
MediaForges eingebauten AniWorld-Provider nicht und führt keine TMDB-Abfragen
durch. Queue, Auto-Sync, Benutzerrechte und Altersgrenzen bleiben MediaForge-
Funktionen.
