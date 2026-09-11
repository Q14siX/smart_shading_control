<p align="center">
  <img src="https://raw.githubusercontent.com/Q14siX/smart_shading_control/main/custom_components/smart_shading_control/brand/icon.png" alt="Smart Shading Control Icon">
</p>

# Smart Shading Control – Release Notes

## `20260911.154309` – Gestaffelter Wiederanlauf und Async-Audit / Staggered Resumption and Async Audit

**Datum / Date:** 11. September 2026 / 11 September 2026  
**Build:** Audit-Korrektur auf Basis von `20260905.120435` / Audit fix based on `20260905.120435`  
**Mindestversion / Minimum Home Assistant:** 2026.7.0  
**Config-Entry-Version / Config Entry version:** 20, unverändert / unchanged

### Deutsch

#### Rollläden nach Ablauf der manuellen Sperre

Der Controller wartete bisher in einer Schleife auf jeden einzelnen Rollladen. Zusätzlich führte die Raum-Warteschlange erst nach Abschluss eines Provideraufrufs und einer weiteren Pause den nächsten aus. Ein langsamer oder hängender erster Serviceaufruf konnte dadurch die übrigen Rollläden bis zu seinem Timeout zurückhalten. Eine reine Änderung an nur einer dieser beiden Stellen hätte den Engpass nicht beseitigt.

Die neue Ausführung bereitet alle betroffenen Rollläden gemeinsam vor und wartet ihre Ergebnisse asynchron ab. **Zwischen den Service-Starts innerhalb eines Raums bleibt mindestens eine Sekunde Abstand.** Bei drei Rollläden starten die Aufrufe typischerweise bei **0 / 1 / 2 Sekunden**, auch wenn der erste Provider noch antwortet. Befehle für denselben physischen Rollladen bleiben zusätzlich nacheinander geordnet. Die Staffelung gilt auch für manuelle Gruppenfahrten, STOP, Lamellen und Kontaktaktionen.

Nach Ablauf einer Sperre werden alle fälligen Entitäten neu bewertet. Ihr gezielter Wiederanlauf wird nicht erneut vom normalen Mindestfahrintervall zurückgehalten; noch laufende individuelle Sperren und Schutzprüfungen bleiben wirksam. Wiederanlaufbedarf wird bis zur Annahme bzw. Erreichung des aktuellen Ziels vorgehalten und für einen Neustart gespeichert. Während der Pause ersetzte, abgebrochene oder inzwischen ungültige Befehle erreichen den Provider nicht.

#### Weitere Fehlerkorrekturen

- **Veraltete Auswertungen:** Nach asynchronen Datenabfragen und Speichervorgängen wird die Eingaberevision erneut geprüft. Eine zwischenzeitlich neu gesetzte manuelle Sperre kann nicht mehr durch eine ältere Zeitregelauswertung entfernt werden. Notwendige Neubewertungen bleiben vorgemerkt.
- **Fehler einzelner Rollläden:** Der Wiederholungsabstand eines fehlgeschlagenen Rollladens sperrt keine anderen gesunden Rollläden. Ein Erfolg auf einem anderen Rollladen entfernt dessen ausstehenden Wiederholungsversuch nicht.
- **Entladen und Cancellation:** Laufende Controller-Aufgaben werden vor dem Warten auf die Auswertung beendet. Anschließend werden alle Queue-Worker und Completion-Callbacks abgearbeitet, bevor der letzte Zustand gespeichert wird. Abgebrochene Befehle hinterlassen dadurch keine veralteten Befehlsmarker im Neustartzustand. Bestätigte automatische Bewegungen speichern ihren Cooldown bereits im Completion-Callback. Auch eine abgebrochene Einrichtung räumt ihre Ressourcen auf.
- **Wetter und Arbeitstage:** Serviceaufrufe besitzen ein Timeout von zehn Sekunden. Ein Timeout vervielfacht sich nicht mehr über weitere Forecast-Typen bzw. Kalendertage. Fehlgeschlagene Workday-Abfragen erhalten einen gemeinsam genutzten Wiederholungsabstand von 30 Sekunden. Verspätete Antworten eines vorherigen Wetterproviders werden verworfen; strukturell ungültige Antworten löschen keine zuvor gültige Prognose.
- **Zeitregeln:** Sonnen-Offsets verwenden tatsächlich verstrichene Minuten über Sommer-/Winterzeitwechsel hinweg. Die Konflikterkennung vergleicht nur wirksame Triggerfelder. Beschädigte Regeln werden isoliert verworfen. Eine bestehende Nachtschließung geht bei Feiertags- oder Polarnachtlücken jenseits des historischen Suchfensters nicht verloren, solange eine passende aktive Schließregel besteht; neuere Öffnungen und entfernte Regeln geben sie weiterhin frei.
- **Restore, Eingaben und Diagnose:** Ungültige gespeicherte Schalterzustände werden nicht als ausdrückliches Ausschalten interpretiert. Nicht endliche Zahlen und Überläufe werden abgefangen. Entitätsumbenennungen über eine Rückumbenennung hinweg behalten ihre richtige Reihenfolge. Warteschlangendaten in der Entscheidungshistorie bleiben unveränderlich und auch bei mehreren aktiven Befehlen anonymisiert. Schreibfehler der Zustandsspeicherung werden als Warnung protokolliert. Die Standard-Sonnenentität wird auch bei leerem alten Konfigurationseintrag beobachtet.

#### Prüfung und Installation

**133 automatisierte Regressionstests bestanden** mit Python 3.12.14. Die Tests verwenden produktive Module bzw. gezielt ausgeführte produktive Controllermethoden mit simulierter Home-Assistant-Ein-/Ausgabe. Sie prüfen unter anderem den Weg vom abgelaufenen Sperr-Timer zur Queue, den echten Ein-Sekunden-Startabstand, fehlgeschlagene und hängende Provider, Re-Trigger, Cancellation, Entladen, Zeitumstellungen und Migrationen. Eine Messung mit noch blockierten Providern ergab Starts bei **0,000 / 1,001 / 2,002 Sekunden**.

Zusätzlich geprüft: Ruff, Python-Syntax, alle JSON-Dateien, gleiche Sprachschlüssel und Platzhalter, Versionsgleichheit, ZIP-Struktur und unveränderte Originalgrafiken. **Ein Live-Test mit Home Assistant 2026.7+ und realen Rollläden war hier nicht verfügbar.** Die gemessenen Zeiten beschreiben Service-Starts der Integration, nicht garantierte Motorlaufzeiten; zugrunde liegende HA-Integrationen können weitere Verzögerungen verursachen. Die Pause wird je Raum verwaltet.

