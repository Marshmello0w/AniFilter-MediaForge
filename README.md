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
- `AniFilter-MediaForge-1.0.0.mfmod` – gepackte Moduldatei
- `INSTALLATION.txt` – kurze Installationsanleitung
- `SHA256SUMS.txt` – Prüfsumme der `.mfmod`-Datei
- `tests/` – Parser-, Filter-, Release- und Neustarttests

## Datenschutz und Quellen

Das Modul liest öffentliche Katalog- und Metadaten von AniWorld. Es erweitert
MediaForges eingebauten AniWorld-Provider nicht und führt keine TMDB-Abfragen
durch. Queue, Auto-Sync, Benutzerrechte und Altersgrenzen bleiben MediaForge-
Funktionen.

