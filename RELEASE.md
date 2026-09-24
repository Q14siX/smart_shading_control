# Smart Shading Control – Release Notes

## 20260924.160135 – Fahrbefehle und Zustandswiederherstellung / Commands and State Recovery

**Datum / Date:** 24. September 2026 / 24 September 2026  
**Mindestversion / Minimum Home Assistant:** 2026.7.0  
**Config-Entry-Version / Config Entry version:** 20, unverändert / unchanged

## Deutsch

### Fahrbefehle und Zeitsteuerung

- Bei positionsfähigen Rollos gilt der Zustand „offen“ ohne gültigen Prozentwert nicht mehr als vollständig geöffnet. Zeitregeln und manuelle Gruppenbefehle senden die erforderliche Öffnung auch an diese Rollos. Unbekannte Positionen werden weder als erreichte Fahrziele noch als bestätigte 100-Prozent-Position gespeichert.
- Bei unbekannter Prozentposition kann eine Teilöffnung den aktiven Wetterschutz nicht umgehen. Eine kontaktbedingte Öffnung verwendet in diesem Fall die vollständig geöffnete Position, damit ein bereits weiter geöffnetes Rollo nicht abgesenkt wird. Ein noch unbestätigter Nacht-Schließbefehl bleibt für einen erforderlichen Kontakt-STOP erkennbar.
- Schnell aufeinanderfolgende STOP-Befehle werden zuverlässig verarbeitet. Auch ein erneuter STOP direkt nach einer neuen Fahrt wird nicht mehr durch eine vorherige STOP-Anfrage unterdrückt.
- Verspätete Rückmeldungen einer vorherigen Fahrt verwerfen keinen wartenden manuellen STOP mehr. Noch gültige Fahranforderungen bleiben auch nach Ablauf der kurzen Rückmeldewartezeit für STOP und Schutzfunktionen erkennbar.
- Nach einem erfolgreichen kontaktbedingten STOP blockiert der alte Schließbefehl keine erneute Nachtfahrt. Fehlgeschlagene Sicherheitsstopps werden bei weiterhin unbekanntem Kontaktzustand erneut geprüft und angefordert. Fällige Wiederholungen bleiben über einen Neustart erhalten und werden nach der ersten aktuellen Raumauswertung fortgesetzt.
- Kontaktbedingte Öffnungen berücksichtigen die aktuelle Position auch nach einem STOP. Ein bereits weiter geöffnetes Rollo wird bei einer eingestellten Teilöffnung nicht wieder abgesenkt. Änderungen während der Wartezeit werden vor dem Versand erneut berücksichtigt.
- Ein neuerer manueller Fahr- oder STOP-Befehl bleibt auch bei 0 Minuten manueller Sperrzeit gültig, wenn gleichzeitig ein kontaktbedingter STOP oder eine anschließende Öffnung verarbeitet wird. Die ältere Kontaktaktion verdrängt diesen Auftrag nicht mehr. Das gilt auch für Wiederholungen nach Gerätefehlern: Eine zwischenzeitliche Gruppenfahrt wird durch deren abschließende Raumauswertung nicht wieder überschrieben.
- Verspätete eigene Positionsmeldungen bleiben nach einer Handbedienung ihrem ursprünglichen Fahrbefehl zugeordnet, solange dessen Rückmeldefrist gültig ist. Sie verwerfen dadurch keinen inzwischen wartenden manuellen Einzel- oder Gruppenauftrag mehr.
- Nach einer erkannten Handbewegung werden alte Fahrziele auch bei 0 Minuten manueller Sperrzeit verworfen. Eine danach neu ausgelöste Zeitregel kann dasselbe Ziel erneut anfordern, ohne durch die Rückmeldewartezeit des alten Befehls unterdrückt zu werden.
- Eine echte Gegenfahrt am Wandtaster oder eine unabhängige Lamellenänderung bleibt auch unmittelbar nach einem kontaktbedingten STOP erkennbar. Das gilt ebenso bei einem fehlgeschlagenen STOP und bei der Rückkehr eines zuvor nicht verfügbaren Geräts.
- Handbewegungen werden auch erkannt, wenn ein Antrieb sie ohne Fahrstatus in mehreren kleinen Positionsschritten meldet. Vertikalposition und Lamellenwinkel werden dabei getrennt betrachtet; kleine Schwankungen und eigene Fahrtrückmeldungen lösen keine neue manuelle Sperre aus.
- Eigene Ankünfte innerhalb der Zieltoleranz bleiben auch bei leichtem Überfahren des Sollwerts dem Fahrbefehl zugeordnet. Eine echte Gegenbewegung wird davon unabhängig erkannt.
- Antriebe ohne Prozent-Rückmeldung ordnen eine passende Öffnungs- oder Schließbewegung einem noch gültigen eigenen Endlagenbefehl zu. Eine kontaktbedingte Öffnung wird dadurch nicht irrtümlich als Handbedienung gesperrt.
- Eine gemeldete Zielposition gilt erst dann als erreicht, wenn keine laufende oder noch nicht zurückgemeldete Gegenbewegung vorliegt. Das betrifft manuelle Bedienung, Automatik und kontaktbedingte Öffnungen.
- Auch die Lamellensteuerung berücksichtigt angenommene, noch nicht zurückgemeldete Gegenbewegungen, bevor eine Sicherheitsposition als bereits erreicht gilt.
- Der Startabgleich und ausstehende Zeitregelöffnungen berücksichtigen laufende Fahrten. Die Öffnungsanforderung und die zugehörigen Zielmarkierungen bleiben bis zur passenden Rückmeldung erhalten.
- Automatische Auswertungen warten während des Home-Assistant-Starts auf die Betriebsbereitschaft. Abgelaufene Sperren werden verarbeitet, ohne dadurch vorzeitig eine automatische Fahrt auszulösen.
- Bestätigte eigene Positionsrückmeldungen werden als Ausgangslage für den nächsten Neustart gespeichert. Eine verspätet gemeldete Ankunft löst nach einer längeren Unterbrechung keine falsche manuelle Sperre mehr aus.
- Beim Entfernen einer Geräteentität werden die zuletzt bestätigten Vertikal- und Lamellenpositionen erhalten. Die unveränderte Rückkehr eines Geräts löst dadurch keine falsche manuelle Sperre aus; tatsächliche Positionsänderungen werden weiterhin berücksichtigt.