Das Installations-ZIP enthält die vollständige Integration unter `custom_components/smart_shading_control/`, beide Sprachvarianten, Grafiken, Manifest, Lizenz, HACS-Metadaten und Dokumentation. Den bestehenden Komponentenordner ersetzen und Home Assistant neu starten; eine neue Einrichtung ist nicht erforderlich. Bestehende Konfigurationen bleiben kompatibel. Das zusätzliche Audit-Paket enthält dieselben Dateien sowie Tests und Prüfskript. Historische Prüfaussagen in älteren Release-Abschnitten beziehen sich ausschließlich auf den jeweils damaligen Build.

### English

#### Covers after a manual override expires

The controller previously awaited each cover in a loop. In addition, the room queue started the next command only after the previous provider call had completed and an additional pause had elapsed. A slow or stalled first service call could therefore hold back every other cover until its timeout. Changing only one of these two layers would not have removed the bottleneck.

The new implementation prepares all affected covers together and awaits their results asynchronously. **Service starts within a room remain at least one second apart.** For three covers, calls typically start at **0 / 1 / 2 seconds**, even while the first provider is still responding. Commands to the same physical cover also remain ordered. Pacing applies to manual group movement, STOP, tilt and contact actions as well.

When an override expires, all due entities are reevaluated. Their targeted resumption is not held back again by the ordinary movement cooldown; active individual overrides and protection checks remain effective. Resumption intent is retained until the current target is accepted or reached and is stored for restart recovery. Commands that are superseded, cancelled or invalidated during the pause do not reach the provider.

#### Additional fixes

- **Stale evaluations:** The input revision is checked again after asynchronous data requests and persistence. An older time-rule evaluation can no longer remove a manual override created while it was waiting. Required reevaluations remain pending.
- **Individual cover failures:** A failed cover's retry delay does not block healthy covers. Success on another cover does not remove the outstanding retry for the failed one.
- **Unload and cancellation:** Owned controller tasks are cancelled before waiting for evaluation to end. All queue workers and completion callbacks are then drained before the final state is saved. Interrupted commands therefore leave no stale command markers in restart storage. Confirmed automatic movements record their cooldown in the completion callback. Cancelled setup also cleans up its resources.
- **Weather and workdays:** Service calls have a ten-second timeout. A timeout no longer multiplies across additional forecast types or calendar dates. Failed Workday requests use a shared 30-second retry delay. Late responses from an earlier weather provider are discarded; malformed responses do not erase a previously valid forecast.
- **Time rules:** Solar offsets use elapsed minutes across daylight-saving transitions. Conflict detection compares only effective trigger fields. Malformed rules are rejected individually. An existing scheduled closure is retained across holiday or polar-event gaps beyond the historical search window while a matching enabled close rule remains; newer open events and removed rules still release it.
- **Restore, inputs and diagnostics:** Invalid restored switch states are not interpreted as an explicit switch-off. Non-finite values and numeric overflow are handled. Entity rename chains retain their order across reversals. Decision history keeps immutable queue snapshots and anonymizes multiple active commands. State persistence failures are logged as warnings. The default sun entity is monitored even when an older configuration contains an empty source.

#### Validation and installation

**133 automated regression tests passed** using Python 3.12.14. Tests execute production modules or focused production controller methods with simulated Home Assistant I/O. They cover the expired-override timer-to-queue path, actual one-second start spacing, failing and stalled providers, retriggers, cancellation, unload, daylight-saving transitions and migrations. With providers deliberately held open, measured starts were **0.000 / 1.001 / 2.002 seconds**.

Also verified: Ruff, Python syntax, all JSON files, matching translation keys and placeholders, consistent versions, ZIP layout and unchanged original graphics. **A live test with Home Assistant 2026.7+ and physical covers was not available here.** Measured timing describes integration service starts, not guaranteed motor movement; underlying HA integrations may add delays. Pacing is managed per room.

The installation ZIP includes the complete integration under `custom_components/smart_shading_control/`, translations, graphics, manifest, license, HACS metadata and documentation. Replace the existing component directory and restart Home Assistant; no new configuration is required. Existing configuration remains compatible. The additional audit bundle includes the same files plus tests and a verification script. Historical validation statements in older release sections apply only to their respective builds.

---

## `20260905.120435` – Plausibler Hitzeschutz und gesicherte Nachtpriorität / Solar-aware Heat Protection and Preserved Night Priority

**Veröffentlichung / Release date:** 5. September 2026 / 5 September 2026  
**Release-Kanal / Release channel:** Stable  
**Mindestversion / Minimum Home Assistant:** 2026.7.0  
**Config-Entry-Version / Config Entry version:** 20

### Deutsch

#### Fehlerkorrekturen und neue Hitzebewertung

- **Zentrale Datenquellen:** Raumcontroller übernehmen wieder sämtliche gebäudeweiten Quellen, insbesondere Wetter, Außentemperatur, Einstrahlung und Helligkeit. Diese vier Einträge fehlten in der bisherigen Liste der weitergereichten globalen Schlüssel. Veraltete raumlokale Quellkopien können aktuelle zentrale Quellen nicht mehr verdecken; entfernte optionale Quellen werden nicht wieder aktiviert.
- **Solare Freigabe vor Temperaturstufe:** Hohe Raumtemperatur und Prognosewerte allein lösen keine Beschattung mehr aus. Eine separate, quellenspezifische Freigabe verlangt ausreichende aktuelle Einstrahlung auf der jeweiligen Fassade. Starker Hitzeschutz benötigt zusätzlich die stärkere solare Freigabe; eine temperaturabhängige Hochstufung kann diese Prüfung nicht umgehen.
- **Regen, Bewölkung und Lux:** Regen, Nebel und bedeckte Bedingungen werden nicht mehr durch einen Helligkeitssensor oder einen widersprüchlichen Bewölkungswert ausgehebelt. Fehlende Wetterinformationen erzeugen keinen pauschalen Sonnenfaktor. Ein gültiger Einstrahlungsmesswert bleibt als tatsächlicher Energiemesswert von einer Lux-/Wetterschätzung unterscheidbar und kann bei hoher Strahlung auch mit kühler Außenluft Beschattung begründen.
- **Fassaden, Temperaturdifferenz und Verlauf:** Vertikale Fassaden verwenden den passenden Höhenwinkelanteil statt der bisherigen Sinusgewichtung. Das Risiko wird pro Fassade berechnet. Kühlere Außenluft und beobachtetes Abkühlen senken den Risikowert, ohne eine nicht nachgewiesene Lüftung anzunehmen. Getrennte Ein-/Ausstiegsschwellen für Strahlung und eine Temperaturhysterese verhindern unnötige Wechsel; die bestehende Risikohysterese und Fahrbegrenzung bleiben erhalten.
- **Ungültige oder alte Daten:** Nicht verwertbare Messwerte werden nicht durch erfundenen Sonnenschein ersetzt. Solarmessungen werden auf gültige Einheiten, endliche Werte, Wiederherstellungskennzeichen und Aktualität geprüft. Die Tagesdynamik hält bei fehlenden notwendigen Daten die Position. Auch Zahlenüberläufe bei kW/m²- und klx-Umrechnungen werden abgefangen.

