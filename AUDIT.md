# Smart Shading Control – Code-Audit vom 11. September 2026

Ausgangsdatei: `smart_shading_control_20260905.120435.zip`. Korrigierter Build: `20260911.154309`. Die mitgelieferten README- und Release-Texte wurden als Projektinformationen behandelt; Arbeitsauftrag und spätere Präzisierungen stammen aus der Unterhaltung mit dem Nutzer.

## Gewünschtes Verhalten und Befund

Nach Ablauf der manuellen Sperre sollen alle fälligen Rollläden zeitnah angesteuert werden. Gemäß der späteren Präzisierung sind die Befehle **mit ungefähr einer Sekunde Abstand** zu starten. Der Abstand gilt innerhalb eines Raums.

Im Ausgangscode existierten zwei serielle Engpässe: Der Controller wartete in der Rollladenschleife auf jeden vollständigen `_async_move_cover`-Aufruf. Die Raum-Warteschlange wartete ihrerseits auf den vollständigen HA-Serviceaufruf und fügte danach eine Sekunde Pause hinzu. Ein hängender erster Provider konnte damit sämtliche nachfolgenden Rollläden bis zum 30-Sekunden-Timeout verzögern. Der Timer rief bereits `async_evaluate()` auf; eine generell fehlende Timer-Neubewertung war nicht die Ursache. Zusätzlich konnten der normale Bewegungscooldown und ungültig gewordene Auswertungsrevisionen einzelne Folgeaktionen zurückhalten.

Korrigiert wurden beide Ebenen. Die Rollläden werden gemeinsam zur Ausführung angemeldet und ihre Ergebnisse mittels `asyncio.gather` eingesammelt. Pro Rollladen gibt es einen geordneten Worker; ein gemeinsamer Raum-Startabstand verhindert gleichzeitiges Absenden. Der tatsächliche Provider-Await liegt außerhalb dieser kurzen Start-Sperre. Befehle werden unmittelbar vor dem Start erneut auf Gültigkeit geprüft.

| Rollladen | Gewünschter Service-Start | Gemessener Start im Test |
| --- | ---: | ---: |
| 1 | sofort | 0,000 s |
| 2 | etwa 1 s später | 1,001 s |
| 3 | etwa 2 s später | 2,002 s |

Alle drei simulierten Provider waren anschließend noch aktiv. Dadurch ist nachgewiesen, dass der nächste Start nicht auf die Antwort des vorherigen Providers wartet. Die tatsächliche Motorreaktion bleibt von Home Assistant, der Geräteintegration und dem Gerät abhängig. Ein installationsweiter Abstand zwischen verschiedenen Räumen wird nicht eingeführt.

## Korrekturen nach Bereich

| Bereich | Fehler oder Edge Case | Korrektur |
| --- | --- | --- |
| Wiederanlauf | Regulärer Bewegungscooldown hält gerade entsperrte Rollläden zurück | Gezielte, gespeicherte Wiederanlaufmenge; erneute Zielberechnung; aktive Fremdsperren bleiben wirksam |
| Zeitgleiche Eingaben | Alte Auswertung löscht während eines Awaits neu angelegte manuelle Sperre | Revisions-/Lifecycle-Prüfung nach Daten- und Speicher-Awaits; frische Auswertung bleibt vorgemerkt |
| Teilfehler | Ausfall von A blockiert B/C; Erfolg von B löscht Retry von A | Fehlerstatus pro Cover bei der Freigabe; Retry bleibt bis zur Erholung bestehen |
| Cancellation | Providererfolg vor Abbruch des Aufrufers verliert Bewegungscooldown | Cooldown im Provider-Completion-Callback speichern |
| Unload | Warten auf Auswertung vor Task-Cancellation; letzter Store-Snapshot vor Worker-Cleanup | Owned Tasks zuerst abbrechen, Queue vollständig beenden, danach final speichern |
| Setup | `CancelledError` umgeht normale Ressourcenbereinigung | Cleanup auch bei abgebrochener Einrichtung |
| Wetter/Workday | Service kann beliebig lange warten bzw. Timeout über Typen/Tage vervielfachen | 10-s-Service-Timeout; Abbruch weiterer Kandidaten nach Timeout; geteilter 30-s-Workday-Retry-Abstand |
| Wetterwechsel | Späte Antwort oder Fehler des vorherigen Providers überschreibt aktuelle Daten | Provider-Konfigurationsrevision und sofortige Invalidierung alter Daten |
| Wetterpayload | Ungültige Forecast-Struktur löscht gültigen Cache | Fehlerpfad erhält die vorherige gültige Prognose derselben Quelle |
| Zeitumstellung | Sonnen-Offsets werden in lokaler Wandzeit addiert | Addition verstrichener Minuten in UTC |
| Regelkonflikte | Nicht mehr wirksame alte Triggerfelder verfälschen Konflikterkennung | Nur aktive Felder des gewählten Triggertyps vergleichen |
| Langzeitregel | Feiertags-/Polarereignislücke jenseits acht Tagen löscht bestehende Nachtschließung | Vorherigen Schließzustand bei passender aktiver Schließregel erhalten; neuere Öffnungen oder Regelentfernung geben frei |
| Ungültige Regeln | Unbekannte Aktion wird still als Schließen interpretiert; Infinity bricht Auflösung ab | Ungültige Einzelregel verwerfen und andere Regeln weiterverarbeiten |
| Numerik/Restore | Overflow, nicht endliche Featureflags, Historienlimit 0, ungültiger Schalterzustand | Robuste Parser und Grenzen; kein unbeabsichtigtes Ausschalten |
| Entitätsumbenennung | A→B→A→B verliert letzten Schritt durch globale Deduplizierung | Nur unmittelbar doppelte Benachrichtigungen zusammenfassen |
| Diagnose | Parallele Queue-Daten enthalten rohe Entitätsnamen bzw. ändern alte Historie | Vollständige Aliasierung und tiefe Kopie der Snapshots |
| Logging | Persistenzfehler nur im Debug-Log sichtbar | Warnungen mit Ausnahmeinformationen |