### Wetter und Sonnenereignisse

- Wartende manuelle Fahrbefehle prüfen den aktiven Wetterschutz und die aktuelle Fahrtrichtung unmittelbar vor dem Versand erneut. Ein inzwischen unzulässiges Schließziel wird nicht an den Antrieb gesendet und als nicht ausgeführt gemeldet; zulässige Öffnungen bleiben möglich.
- Ein aktiver Wind-, Sturm-, Regen- oder Frostschutz bleibt nach einem Neustart erhalten, wenn die Wetterquelle während der verzögerten Entwarnung unbekannt wird.
- Die Temperaturprognose verwendet die Zeitstempel der Vorhersage und den eingestellten Zeitraum. Vergangene Stunden aus einem noch gültigen Zwischenspeicher verdrängen keine aktuellen Vorhersagewerte mehr. Tages- und Zwölfstundenprognosen berücksichtigen ihre jeweiligen Zeiträume.
- Vorhersagezeitstempel bleiben beim Speichern und Wiederherstellen erhalten. Ältere Zwischenspeicher ohne Zeitstempel bleiben bis zum nächsten Abruf lesbar.
- Nicht umrechenbare Prognosezeitstempel werden einzeln übersprungen. Sie unterbrechen weder die Raumauswertung noch die Fahrbefehle; gültige Vorhersageeinträge bleiben nutzbar.
- Beim Wechsel der Wetterquelle während eines laufenden Abrufs werden Prognosedaten erneut der aktuellen Quelle zugeordnet. Daten einer anderen Quelle können dadurch keine unberechtigte Hitzeschutzentscheidung im bisherigen Raumzustand auslösen.
- Ungültige oder nicht umrechenbare Datumsangaben der Sonnenquelle unterbrechen die Verarbeitung nicht mehr. Für die Zeitsteuerung wird die verfügbare astronomische Berechnung verwendet; die ungültige Quelle wird als Reparaturhinweis angezeigt.