#### Nachtsteuerung und Bestandsschutz

Die Nachtsteuerung bleibt der Tagesdynamik übergeordnet. Nachlassende Einstrahlung, Regen oder fallende Raumtemperaturen können eine aktive Nacht-Schließregel nicht durch ein dynamisches Öffnungsziel ersetzen. Zusätzlich wurde ein reproduzierbarer Wiederanlauffehler korrigiert: Ein noch gespeicherter Wiederholungsauftrag einer älteren Öffnungsregel konnte nach einem Ausfall eine inzwischen wirksame neuere Schließregel überschreiben. Solche überholten Öffnungsaufträge werden jetzt vor der Zielübergabe entfernt und die Bereinigung wird gespeichert.

Die Zuordnung von Kontakten zu einzelnen Rollläden, die verzögerte Nachholung einer freigegebenen Nachtschließung, manuelle Sperren samt ursprünglichen Ablaufzeitpunkten, bestehende Betriebsarten und die eigenständigen Wetter-/Frostschutzfunktionen bleiben erhalten. Eine ausdrücklich gewählte feste Betriebsart „Hitzeschutz“ bleibt eine feste Position und ist nicht mit der automatischen Einstrahlungsbewertung gleichgesetzt.

#### Diagnose, Paket und Prüfung

Entscheidungsgrund, Hitzerisiko und Sonnenlast erhalten nachvollziehbare Attribute mit Messquelle, Mess-/Wetterwerten, Temperaturdifferenz und Fassadenbewertung. Neue Entscheidungsgründe für fehlenden solaren Wärmeeintrag und Halten wegen fehlender Daten sind vollständig auf Deutsch und Englisch übersetzt, einschließlich der regionalen Sprachdateien. Die README beschreibt Ablauf, Grenzwerte und Grenzen des Modells in beiden Sprachen.

**134 gezielte automatisierte Tests bestanden.** Geprüft wurden unter anderem 17,7 °C außen / 25,6 °C innen bei Regen oder bedecktem Himmel, mit und ohne Luxsensor, echte Einstrahlung trotz kühler Außenluft, ungültige/veraltete Werte, Hysterese, Fassadentrennung, Prognose, Zeit- und Sonnenuntergangsregeln, Nachtpriorität, veraltete Öffnungswiederholungen, Neustart/Persistenz, manuelle Sperren aller drei Rollläden, mittlere/linke Kontaktzuordnung, Kontaktverzögerung, Sicherheitsprioritäten und Trockenlauf. Die produktiven Berechnungs- und Controllermethoden wurden mit simulierter Home-Assistant-Ein-/Ausgabe ausgeführt. Ein Live-Test in Home Assistant mit realen Rollläden war in dieser Umgebung nicht möglich.

Python-Syntax, JSON-Struktur, Sprachschlüssel-/Platzhalterkonsistenz, Versionsgleichheit und ZIP-Inhalt werden zusätzlich geprüft. Das vollständige Paket enthält keine Test-, Cache- oder Entwicklungsartefakte. Original-ICON und Original-LOGO bleiben bytegenau unverändert; ihre SHA-256-Prüfsummen stimmen mit den Referenzen überein. Vorhandene Konfiguration und gespeicherte Schutzzeiten bleiben kompatibel; eine Neueinrichtung ist nicht erforderlich.

### English

#### Fixes and revised heat assessment

- **Central input sources:** Room controllers once again inherit all building-wide sources, particularly weather, outside temperature, irradiance and illuminance. These four entries were absent from the previous list of forwarded global keys. Old room-local source copies can no longer hide current central sources, and removed optional sources are not revived.
- **Solar eligibility before temperature level:** A hot room or forecast alone no longer triggers shading. A separate source-aware gate requires sufficient current solar exposure on the specific facade. Strong heat protection requires stronger solar eligibility, and temperature-driven escalation cannot bypass that check.
- **Rain, clouds and lux:** Illuminance and contradictory cloud percentages no longer suppress evidence of rain, fog or overcast conditions. Missing weather does not create a default sunshine factor. A valid irradiance reading remains distinguishable from lux/weather estimates and may justify shading under high radiation even when outside air is cool.
- **Facades, temperature difference and trend:** Vertical facades use the appropriate elevation-angle component rather than the previous sine weighting. Risk is calculated per facade. Cooler outside air and observed room cooling reduce risk without assuming unverified ventilation. Separate radiation entry/exit thresholds and temperature hysteresis reduce switching; existing risk hysteresis and movement limits are retained.
- **Invalid or old data:** Unusable measurements are not replaced by invented sunshine. Solar measurements are checked for units, finite values, restored-state flags and reporting age. Missing necessary inputs hold the daytime position. Numeric overflow during kW/m² and klx conversion is also rejected.

#### Night control and existing protection

Night control retains priority over daytime dynamics. Reduced radiation, rain or falling room temperature cannot replace an active scheduled night closure with a dynamic opening target. A reproducible restart issue was also corrected: a persisted retry from an older opening rule could override a newer closing rule after an outage. Superseded opening retries are now removed before targets are submitted, and that cleanup is persisted.

Per-cover contact assignment, delayed night-close retry after contact clearance, manual overrides with their original deadlines, explicit operating modes and independent weather/frost safety functions are retained. Explicitly selecting the fixed “Heat protection” operating mode still requests its fixed position rather than enabling the automatic solar assessment.

#### Diagnostics, package and validation

Reason, heat-risk and solar-load sensors expose the selected source, measured/weather inputs, temperature difference and facade assessments. New reason codes for insufficient solar gain and holding because of missing data are translated in German and English, including regional locale files. The bilingual README documents the decision sequence, thresholds and model limitations.

