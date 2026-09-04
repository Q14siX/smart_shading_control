<p align="center">
  <img src="https://raw.githubusercontent.com/Q14siX/smart_shading_control/main/custom_components/smart_shading_control/brand/icon.png" alt="Smart Shading Control Icon">
</p>

# Smart Shading Control – Release Notes

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