### Einrichtung

- Beim Abschluss der mehrstufigen Rollladenzuordnung werden die aktuellen Zeitregeln übernommen. Zwischenzeitlich ergänzte Regeln gehen nicht verloren, gelöschte Regeln werden nicht wiederhergestellt.
- Die Zuordnung zu anderen Räumen wird unmittelbar vor dem Speichern erneut geprüft. Änderungen während eines geöffneten Assistenten können keine doppelte Rollladenzuordnung mehr erzeugen.

- Entitätsumbenennungen bleiben bereits während der ersten Einrichtung sowie bei wiederholtem Neuladen erhalten. Das gilt auch, wenn ein Einrichtungsversuch fehlschlägt. Deaktivierte Einträge speichern die Zuordnungsänderung, ohne dadurch aktiviert zu werden.
- Bei der Umbenennung einer verwendeten Entität werden offene Einstellungsdialoge dieser Integration beendet. Das gilt auch für Dialoge, die während der Umstellung neu geöffnet werden. Bitte den Dialog nach Abschluss der Umstellung erneut öffnen; so können alte Entwürfe die aktualisierten Zuordnungen nicht überschreiben.
- Einrichtungs- und Einstellungsdialoge berücksichtigen auch neu ausgewählte Rollos, Kontakte und andere Quellen, die noch nicht gespeichert wurden. Wird eine solche Quelle umbenannt, wird der betroffene Dialog beendet, bevor eine veraltete Zuordnung gespeichert werden kann.

### Installation

1. Eine Sicherung der bestehenden Home-Assistant-Konfiguration erstellen.
2. Den vorhandenen Ordner `custom_components/smart_shading_control/` vollständig durch den gleichnamigen Ordner aus diesem Paket ersetzen.
3. Home Assistant vollständig neu starten.

Bestehende Räume, Zeitregeln, Kontaktzuordnungen und Einstellungen bleiben kompatibel. Eine erneute Einrichtung ist nicht erforderlich. Diese Version enthält auch die Verbesserungen der vorherigen Version zur zuverlässigen Raumsteuerung.

## English

### Commands and schedules