**134 targeted automated tests passed.** Coverage includes 17.7 °C outside / 25.6 °C inside in rain or overcast conditions, with and without lux input, real irradiance with cool outside air, invalid/stale inputs, hysteresis, facade isolation, forecast, fixed-time and sunset schedules, night priority, obsolete opening retries, restart/persistence, manual locks for all three covers, middle/left contact assignment, contact delay, safety priorities and dry run. Production calculation and controller methods were executed with simulated Home Assistant I/O. A live Home Assistant test with physical covers was not available in this environment.

Python syntax, JSON structure, locale/placeholder consistency, matching versions and ZIP contents are checked separately. The complete package excludes test, cache and development artifacts. Original ICON and LOGO files are byte-for-byte unchanged and match their reference SHA-256 checksums. Existing configuration and persisted protection deadlines remain compatible; no new setup is required.

---

## `20260904.104856` – Unabhängige Gegenprüfung und Race-Korrekturen / Independent Adversarial Recheck and Race Corrections

**Veröffentlichungsdatum:** 4. September 2026  
**Release-Kanal:** Stable  
**Mindestversion Home Assistant:** 2026.7.0  
**Config-Entry-Version:** 20

Diese Version dokumentiert ausschließlich die zusätzlichen Befunde und Korrekturen des zweiten, unabhängig und gegenbeweisorientiert durchgeführten Prüfdurchlaufs auf Basis von `20260904.091706`.

---

## Deutsch

### Manuelle Bedienung, eigene Befehle und Neustart

- Eigene Command-Kontexte sind jetzt strikt dem konkreten physischen Rollladen zugeordnet. Ein Kontext von Rollladen A kann eine manuelle Fahrt von Rollladen B nicht mehr als automatische Rückmeldung maskieren.
- Ein kontextloser physischer STOP innerhalb des noch plausiblen Weges zu einem früheren SSC-Sollwert wird als manuelle Übernahme erkannt. Unerklärte Bewegungs- und Recovery-Zustände gelten nur noch dann als eigene Rückmeldung, wenn Richtung, Zielkorridor und tatsächliche Bewegungsindizien zusammenpassen.
- Bereits beim Start sichtbare Zustände `opening` und `closing` werden auch ohne messbare Positionsdifferenz vor der ersten Automatik ausgewertet. Eine gewöhnliche Startauswertung hält einen bereits fahrenden Rollladen; nur eine ausdrücklich erzwungene aktuelle Regel- oder Safety-Aktion darf eingreifen.
- Erreichte Pending-Ziele werden für positionierbare und binäre Cover vollständig bereinigt und erst nach Aktualisierung der Restart-Baseline gespeichert.
- Provisorische Context-, Ziel- und Suppression-Marker werden während des Provider-Aufrufs von konkurrierenden Store-Snapshots ausgeschlossen. Bestätigte Marker werden erst nach erfolgreichem blockierendem Service-Call persistiert; bei Fehlern werden sie vollständig zurückgerollt.
- Die Befehlswarteschlange besitzt nun einen idempotenten Abschluss-Callback vor der Future-Auflösung. Er läuft auch dann genau einmal, wenn der ursprüngliche Aufrufer nach `on_started` abgebrochen wurde, und bereinigt beziehungsweise persistiert STOP-, Vertikal- und Lamellenbefehle anhand des tatsächlichen Provider-Ergebnisses.

### Lifecycle, Reload und mehrere Instanzen

- Jeder geladene Raumcontroller arbeitet mit einem unveränderlichen Snapshot seiner Config-Entry-Optionen. Eine alte Controller-Generation kann während eines Reloads weder neue Optionen lesen noch den gemeinsam genutzten Wetter-Coordinator auf eine alte Quelle zurücksetzen oder dessen neue Prognose konsumieren.
- Controller-eigene Hintergrundtasks sowie extern gestartete Entity-Service- und bereits angelaufene Timer-/Start-Callbacks werden explizit verfolgt. `async_stop()` beendet und joint sie vor den finalen Store-Schreibvorgängen; auch nach einem fehlgeschlagenen Plattform-Unload und anschließender Entfernung kann kein alter Raumtask den gelöschten Store neu anlegen.
- Der Entity-Registry-Rename-Listener bleibt über Reload-Grenzen stabil, serialisiert verkettete Umbenennungen und wird bei der Entfernung ausdrücklich gelöst.
- Queue-Erzeugung und -Shutdown bleiben strikt auf die jeweilige Config-Entry-ID begrenzt. Das Entladen oder Entfernen eines Raums beeinflusst keine Warteschlange eines anderen Raums.

### Zeit, Persistenz und Migration

- Zeitregel-Fenster und Cursor rechnen über absolute UTC-Zeit. Die Rückstellung von Sommer- auf Winterzeit kann ein zehnminütiges Catch-up-Fenster nicht mehr unbeabsichtigt auf 70 Minuten erweitern.
- Zeitstempel an den Grenzen des Python-Datetime-Bereichs sowie numerische Überläufe in Persistenz- und Migrationsdaten werden kontrolliert abgewiesen, statt Setup oder Migration mit `OverflowError` abzubrechen.
- Die Suche nach von Home Assistant erzeugten `.corrupt.*`-Store-Backups maskiert Sonderzeichen des Konfigurationspfads korrekt und bleibt dadurch auch bei Pfaden mit Glob-Metazeichen fail-closed.
- Sämtliche älteren Raum- und Zentralregeln werden vor der Migration semantisch validiert. Unbekannte Enums, ungültige Bool-/Zeit-/Offset-/Prioritäts-/Positionswerte und fehlende Pflichtfelder blockieren die Migration ohne Mutation. Mehrdeutige raumweite Legacy-Kontakte werden nicht mehr still gelöscht; nur die eindeutig abbildbare Kombination aus genau einem Cover und einem Kontakt wird automatisch übernommen.

### Zusätzliche Verifikation

- **110 von 110** Regressionstests bestehen. Davon prüfen **44** Tests Restart/Persistenz, **12** die Queue einschließlich Abbruch und Instanzisolation sowie **8** die exakte Cover-Kontakt-Zuordnung einschließlich der Konstellationen mit ausschließlich mittlerem beziehungsweise linkem Kontakt.
- Syntax-/Bytecode-Prüfung, Vulture mit 80 Prozent Mindestkonfidenz, JSON-Parsing sowie Locale-, Placeholder-, Manifest- und Paketkonsistenz sind erfolgreich. Ruff ist für alle in diesem Durchlauf geänderten Produktions- und Testdateien ohne Befund.