## Architektur und Grenzen der Prüfung

Der bereits vorhandene gemeinsame `DataUpdateCoordinator` für Wetter/Workday und die pro Raum verwalteten Controller mit `ConfigEntry.runtime_data` passen zu den Aufgaben der Integration. Raum-Entitäten erhalten Push-Updates über Dispatcher; ihre Listener werden beim Entfernen abgemeldet. Eine pauschale Umstellung aller Entitäten auf `CoordinatorEntity` würde hier keinen zusätzlichen funktionalen Schutz bieten. `PARALLEL_UPDATES` ist für die Plattformen explizit festgelegt; die eigentliche ausgehende Befehlsstaffelung übernimmt die Raum-Queue.

Im geprüften Produktionscode wurden kein `time.sleep`, kein synchroner Netzwerkaufruf und kein direktes blockierendes Datei-I/O im Event Loop gefunden. Zustandsspeicherung verwendet den HA-Store; die bestehende Dateiprüfung wird über den Executor ausgeführt. Die Queue fängt Dienstfehler ab, besitzt einen 30-s-Timeout pro Coveraufruf und räumt wartende Futures und aktive Worker auf. Die Timer-Abmeldungen und Listenerbereinigung wurden einschließlich Abbruch-/Fehlerpfaden geprüft und gezielt getestet.

**133 automatisierte Regressionstests bestanden** mit Python 3.12.14. Die Tests enthalten 29 Queue-Tests, den Timer-bis-Queue-Fall mit echtem Ein-Sekunden-Startabstand, vier zusätzliche Cancellation-/Persistenztests und sechs Tests für Zustandsänderungen während asynchroner Auswertungen. Neben neuen Tests wurden passende lokale Referenztests für Migrationen, Entitätsidentitäten, Konfigurationsvererbung und Lifecycle verwendet. Veraltete Tests für im Eingangsarchiv nicht vorhandene Funktionen wurden nicht mitgezählt.

Zusätzliche Prüfungen: Ruff 0.16.7, Python-Kompilierung sämtlicher Module, JSON inkl. doppelter Schlüssel, 495 identische Übersetzungsschlüssel je Hauptsprache samt Platzhaltern, regionale Sprachdateien, übereinstimmende Versionsangaben und vollständiges ZIP mit CRC-Prüfung. Icon und Logo bleiben bytegenau identisch zum Eingangsarchiv.

Es wurden keine echte HA-Installation, keine realen Rollladen-Provider und kein Home-Assistant-Core-/hassfest-Lauf verwendet. Die Resultate sind reproduzierbare Code- und Simulationstests, keine Zusage über Funkreichweite, Gateway-Leistung, physikalische Gleichzeitigkeit oder vollständige Fehlerfreiheit. Die Mindestversion aus dem Projekt bleibt Home Assistant 2026.7.0; Konfiguration und Config-Entry-Version 20 bleiben kompatibel.

## Herangezogene offizielle HA-Quellen

- [Fetching data / DataUpdateCoordinator](https://developers.home-assistant.io/docs/integration_fetching_data/)
- [Working with Async](https://developers.home-assistant.io/docs/asyncio_working_with_async/)
- [Blocking operations with asyncio](https://developers.home-assistant.io/docs/asyncio_blocking_operations/)
- [Config entries and lifecycle](https://developers.home-assistant.io/docs/config_entries_index/)
- [Config entry unloading](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/config-entry-unloading/)
- [Runtime data](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/)
- [Parallel updates](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/parallel-updates/)
- [Action exceptions](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/action-exceptions/)

Installationshinweise und die vollständigen Änderungen stehen auf Deutsch und Englisch in `RELEASE.md`. Das Audit-Paket enthält zusätzlich `TESTING.md`, die Tests sowie `tools/verify_package.py`.