- For covers supporting position control, the state “open” without a valid percentage no longer means fully open. Schedules and manual group commands also send the required opening request to these covers. Unknown positions are neither treated as reached targets nor saved as confirmed 100-percent positions.
- With an unknown percentage position, a partial opening cannot bypass active weather protection. Contact-triggered opening uses the fully open position in this case so that a cover that is already farther open is not lowered. An unconfirmed scheduled closing command remains visible to a required contact-triggered STOP.
- Rapidly repeated STOP requests are processed reliably. A new STOP immediately after another movement is no longer suppressed by an earlier STOP request.
- Delayed feedback from an earlier movement no longer invalidates a waiting manual STOP. Valid movement intents remain visible to STOP and protection functions beyond the short feedback grace period.
- After a successful contact-triggered STOP, the previous closing command no longer delays resumed scheduled closing. Failed safety stops are reconsidered and requested again while the contact state remains unknown. Due retries survive a restart and resume after the first evaluation of the current room state.
- Contact-triggered opening considers the current position again after a STOP. A cover that is already farther open is not lowered to a configured partial opening. Position changes while a command is waiting are checked again before dispatch.
- A newer manual movement or STOP request remains valid even with a zero-minute manual hold while a contact-triggered STOP or subsequent opening is being processed. The older contact operation no longer displaces that request. This also applies to retries after device failures: their final room evaluation no longer overwrites a newer group movement.
- Delayed position feedback remains associated with its original command after manual movement while that command’s feedback window is valid. It no longer invalidates a newer pending individual or group request.
- Detected manual movement clears obsolete movement targets even with a zero-minute manual hold. A subsequently triggered schedule rule can request the same target again without being suppressed by the earlier command’s feedback grace period.
- Opposite movement from a wall switch or an independent slat adjustment remains detectable immediately after a contact-triggered STOP. This also applies when the STOP fails or a previously unavailable device returns.
- Manual movement is also detected when a drive reports it as several small position updates without a movement state. Vertical position and slat angle are tracked separately; small fluctuations and feedback from issued commands do not create a new manual hold.
- Feedback arriving within the target tolerance remains associated with the issued command even when movement slightly overshoots the target. Actual movement in the opposite direction is detected independently.
- Drives without percentage feedback associate matching opening or closing movement with a valid command to the corresponding endpoint. This prevents a contact-triggered opening from being mistaken for manual operation.
- A reported target position is considered reached only when no movement or accepted but unreported opposing command remains. This applies to manual operation, automation and contact-triggered opening.
- Slat control also accounts for accepted but unreported opposing movement before treating a safety position as already reached.
- Startup reconciliation and pending scheduled openings account for ongoing movement. Opening requests and their target markers remain pending until the appropriate feedback arrives.
- Automatic evaluation waits until Home Assistant is running. Expired holds are processed without triggering automatic movement prematurely during startup.
- Confirmed feedback from issued commands is saved as the baseline for the next restart. A delayed arrival report no longer causes a false manual hold after a longer interruption.
- The last confirmed vertical and tilt positions are preserved when a device entity is removed. A device returning at an unchanged position no longer creates a false manual hold; actual position changes are still considered.

### Weather and solar events

- Queued manual movement requests recheck active weather protection and their current movement direction immediately before dispatch. A closing target that has become unsafe is not sent to the drive and is reported as not executed; permitted opening movements remain available.
- Active wind, storm, rain and frost protection survives a restart when the weather source becomes unknown during the delayed release period.
- Temperature forecasts use their timestamps and the configured horizon. Past hours in an otherwise valid cache no longer displace current forecast values. Daily and twelve-hour forecasts account for their respective periods.
- Forecast timestamps survive storage and restoration. Older caches without timestamps remain readable until the next update.
- Forecast timestamps that cannot be converted are skipped individually. They interrupt neither room evaluation nor cover commands, and valid forecast entries remain usable.
- When the weather source changes during a pending refresh, forecast data is checked again against its current source. Data from another source can no longer trigger an incorrect heat-protection decision in the previous room state.
- Invalid solar source dates or dates that cannot be converted no longer interrupt processing. Scheduling uses the available astronomical calculation, and the invalid source produces a repair notice.

### Configuration

- Completing the multi-step cover assignment uses the current schedule rules. Rules added in the meantime are retained, and removed rules are not restored.
- Ownership by other rooms is checked again immediately before saving. Changes made while a wizard is open can no longer create duplicate cover assignments.

- Entity renames are retained from the first setup attempt and during repeated reloads, including when a setup attempt fails. Disabled entries preserve the reference change without being activated.
- Renaming a source entity closes open settings dialogs belonging to this integration, including dialogs opened while migration is in progress. Reopen the dialog after migration finishes so an old draft cannot overwrite the updated assignments.
- Setup and settings dialogs also track newly selected covers, contacts and other sources that have not yet been saved. Renaming one of these sources closes the affected dialog before an obsolete assignment can be stored.

### Installation

1. Back up the existing Home Assistant configuration.
2. Replace the complete `custom_components/smart_shading_control/` directory with the matching directory from this package.
3. Restart Home Assistant completely.

Existing rooms, schedules, contact assignments and settings remain compatible. No new setup is required. This version also includes the previous version’s improvements to reliable room control.