---

## English

### Manual control, owned commands and restart

- Owned command contexts are now bound to the exact physical cover. A context belonging to cover A can no longer mask manual movement of cover B as automatic feedback.
- A context-free physical STOP inside the still-plausible path to an earlier SSC target is treated as manual takeover. Unexplained movement and recovery states count as owned feedback only when direction, target corridor and real movement evidence agree.
- Preloaded `opening` and `closing` states are reconciled before the first automatic evaluation even when no measurable position delta exists. An ordinary startup evaluation holds an already-moving cover; only an explicitly forced current rule or safety action may intervene.
- Reached pending targets are cleared completely for both position-capable and binary covers, and the restart baseline is updated before the cleanup is persisted.
- Provisional context, target and suppression markers are excluded from concurrent Store snapshots while the provider call is in flight. Confirmed markers are persisted only after the blocking service call succeeds; failures roll every provisional marker back.
- The command queue now has an idempotent completion callback that runs before waking the waiter. It executes exactly once even when the original submitter is cancelled after `on_started`, and it cleans up or persists STOP, vertical and tilt commands from the real provider outcome.

### Lifecycle, reload and multiple instances

- Each loaded room controller uses an immutable snapshot of its Config Entry options. During reload, an old controller generation can neither read new options nor roll the shared weather coordinator back to an old source or consume the new source's forecast.
- Controller-owned background tasks, externally initiated entity-service operations and already-running timer/start callbacks are tracked explicitly. `async_stop()` cancels and joins them before final Store writes, preventing an old room task from recreating a deleted Store after failed platform unload followed by removal.
- The Entity Registry rename listener remains stable across reload boundaries, serializes chained renames and is removed explicitly with the entry.
- Queue creation and shutdown remain scoped to the individual Config Entry ID. Unloading or removing one room does not affect another room's queue.

### Time, persistence and migration

- Time-rule windows and cursors now use absolute UTC arithmetic. The daylight-saving fall-back transition can no longer expand a ten-minute catch-up window to 70 minutes.
- Timestamps at Python datetime boundaries and numeric overflow in persisted or migration data are rejected safely instead of crashing setup or migration with `OverflowError`.
- Home Assistant `.corrupt.*` Store-backup discovery now escapes configuration-path metacharacters, preserving fail-closed behavior even when a path contains glob syntax.
- Every older room and central rule is semantically validated before migration. Unknown enums, invalid boolean/time/offset/priority/position values and missing required fields block migration without mutation. Ambiguous room-wide legacy contacts are no longer silently deleted; automatic conversion is limited to the unambiguous one-cover/one-contact case.

### Additional validation

- **110 of 110** regression tests pass: **44** cover restart/persistence, **12** cover queue cancellation and instance isolation, and **8** exact cover/contact assignment including middle-only and left-only contact layouts.
- Syntax/bytecode checks, Vulture at 80 percent confidence, JSON parsing, locale/placeholder checks, manifest consistency and package checks pass. Ruff reports no finding in any production or test file changed by this recheck.

---

## `20260904.091706` – Restart-, Persistenz- und Lifecycle-Korrekturen / Restart, Persistence and Lifecycle Corrections

**Veröffentlichungsdatum:** 4. September 2026  
**Release-Kanal:** Stable  
**Mindestversion Home Assistant:** 2026.7.0  
**Config-Entry-Version:** 20

Diese Version folgt auf eine vollständige, modulübergreifende Prüfung der Integration. Der Schwerpunkt lag auf manuellen Sperren, der Unterscheidung eigener und externer Fahrten, Restart-/Reload-Verhalten, mehreren Rollläden pro Raum, persistenten Zeit- und Wetterschutzzuständen sowie dem Home-Assistant-Lifecycle.

---

## Deutsch

### Manuelle Bedienung und mehrere Rollläden

- Manuelle Sperren werden nicht mehr optional, sondern immer pro Rollladen mit ihrem absoluten Ablaufzeitpunkt gespeichert.
- Nach einem Restart oder Reload gilt nur die ursprüngliche Restlaufzeit weiter. Abgelaufene Sperren werden verworfen; die konfigurierte Dauer beginnt nicht erneut.
- Für eine manuelle Gruppenfahrt werden die Sperren aller ausgewählten Rollläden vor dem ersten Provider-Aufruf reserviert. Eine eigene Transaktionsrevision verhindert, dass gewöhnliche Sensor- oder Minutenereignisse die Fahrt nach dem ersten Listeneintrag abbrechen.
- Fehlgeschlagene oder nicht verfügbare Rollläden werden einzeln auf ihren vorherigen Sperrzustand zurückgesetzt; erfolgreiche beziehungsweise bereits am Ziel befindliche Rollläden behalten ihre eigene Sperre.
- Explizit externe Home-Assistant-Kontexte werden vor Ziel- und Grace-Heuristiken als manuell erkannt. Vertikale Position und Lamellenposition werden getrennt behandelt; ein Überschießen eines eigenen Sollwerts gilt als neue manuelle Absicht.
- Bei einem aktiven Schutz mit Sicherheitsposition werden manuelle Positionsanforderungen in die unsichere Richtung begrenzt. Eine Bewegung in die sicherere Richtung bleibt möglich; die Frost-Aktion **Automatik blockieren** betrifft weiterhin nur Automatikfahrten. Ein ausdrücklicher manueller STOP bleibt ein unmittelbarer Benutzer- beziehungsweise Notstopp.

### Restart-, Reload- und Persistenzverhalten

- Beide raumbezogenen Home-Assistant-Stores werden mit atomaren Schreibvorgängen verwendet und vor dem Start der Plattformen sowie vor der ersten Automatik-Auswertung geladen.
- Beschädigte, nicht lesbare oder für aktive Schutzfelder semantisch ungültige persistente Daten führen zu `ConfigEntryNotReady`. Der Raum startet nicht still mit leeren Schutzwerten. Auch von Home Assistant umbenannte `.corrupt.*`-Dateien werden über nachfolgende Setup-Versuche hinweg berücksichtigt.
- Persistiert werden unter anderem Enable-/Betriebsmodus, per-Cover-Sperrfristen, Mindestfahrabstände, letzte bekannte Vertikal- und Lamellenpositionen, eigene Command-/Context-Kennzeichen, begrenzte Pending-Sollwerte, Zeitregel-Cursor und -Zustände, Wetter-Schutztimer sowie Provider-Retry-Frist und Backoff-Stufe.
- Ein eigener absoluter Ablauf-Timer entfernt Sperren pünktlich; jeder Rollladen besitzt seinen eigenen Eintrag. Temporäre Sperren bleiben zusätzlich auf den nächsten lokalen Tageswechsel begrenzt.
- Ein kurzlebiger Pending-Sollwert von höchstens 15 Minuten kann nach einem Restart noch erkennen, dass ein vor dem Stop angenommener eigener Befehl während der Downtime abgeschlossen wurde. Unerklärte Positions- oder Lamellenänderungen werden dagegen als manuell geschützt.
- Bereits vor der Listenerregistrierung verfügbare Cover-Zustände werden gegen die persistierte Ausgangslage geprüft. Damit werden Handbewegungen während `unavailable`, `unknown`, eines Neustarts oder Reloads nicht als neue ungeschützte Basis übernommen.
- `async_stop()` erfasst die vertikale und Lamellen-Ausgangslage, bevor Listener abgeschaltet werden und bevor es auf eine laufende Auswertung wartet. Eine Handbewegung in dieser Wartephase kann deshalb nicht mehr irrtümlich als neue Baseline gespeichert werden.
- Provider-Backoff behält auch dann seine gespeicherte Eskalationsstufe, wenn die Retry-Frist während der Downtime abgelaufen ist. Eine abgelaufene Frist bleibt sofort fällig, statt nach jedem Restart wieder mit der ersten Stufe zu beginnen.
- Aktivierungs-, Bestätigungs- und Entwarnungszeiten von Sturm-, Wind-, Regen- und Frostschutz werden absolut fortgeführt. Ein bestehender Schutz bleibt bei unbekannter Quelle aktiv; ein unbekannter Zustand allein aktiviert keinen neuen Schutz.
- Laufende Python-Tasks, Listenerhandles und konkrete Warteschlangenbefehle werden bewusst nicht serialisiert oder blind wiederholt. Der neue Controller baut sie neu auf und berechnet den aktuellen Sollzustand aus Live- und Persistenzdaten.

### Zeitregeln, zentrale Konfiguration und Migration

- Zeitregel-Cursor, ausgeführte Vorkommen, anhaltende Nacht-Schließzustände, manuelle Freigaben sowie verzögerte Öffnungs- und Kontakt-Schließaktionen werden restartfest rekonstruiert.
- Eine nach längerer Nichtverfügbarkeit wiederkehrende Cover-Entity wird gezielt mit einer weiterhin aktiven Öffnungsregel abgeglichen; dadurch geht die einmalige Aktion nicht dauerhaft verloren.
- Der zentrale Regelassistent prüft sämtliche Zielräume vollständig, bevor der erste Raum geändert wird. Konflikte verursachen keine Teilverteilung; inaktive Regeln bleiben erhalten und werden bei der Konfliktprüfung nicht als aktive Ausführung behandelt.
- Gibt es keinen Raum mit nutzbarem Cover, meldet der Assistent einen lokalisierten Fehler, statt einen Erfolg ohne gespeicherte Regel anzuzeigen.
- Die v20-Migration normalisiert Regel-IDs deterministisch, erhält deaktivierte Regeln und löscht die zentrale Migrationsquelle erst, wenn jeder vorhandene Raum eine unabhängige Kopie besitzt. Verdeckte Löschmarkierungen verhindern, dass bewusst gelöschte migrierte Regeln bei einem späteren Retry wieder erscheinen.
- Nicht sicher interpretierbare Migrationsdaten blockieren die Migration, statt Konfigurationen still zu verwerfen. Bereits durch eine ältere v19-Ausführung verlorene Quelldaten können naturgemäß nicht rückwirkend rekonstruiert werden.
- Änderungen zentraler Optionen werden erst committed und danach genau einmal über den Update-Listener auf Coordinator und Räume angewendet. Zustandsabhängige Reload-Planung berücksichtigt auch parallel laufende Config-Entry-Setups.

### Home-Assistant-Lifecycle, Entities und Diagnosen

- Die bereits je Raum getrennte serialisierte Befehlswarteschlange wird in allen Setup-, Unload- und Remove-Pfaden konsistent verwaltet. Prioritätsbewusstes Coalescing verhindert, dass spätere Automatik- oder manuelle Positionsbefehle eine notwendige Safety-Fahrt verdrängen; vertikale und Lamellenkanäle bleiben getrennt.
- Beim fehlgeschlagenen Setup, Unload und Entfernen werden raumeigene Tasks, Timer, Listener, Claims und Queue-Worker beendet, ohne andere Räume zu beeinflussen. Der globale Coordinator wird bei Deaktivierung und Entfernung sicher entkoppelt und bei erneutem Laden wieder angebunden.
- Quellen-Umbenennungen aus der Entity Registry werden über einen persistenten Marker in Config Entry und beiden Stores atomar nachgezogen. Ein fehlgeschlagener Reload kann die idempotente Migration beim nächsten Setup wiederholen.
- Dynamische Unique IDs verwenden die beständige Entity-Registry-ID ihrer Quelle statt der veränderlichen `entity_id`. Legacy-IDs werden in-place migriert; bei einer Kollision bleibt der bestehende Eintrag sicherheitshalber erhalten.
- Nicht mehr konfigurierte dynamische Entities werden nur entfernt, wenn sie diesem Config Entry gehören. STOP-Unterstützung virtueller Cover folgt den aktuell verfügbaren Quell-Features.
- Diagnosen funktionieren auch für nicht geladene, gestoppte oder teilweise aufgebaute Einträge und redigieren aktuelle sowie ältere Entity-Referenzen und per-Cover-Laufzeitdaten.

### Bereinigung

- Die wirkungslose Option zur manuellen Persistenz wurde aus Flow, Defaults und Übersetzungen entfernt; ein alter gespeicherter Schlüssel wird bei der Migration weiterhin verträglich bereinigt.
- Nicht verwendete Transferauswahl-, Failsafe-, Kontaktpositions- und Status-Konstanten sowie zugehörige nie erreichbare Hilfslogik wurden entfernt.
- Wiederholte Zeitstempel-, Restore- und Entity-Referenzlogik wurde in klar abgegrenzte Hilfsmodule zusammengeführt, ohne die fachlichen Regeln der Controller zu verallgemeinern.

### Prüfung und bekannte Grenzen

- **75 von 75** Regressionstests bestehen; die fokussierte Restart-/Persistenzsuite umfasst **31** Tests und alle sieben ausdrücklich geprüften Restartfälle.
- Python-`compileall`, Vulture mit 80 Prozent Mindestkonfidenz sowie die JSON- und Übersetzungskonsistenzprüfungen sind erfolgreich. Ruff meldet außerhalb reiner Format-/Importsortierung keine Befunde. Fünf bereits im Original vorhandene `I001`-Importsortierungsbefunde in ansonsten bytegleich belassenen Modulen sowie eine mögliche breite Neuformatierung wurden entsprechend der Vorgabe gegen reine Stiländerungen bewusst nicht automatisch korrigiert.
- Die Prüfungen sind umfassende Unit-, AST- und Stub-Regressionen, jedoch kein vollständiger End-to-End-Neustart mit realer Hardware und allen Cover-/Wetterprovidern.
- Home Assistants `Store.async_save()` meldet Datenträger-Schreibfehler nicht zuverlässig an die Integration zurück. Atomare Writes reduzieren Teil-Dateien, können einen harten Prozess-, Rechte- oder Datenträgerfehler aber nicht ausschließen.
- Eine vollständig kontextlose Handbewegung, die innerhalb des höchstens 15-minütigen Pending-Fensters exakt im plausiblen Weg zu einem eigenen Sollwert liegt, kann ohne ein zusätzliches Providersignal technisch nicht zweifelsfrei von verspätetem Feedback unterschieden werden.
- Source-Renames eines deaktivierten beziehungsweise nicht geladenen Eintrags werden mangels aktivem Listener nicht sofort erkannt. Legacy-Unique-ID-Kollisionen werden absichtlich nicht automatisch gelöscht.

---

## English

### Manual control and multiple covers

- Manual overrides are now always stored per cover with an absolute expiry instead of being optional.
- A restart or reload restores only the original remaining time. Expired overrides are discarded and the configured duration is not restarted.
- A manual group transaction reserves every selected cover's hold before the first provider await. Its own revision prevents ordinary sensor or minute events from aborting the transaction after list index `0`.
- Failed or unavailable covers are rolled back individually; successful covers and covers already at the requested target retain their own protection.
- Explicit external Home Assistant contexts take precedence over target and grace heuristics. Vertical and tilt feedback are tracked separately, and movement beyond an integration target is classified as new manual intent.
- Manual requests in an unsafe direction are clamped when an active protection defines a safety position. Safer movement remains possible, `frost_action=block` still affects automatic movement only, and an explicit manual STOP remains an immediate user or emergency stop.

### Restart, reload and persistence behavior

- Both room-owned Home Assistant Stores use atomic writes and are loaded before platforms and the first automatic evaluation start.
- Corrupt, unreadable or semantically unsafe persisted data raises `ConfigEntryNotReady` instead of silently starting with empty protection state. Home Assistant `.corrupt.*` backups remain detectable across later setup retries.
- Persisted state now includes enable/mode state, per-cover override deadlines, move cooldowns, last-known vertical and tilt positions, command/context markers, bounded pending targets, schedule cursor/state, weather-protection timers, and provider retry deadline/stage.
- Each cover keeps its own absolute override deadline and expiry wake-up. Temporary protection is additionally capped at the next local midnight.
- A pending target valid for at most 15 minutes can identify an accepted integration command completed during downtime. Unexplained vertical or tilt changes are protected as manual actions.
- Cover state already available before listener registration is compared with its persisted baseline. Manual movement while `unknown`, `unavailable`, stopped or reloading is therefore not silently adopted as an unprotected starting point.
- `async_stop()` snapshots vertical and tilt baselines before listeners are disabled and before waiting for an in-flight evaluation, closing a race that could previously bless a manual change made during that wait.
- Provider retry attempts retain their escalation stage even if the stored deadline expired during downtime. Expired retries remain immediately due instead of restarting at the first backoff step.
- Absolute activation, confirmation and release markers preserve storm, wind, rain and frost protection. Existing protection is held while its source is unknown; unknown input alone cannot mature a new protection state.
- In-flight Python tasks, listener handles and concrete queued service calls are intentionally rebuilt, not serialized or blindly replayed. The controller recalculates the current desired action from live and persisted state.

### Schedules, central configuration and migration

- Schedule cursor, executed occurrences, persistent night-close state, manual releases, pending opens and delayed contact closes are reconstructed across restarts.
- A cover recovering after an extended outage is reconciled specifically with a still-active OPEN rule so the one-shot action is not permanently missed.
- Central rule distribution preflights all target rooms before changing any room. Conflicts cannot produce a partial rollout; disabled rules are retained and do not count as active conflicts.
- The wizard returns a localized error when no room has a usable cover instead of reporting success while losing the new rule.
- The v20 migration uses deterministic rule IDs, retains disabled rules, and removes the central migration source only after every existing room owns an independent copy. Hidden tombstones prevent deliberately deleted migrated rules from being resurrected by a retry.
- Unsafe migration input blocks migration rather than silently dropping configuration. Source data already lost by an older v19 migration cannot be reconstructed retroactively.
- Central option updates are committed first and then applied exactly once through the update listener; state-aware room reload scheduling also covers concurrent Config Entry setup.

### Home Assistant lifecycle, entities and diagnostics

- The existing per-room serialized command queues are now managed consistently through every setup, unload and removal path. Priority-aware coalescing prevents later automatic or manual position requests from displacing safety work, while vertical and tilt channels remain isolated.
- Failed setup, unload and removal stop room-owned tasks, timers, listeners, claims and queue workers without affecting other rooms. The central coordinator detaches on disable/removal and reattaches safely.
- Entity Registry source renames are staged durably and applied across Config Entry data and both Stores. A failed reload leaves an idempotent marker for the next setup.
- Dynamic unique IDs are based on the source Entity Registry ID instead of its mutable `entity_id`. Legacy IDs migrate in place; an existing collision is retained rather than deleted.
- Stale dynamic entities are removed only when owned by the current Config Entry. Virtual-cover STOP support follows the current source feature set.
- Diagnostics remain safe for unloaded, stopped and partially constructed entries and redact current and legacy entity references plus per-cover runtime details.

### Cleanup

- The ineffective manual-persistence option was removed from flows, defaults and translations; migration still discards an old stored key safely.
- Unused transfer-selection, failsafe, contact-position and status constants and their unreachable helper logic were removed.
- Repeated timestamp restoration and entity-reference handling were consolidated into narrowly scoped helper modules without flattening controller business rules.

### Validation and known limits

- **75 of 75** regression tests pass. The focused restart/persistence suite contains **31** tests and covers all seven requested restart cases.
- Python `compileall`, Vulture at 80 percent confidence, JSON validation and translation-consistency checks pass. Ruff reports no findings outside formatting/import ordering. Five pre-existing `I001` import-order findings in modules otherwise kept byte-identical to the original, and a possible broad formatter rewrite, were deliberately not auto-fixed in accordance with the no-style-only-change requirement.
- The verification uses extensive unit, AST and stub regressions, not a full end-to-end restart with real cover hardware and every weather provider.
- Home Assistant's `Store.async_save()` does not reliably propagate disk-write failures back to the integration. Atomic writes reduce partial files but cannot eliminate hard process, permission or storage failures.
- Without an external signal, a completely context-free manual movement exactly along a still-plausible integration target cannot be distinguished with certainty from delayed provider feedback during the bounded 15-minute pending window.
- A source rename while its Config Entry is disabled or unloaded is not observed immediately because no listener is active. Legacy unique-ID collisions are deliberately retained for manual resolution.

---

## `20260903.085028` – Erste öffentliche Stable-Veröffentlichung / First Public Stable Release

**Veröffentlichungsdatum:** 3. September 2026  
**Release-Kanal:** Stable  
**Mindestversion Home Assistant:** 2026.7.0  
**Config-Entry-Version:** 19

Diese Version ist die **erste öffentliche Veröffentlichung** von Smart Shading Control. Frühere interne Entwicklungs- und Teststände werden nicht als öffentliche Releases geführt.

---

## Deutsch

### Smart Shading Control

Smart Shading Control ist eine vollständig über die Home-Assistant-Oberfläche konfigurierbare Integration zur intelligenten, sicheren und raumbezogenen Steuerung von Rollläden und Jalousien.

Die Erstveröffentlichung umfasst unter anderem:

- zentrale Gebäudeeinstellungen und getrennte Raumkonfigurationen
- Zuordnung mehrerer Rollläden zu Nord-, Ost-, Süd- und Westfassaden
- sonnenstands-, temperatur-, prognose- und wetterabhängige Beschattung
- feste Zeitregeln sowie Sonnenaufgang und Sonnenuntergang mit Versatz
- getrennte Zielpositionen für Öffnung, Nacht, Vorbeugung, Hitze und starke Hitze
- optionale Fenster- oder Türkontakte je Rollladen
- Wind-, Sturm-, Regen- und Frostschutz
- manuelle Übersteuerungen mit einstellbarer Sperrzeit
- optionale Wiederherstellung aktiver manueller Sperren nach einem Neustart
- virtuelle Raum- und Einzel-Cover
- optionale Lamellensteuerung kompatibler Cover
- serialisierte Befehlswarteschlangen zur zuverlässigen Ausführung von Fahrbefehlen
- Status-, Diagnose-, Entscheidungs- und Reparaturentitäten
- Trockenlaufmodus ohne physische Fahrbefehle

### Korrigierte manuelle Mehrfachbedienung

Die Erstveröffentlichung enthält bereits die Korrektur für die manuelle Bedienung mehrerer Rollläden eines Raums:

- Ein eindeutig externer Home-Assistant-Bedienkontext wird vor internen Grace-, Sollwert- und `last_command`-Heuristiken als manuelle Bedienung erkannt.
- Dadurch erhält auch der **zuerst manuell angesteuerte Rollladen** zuverlässig seine manuelle Sperre.
- Eine spätere automatische Auswertung kann diesen ersten Rollladen nicht mehr irrtümlich auf einen Automatik-Sollwert zurückfahren, während die übrigen Rollläden gesperrt bleiben.
- Die Erkennung funktioniert unabhängig davon, ob dem betreffenden Rollladen ein Fenster- oder Türkontakt zugeordnet ist.
- Eigene Befehle von Smart Shading Control bleiben über ihre Context-ID eindeutig von manuellen Bedienungen getrennt.

### Installation

Die Installation erfolgt empfohlen über HACS. Alternativ kann der Ordner `custom_components/smart_shading_control` aus dem Release-Paket nach `/config/custom_components/smart_shading_control` kopiert werden. Nach der Installation muss Home Assistant vollständig neu gestartet werden.

### Paketqualität

- ICON und LOGO wurden bytegenau unverändert übernommen.
- Das Release-Paket enthält keine Entwicklungs-, Test-, Cache- oder Bytecode-Artefakte.
- Versionsangaben in Manifest, Konstanten, README und RELEASE sind konsistent.

---

## English

### Smart Shading Control

Smart Shading Control is a Home Assistant custom integration for intelligent, safe and room-based control of shutters and blinds, configured entirely through the Home Assistant user interface.

The first public release includes, among other features:

- central building settings with separate room configurations
- assignment of multiple covers to north, east, south and west facades
- sun-, temperature-, forecast- and weather-based shading
- fixed schedules plus sunrise and sunset rules with offsets
- dedicated target positions for open, night close, preventive shading, heat and strong heat
- optional window or door contacts per cover
- wind, storm, rain and frost protection
- manual overrides with configurable lock duration
- optional persistence of active manual overrides across restarts
- virtual room and individual cover entities
- optional tilt control for compatible covers
- serialized command queues for reliable cover command execution
- status, diagnostic, decision and repair entities
- dry-run mode without physical cover commands

### Corrected manual multi-cover operation

The first public release already includes the correction for manually operating multiple covers in one room:

- An unambiguously external Home Assistant command context is classified as manual operation before internal grace-period, target-position and `last_command` heuristics are evaluated.
- As a result, the **first cover operated manually** now reliably receives its manual override as well.
- A later automatic evaluation can no longer incorrectly move that first cover back to an automatic target while the other manually operated covers remain locked.
- Detection works independently of whether a window or door contact is assigned to the affected cover.
- Smart Shading Control's own commands remain clearly separated from manual operation through their Context IDs.

### Installation

Installation through HACS is recommended. Alternatively, copy `custom_components/smart_shading_control` from the release package to `/config/custom_components/smart_shading_control`. Home Assistant must be fully restarted after installation.

### Package quality

- ICON and LOGO remain byte-for-byte unchanged.
- The release package contains no development, test, cache or bytecode artifacts.
- Version information in the manifest, constants, README and RELEASE is consistent.
