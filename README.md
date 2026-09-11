<p align="center">
  <img src="https://raw.githubusercontent.com/Q14siX/smart_shading_control/main/custom_components/smart_shading_control/brand/logo.png" alt="Smart Shading Control">
</p>

# Smart Shading Control

<p align="center">
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2026.7.0%2B-41BDF5?logo=homeassistant&logoColor=white" alt="Home Assistant 2026.7.0+"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5" alt="HACS Custom Integration"></a>
  <img src="https://img.shields.io/badge/Release-Stable-success" alt="Stable Release">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"></a>
</p>

**Smart Shading Control** ist eine vollständig über die Home-Assistant-Oberfläche konfigurierbare Integration zur intelligenten, sicheren und raumbezogenen Steuerung von Rollläden und Jalousien.

Aktuelle Version: **`20260911.154309`**  
Veröffentlichungsstatus: **Stable**

[Deutsch](#deutsch) · [English](#english)

---

## Deutsch

**Wiederanlauf nach manueller Sperre:** Alle fälligen Rollläden werden direkt neu bewertet. Ihre Befehle starten pro Raum gestaffelt mit ungefähr einer Sekunde Abstand (bei drei Rollläden typischerweise 0 / 1 / 2 Sekunden). Die Integration wartet für den nächsten Rollladen nicht auf den Abschluss des vorherigen Serviceaufrufs. Eine abgelaufene Sperre erhält einen gezielten Wiederanlauf, der nicht erneut vom normalen Mindestfahrintervall verzögert wird; noch aktive Sperren anderer Rollläden bleiben wirksam. Für denselben physischen Rollladen bleiben Befehle geordnet. Die Staffelung gilt auch für manuelle Gruppenbefehle und Lamellen-/Kontaktaktionen. Die tatsächliche Motorbewegung hängt von Home Assistant und dem jeweiligen Provider ab.

### Funktionsumfang

- zentrale Gebäudeeinstellungen und getrennte Raumkonfigurationen
- Zuordnung mehrerer Rollläden zu Nord-, Ost-, Süd- und Westfassaden
- sonnenstands-, temperatur-, prognose- und wetterabhängige Beschattung
- globaler Erstellungsassistent für neue Zeitregeln sowie vollständig raumbezogene Regelverwaltung
- feste Uhrzeiten sowie Sonnenaufgang und Sonnenuntergang mit Versatz
- getrennte Zielpositionen für Öffnung, Nacht, Vorbeugung, Hitze und starke Hitze
- optionale Fenster- oder Türkontakte je Rollladen
- Wind-, Sturm-, Regen- und Frostschutz
- manuelle Übersteuerungen mit einstellbarer Sperrzeit
- neustartsichere Wiederherstellung aktiver manueller Sperren und weiterer Schutzzeiten
- Trockenlaufmodus ohne physische Fahrbefehle
- virtuelle Raum- und Einzel-Cover
- Status-, Diagnose-, Entscheidungs- und Reparaturentitäten
- optionale Lamellensteuerung für kompatible Cover-Entitäten
- Befehlswarteschlange mit mindestens einer Sekunde zwischen den Befehlsstarts pro Raum; langsame Providerantworten blockieren die anderen Rollläden nicht

### Voraussetzungen

- Home Assistant **2026.7.0 oder neuer**
- mindestens eine vorhandene `cover`-Entität
- HACS für die empfohlene Installation oder Dateizugriff auf das Home-Assistant-Konfigurationsverzeichnis

Smart Shading Control ist eine benutzerdefinierte Integration und nicht Bestandteil von Home Assistant Core.

### Installation über HACS

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Q14siX&repository=smart_shading_control&category=integration)

Alternativ:

1. HACS öffnen.
2. **Integrationen** auswählen.
3. Das Menü oben rechts öffnen und **Benutzerdefinierte Repositories** wählen.
4. `https://github.com/Q14siX/smart_shading_control` eintragen.
5. Als Kategorie **Integration** auswählen.
6. **Smart Shading Control** installieren.
7. Home Assistant vollständig neu starten.
8. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
9. Nach **Smart Shading Control** suchen.

### Manuelle Installation

1. Den Ordner `custom_components/smart_shading_control` aus dem Release-Paket vollständig nach `/config/custom_components/smart_shading_control` kopieren.
2. Home Assistant vollständig neu starten.
3. Die Integration unter **Einstellungen → Geräte & Dienste** hinzufügen.

Ein einfaches Neuladen von YAML ersetzt den Neustart nach einer Installation oder Aktualisierung nicht.

### Konfigurationsmodell

Die Integration verwendet zwei Arten von Config Entries:

#### Globale Einstellungen

Der globale Eintrag enthält gebäudeweite Daten und Vorlagen, unter anderem:

- Sonnen- und Wetterquelle
- Außentemperatur, Wind, Regen, Einstrahlung und Helligkeit
- Fassadenausrichtung
- Frost-, Wind-, Sturm- und Regenschutz
- Assistent zum einmaligen Erstellen einer neuen Zeitregel für alle vorhandenen Räume
- globale Positionsvorlagen
- globale Sperrzeit für manuelle Bedienungen
- Auswertungsintervall

Zentrale Positionswerte und die zentrale Sperrzeit für manuelle Bedienungen werden beim Speichern in **alle** vorhandenen Räume geschrieben und überschreiben dort die bisherigen Werte. Danach können einzelne Räume wieder individuell angepasst werden. Das nächste Speichern der betreffenden globalen Einstellung überschreibt diese Raumwerte erneut.

Zeitregeln verhalten sich bewusst anders: Im globalen Eintrag werden sie nicht gespeichert. Der globale Assistent dient ausschließlich dazu, **eine neue Regel zu erstellen** und als eigenständige Raumregel an jeden zu diesem Zeitpunkt vorhandenen Raum anzuhängen.

Fahrpositionen, Zeitregeln und raumspezifische Vorgaben stammen aus dem jeweiligen Raum. Gebäudeweite Sonnen-, Wetter- und Messquellen werden dagegen aus dem zentralen Eintrag übernommen. Die zentrale Konfiguration sendet selbst keine Fahrbefehle an einen ausgewählten Raum.

#### Räume

Jeder Raum erhält einen eigenen Eintrag mit ausschließlich den Geräten und Einstellungen dieses Raums:

- Raumname und Raumtemperatursensor
- Rollläden nach Himmelsrichtung
- optional ein Öffnungskontakt je Rollladen
- individuelle Zielpositionen
- individuelle Zeitregeln
- manuelle Sperrzeit
- neustartsichere Speicherung manueller Übersteuerungen
- optionale Lamellenpositionen

Ein Rollladen kann nicht gleichzeitig mehreren Räumen zugeordnet werden.

### Dynamischer Hitzeschutz

Hitzeschutz ist eine Tagesfunktion und wird für jede Fassade getrennt bewertet. Zuerst müssen Sonnenstand, Fassadenausrichtung und eine ausreichend plausible aktuelle Einstrahlung zusammenpassen. Erst danach bestimmen Raumtemperatur, Außentemperatur, Temperaturdifferenz, Raumtemperaturtrend und Temperaturprognose die Stufe. Eine warme Raumtemperatur oder eine hohe Vorhersage allein erzeugt keine Sonneneinstrahlung.

Ein gültiger Einstrahlungssensor liefert tatsächliche Messwerte in W/m². Helligkeit in Lux und Wetterzustände sind dagegen nur Schätzgrundlagen. Regen, Nebel, bedeckter Himmel sowie mindestens 85 % Bewölkung dürfen von einem hohen Luxwert nicht ausgeblendet werden. Bei Regen oder bedecktem Himmel ohne ausreichenden Einstrahlungsmesswert wird deshalb kein dynamischer Hitzeschutz aktiviert. Ein ausreichend hoher tatsächlicher Einstrahlungsmesswert kann auch bei gemeldetem Regen oder kühler Außenluft eine Beschattung begründen.

| Eingangsquelle | Einstieg in Beschattung | Halten einer aktiven Beschattung | Einstieg in starken Hitzeschutz | Halten der starken Einstrahlungsfreigabe |
|---|---:|---:|---:|---:|
| Einstrahlungsmessung | 200 W/m² | 160 W/m² | 400 W/m² | 350 W/m² |
| Helligkeitsmessung mit Wetterprüfung | 30.000 lx | 24.000 lx | 45.000 lx | 40.000 lx |
| Wetterbasierter Einstrahlungsfaktor | 0,40 | 0,32 | 0,65 | 0,55 |

Die Werte sind Freigabegrenzen, keine alleinigen Fahrbefehle. Auch Luxwerte müssen den zugehörigen Wetterfaktor erreichen. Zusätzlich gilt ein fassadenbezogener Einstrahlungsfaktor von mindestens 0,12 beim Einstieg beziehungsweise 0,09 beim Halten; für die starke Freigabe sind es 0,25 beziehungsweise 0,20. Die Berechnung verwendet den geometrischen Einfall auf eine vertikale Fassade. Die Prozentanzeige ist ein relativer Steuerungswert, keine berechnete Heizleistung und keine Messung direkt am Fenster.

Das Risikomodell gewichtet Raumtemperatur mit maximal 35, Temperaturprognose mit 25, Außentemperatur mit 15, fassadenbezogene Einstrahlung mit 15 und steigende Raumtemperatur mit 10 Punkten. Deutlich kühlere Außenluft und ein tatsächlich fallender Raumtemperaturtrend reduzieren das Risiko jeweils um höchstens 10 Punkte. Die Temperaturdifferenz allein wird ausdrücklich nicht als Nachweis einer offenen Lüftung oder einer tatsächlichen Abkühlung behandelt. Die Risikoeinstiegsgrenzen bleiben 35/55/75 Punkte; die konfigurierte Risikohysterese bleibt wirksam. Temperaturbedingte Hochstufungen benötigen ebenfalls die Einstrahlungsfreigabe; eine Hochstufung auf starken Hitzeschutz benötigt die stärkere Freigabe. Für die temperaturbedingte Rückstufung gilt eine Hysterese von 0,3 °C.

Fehlen benötigte Tages-Eingangsdaten, wird die Position gehalten, statt aus Ersatzannahmen zu öffnen oder zu beschatten. Ungültige Einheiten, negative/nicht endliche Solarmesswerte und reine Wiederherstellungszustände gelten nicht als Messnachweis. Solarsensoren werden anhand von `last_reported` auf Aktualität geprüft: höchstens 30 Minuten beziehungsweise drei Auswertungsintervalle, falls diese länger sind. Mehr als fünf Minuten in der Zukunft liegende Berichte werden ebenfalls verworfen. Ein unverändert, aber frisch gemeldeter Messwert bleibt gültig. Ist ein konfigurierter Messsensor nicht nutzbar, kann eine weitere gültige konfigurierte Messquelle einspringen; ohne solche Messwerte wird nicht stillschweigend auf geschätzten Sonnenschein gewechselt.

**Eine aktive Nacht-Schließregel hat Vorrang vor dem dynamischen Tagesziel.** Das Ende des Hitzeschutzes hebt sie nicht auf. Ein nach einem Ausfall wiederhergestellter alter Öffnungs-Wiederholungsauftrag darf eine neuere Schließregel nicht überschreiben. Fensterkontakte, manuelle Sperren, Mindestfahrabstände und explizite Betriebsarten behalten ihre bisherigen Aufgaben; konfigurierte Sicherheitsfunktionen können weiterhin entsprechend ihrer eigenen Regeln eingreifen.

Die Sensoren für Entscheidungsgrund, Hitzerisiko und Sonnenlast zeigen in ihren Attributen die verwendete Quelle, Wetter-/Messwerte, Temperaturdifferenz und die Bewertung jeder Fassade. `dynamic_no_solar_heat_gain` bedeutet, dass keine ausreichende solare Freigabe vorliegt; `dynamic_inputs_unavailable` bedeutet Halten wegen fehlender oder nicht verwertbarer Daten. Die Grenzwerte sind konservative Steuerungsheuristiken. Ohne Informationen über Verglasung, Fensterflächen, Verschattung, Luftwechsel und interne Wärmequellen lässt sich daraus keine exakte Raumwärmebilanz ableiten.

### Zeitregeln

Eine Zeitregel führt genau eine Aktion aus:

- **Öffnen**
- **Schließen**

Als Auslöser stehen eine feste Uhrzeit, Sonnenaufgang oder Sonnenuntergang zur Verfügung. Für Sonnenereignisse kann ein positiver oder negativer Versatz verwendet werden. Jeder Raumcontroller überwacht Zeitereignisse dauerhaft minütlich.

Über **Globale Einstellungen → Neue Zeitregel für alle Räume erstellen** kann genau eine neue Regel angelegt werden. Beim Abschluss wird diese Regel als unabhängige Raumregel an jeden bereits vorhandenen Raum angehängt und gilt dort zunächst für alle Rollläden dieses Raums. Vorhandene Raumregeln bleiben erhalten.

Die erstellte Regel wird **nicht global gespeichert**. Sie kann daher anschließend ausschließlich im jeweiligen Raum bearbeitet oder gelöscht werden. Später neu angelegte Räume erhalten zuvor verteilte Regeln nicht automatisch.

Eine Schließregel erzeugt einen anhaltenden Nacht-Schließzustand. Eine spätere Öffnungsregel hebt diesen Zustand wieder auf. Kurzzeitige Provider-Ausfälle führen nicht dazu, dass ein einmaliges Öffnungsereignis unbemerkt verloren geht.

### Fenster- und Türkontakte

Ein zugeordneter Kontakt schützt ausschließlich automatische Schließbewegungen aus einer Nacht- beziehungsweise Schließregel.

- **geschlossen:** Die Schließung ist nach einer kurzen Entprellzeit zulässig.
- **geöffnet oder gekippt:** Die automatische Schließung wird blockiert.
- **unknown oder unavailable:** Die automatische Schließung wird sicherheitshalber blockiert, ohne den Rollladen zu bewegen.
- **kein Kontakt zugeordnet:** Der Rollladen kann ohne Kontaktprüfung automatisch öffnen und schließen.

Wurde ein Rollladen nachweislich durch eine Nachtregel geschlossen, kann ein echter Übergang von geschlossen zu geöffnet oder gekippt den Rollladen wieder öffnen. Ein bloßer Wiederanlauf eines Kontakts von `unknown` oder `unavailable` zu `open` gilt nicht als tatsächliches Öffnen und löst keine Fahrt aus.

### Manuelle Übersteuerung

Erkennt die Integration eine manuelle Fahrt, wird der betroffene Rollladen für die konfigurierte Dauer von normalen automatischen Bewegungen ausgenommen. Das gilt sowohl für Bedienungen über Home Assistant als auch für physische Taster oder Gateways, die nur eine Positionsänderung melden.

- Standardwert: **240 Minuten**
- die Dauer kann global übertragen und anschließend je Raum geändert werden
- aktive Sperren werden immer mit ihrem absoluten Ablaufzeitpunkt gespeichert und nach Neustart oder Reload mit der ursprünglichen Restlaufzeit wiederhergestellt
- bereits abgelaufene Sperren werden nicht wiederhergestellt; ein Neustart beginnt die konfigurierte Dauer nicht erneut
- Sperren und Ablaufzeiten werden für jeden Rollladen getrennt geführt, auch für den ersten Rollladen einer Gruppe
- am lokalen Tageswechsel werden temporäre Sperren beendet
- eine neu ausgelöste Zeitregel darf eine ältere manuelle Sperre gezielt ersetzen
- Wiederholungsversuche einer bereits früher ausgelösten Öffnungsregel dürfen eine spätere manuelle Bedienung nicht aufheben

Konfigurierte Sicherheitsmaßnahmen können eine manuelle Sperre übersteuern, wenn dies zum Schutz der Anlage erforderlich ist. Bei einem aktiven Wind-, Sturm-, Regen- oder Frostschutz mit vorgegebener Sicherheitsposition wird ein manueller Positionsbefehl, der den Rollladen weiter in die unsichere Richtung fahren würde, auf diese Position begrenzt. Eine Fahrt in die sicherere Richtung bleibt möglich. Die Frost-Aktion **Automatik blockieren** sperrt entsprechend ihrer Konfiguration nur Automatikfahrten. Ein ausdrücklich ausgelöster manueller STOP hat als unmittelbarer Benutzer- beziehungsweise Notstopp Vorrang vor einer noch ausstehenden Fahrt.

### Neustart- und Reload-Verhalten

Restart-relevante Zustände werden in Home Assistants persistentem Speicher abgelegt, bevor der Raumcontroller mit seiner ersten automatischen Auswertung beginnt. Dazu gehören insbesondere:

- die absoluten Ablaufzeitpunkte manueller Sperren pro Rollladen
- Cooldowns, letzte bekannte Positionen sowie Kennzeichen eigener Positions- und Lamellenbefehle
- anhaltende und verzögerte Zustände von Zeitregeln, einschließlich ausstehender Öffnungs- und Schließaktionen
- absolute Aktivierungs-, Bestätigungs- und Entwarnungszeiten des Wetter- und Frostschutzes
- begrenzte Wiederholungszustände bei vorübergehend nicht erreichbaren Providern
- ein zeitlich begrenztes Sollwertkennzeichen für einen bereits angenommenen, aber vor dem Restart noch nicht vollständig gemeldeten Fahrbefehl

Nach einem Neustart werden Live-Zustände wie aktuelle Sensorwerte, Sonnenstand, Kontakte und der daraus folgende Sollwert neu aus Home Assistant ermittelt. Bereits in Arbeit befindliche Python-Tasks oder Warteschlangeneinträge werden nicht blind wiederholt; fachlich notwendige Aktionen werden anhand der gespeicherten Zustände neu bewertet. Positionsänderungen während einer Nichtverfügbarkeit oder eines Reloads werden gegen die zuvor gespeicherte Ausgangslage geprüft, damit eine Handbedienung nicht durch eine sofortige Automatikfahrt überschrieben wird.

Ist ein bereits vorhandener persistenter Schutzspeicher beschädigt oder semantisch ungültig, startet der betroffene Raum nicht im ungeschützten Zustand. Der Config Entry bleibt stattdessen bis zur Wiederherstellung beziehungsweise bewussten Bereinigung des Speichers nicht bereit.

### Betriebsarten

Je Raum stehen folgende Betriebsarten zur Verfügung:

- **Automatik:** vollständige automatische Auswertung
- **Hitzeschutz:** feste Hitzeschutzposition
- **Offen:** alle Rollläden auf die konfigurierte Öffnungsposition
- **Geschlossen:** alle Rollläden schließen
- **Pause:** keine automatischen Bewegungen

### Entitäten

Abhängig von der Konfiguration erzeugt die Integration unter anderem:

- Aktivierungsschalter für die Raumautomatik
- Auswahl der Betriebsart
- virtuelle Cover für den gesamten Raum und einzelne Rollläden
- Sensoren für Status, Zielposition, Entscheidung, Kontakte und Schutzfunktionen
- Diagnosesensoren für Zeitregeln, Befehlswarteschlange und manuelle Sperren
- Schaltflächen zum Neuberechnen, Zurücksetzen und Löschen manueller Sperren

Nicht benötigte oder nicht unterstützte Funktionen erzeugen keine unnötigen Entitäten.

### Prioritäten und Sicherheit

Die Steuerung berücksichtigt unter anderem folgende Grundsätze:

1. Pause oder deaktivierte Automatik verhindert normale automatische Fahrten.
2. Explizite Betriebsarten haben Vorrang vor der dynamischen Beschattung.
3. Zeitregeln können die dynamische Zielposition ersetzen.
4. Wetter- und Frostschutz kann eine sicherere Position erzwingen.
5. Kontakte blockieren nur die automatische Nacht-Schließung.
6. Manuelle Sperren unterdrücken normale automatische Ziele, nicht jedoch notwendige Sicherheitsbewegungen.
7. Mindeständerung und Mindestfahrabstand verhindern unnötige oder zu häufige Fahrbefehle.
8. Im Trockenlauf werden Entscheidungen berechnet, aber keine Befehle an Geräte gesendet.

### Release-Historie

Die Version **`20260903.085028`** vom 3. September 2026 war die **erste öffentliche Stable-Veröffentlichung** von Smart Shading Control.

Für die Erstinstallation wird Smart Shading Control über HACS oder manuell installiert und anschließend vollständig über die Home-Assistant-Oberfläche eingerichtet. Nach der Installation ist ein vollständiger Neustart von Home Assistant erforderlich.

Die Erstveröffentlichung enthält bereits die korrigierte Erkennung manueller Mehrfachbedienungen: Auch der zuerst manuell angesteuerte Rollladen eines Raums erhält zuverlässig seine manuelle Sperre und wird nicht durch eine spätere automatische Auswertung vorzeitig auf einen Automatik-Sollwert zurückgefahren. Dies gilt unabhängig davon, ob dem Rollladen ein Fenster- oder Türkontakt zugeordnet ist.

### Hilfe und Fehlerberichte

- Dokumentation: https://hilfe.q14six.de/shelves/smart-shading-control
- English help portal: https://help.q14six.de
- Fehlerberichte: https://github.com/Q14siX/smart_shading_control/issues

Ein Fehlerbericht sollte mindestens enthalten:

- Home-Assistant-Version
- Version von Smart Shading Control
- betroffener Raum und betroffene Entitäten
- genauer Zeitpunkt
- relevante Protokollauszüge
- heruntergeladene Integrationsdiagnose
- erwartetes und tatsächlich beobachtetes Verhalten

### Datenschutz

Die Integration benötigt keinen eigenen Cloud-Dienst und überträgt selbst keine Daten an Q14siX. Sie verarbeitet ausschließlich die in Home Assistant vorhandenen Entitäten und Konfigurationen.

### Markenbilder

Die mitgelieferten Dateien `brand/icon.png` und `brand/logo.png` sind Bestandteil der Integration. Sie dürfen in offiziellen Paketen nicht optimiert, neu kodiert, komprimiert, skaliert oder anderweitig verändert werden.

### Lizenz

Smart Shading Control wird unter der [MIT-Lizenz](LICENSE) veröffentlicht.

---

## English

**Resuming after a manual override:** All due covers are reevaluated immediately. Commands are staggered by approximately one second per room (typically 0 / 1 / 2 seconds for three covers). Dispatch of the next cover does not wait for the previous service call to complete. An expired override receives a targeted resumption that is not delayed again by the ordinary movement cooldown; other covers' active overrides remain effective. Commands to the same physical cover remain ordered. Pacing also applies to manual group commands, tilt and contact actions. Actual motor movement depends on Home Assistant and the underlying provider.

**Smart Shading Control** is a Home Assistant custom integration for intelligent, safe and room-based control of shutters and blinds. It is configured entirely through the Home Assistant user interface.

Current version: **`20260911.154309`**  
Release status: **Stable**

### Main features

- central building settings with separate room configurations
- north, east, south and west facade assignments
- sun-, temperature-, forecast- and weather-based shading
- create-only central wizard for new rules, with complete rule management inside each room
- fixed times, sunrise and sunset with offsets
- dedicated positions for open, night close, preventive shading, heat and strong heat
- optional opening contact for each cover
- wind, storm, rain and frost protection
- configurable manual override duration
- restart-safe persistence of active manual overrides and other protection deadlines
- dry-run mode without physical commands
- virtual room and individual cover entities
- diagnostic, decision, status and repair entities
- optional tilt control for supported covers
- command queue with at least one second between command starts per room; slow provider responses do not block the other covers

### Requirements

- Home Assistant **2026.7.0 or newer**
- at least one existing `cover` entity
- HACS for the recommended installation, or file access to the Home Assistant configuration directory

Smart Shading Control is a custom integration and is not part of Home Assistant Core.

### HACS installation

[![Open your Home Assistant instance and open the repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Q14siX&repository=smart_shading_control&category=integration)

Alternatively, add `https://github.com/Q14siX/smart_shading_control` as a custom HACS integration repository, install the integration, restart Home Assistant, and add **Smart Shading Control** under **Settings → Devices & services**.

### Manual installation

Copy `custom_components/smart_shading_control` to `/config/custom_components/smart_shading_control`, restart Home Assistant completely, and add the integration through the user interface.

### Configuration model

The integration uses one central building entry and separate room entries. Saving central position values or the manual-operation lock duration writes them to **every** existing room and replaces the previous room value. Individual rooms can then be customized again; saving the related central setting later overwrites those room values again.

Time rules intentionally use a different workflow. They are never stored in the central entry. The central wizard only creates one new rule and appends an independent copy to every room that exists at that moment.

At runtime, positions, schedules and room-specific settings come from the room entry. Building-wide sun, weather and measurement sources come from the central entry. The central entry itself does not send cover commands to one selected room.

Each room contains only its own covers, contacts, temperature sensor, positions, schedules and manual override settings. A physical cover cannot be assigned to more than one room.

### Dynamic heat protection

Heat protection is a daytime function assessed separately for each facade. Sun position, facade orientation and sufficiently plausible current solar exposure must first agree. Only then do room temperature, outside temperature, their difference, the measured room temperature trend and the temperature forecast determine the level. A hot room or a hot forecast alone cannot create solar evidence.

A valid irradiance sensor provides a measurement in W/m². Illuminance in lux and weather conditions are estimates, not energy measurements. A high lux reading must not hide rain, fog, overcast conditions or cloud coverage of at least 85 %. Rain or overcast conditions without sufficient measured irradiance therefore do not activate dynamic heat protection. Sufficiently high actual irradiance may still justify shading during reported rain or with cool outside air.

| Input source | Enter shading | Hold active shading | Enter strong solar eligibility | Hold strong solar eligibility |
|---|---:|---:|---:|---:|
| Irradiance measurement | 200 W/m² | 160 W/m² | 400 W/m² | 350 W/m² |
| Illuminance with weather validation | 30,000 lx | 24,000 lx | 45,000 lx | 40,000 lx |
| Weather-derived radiation factor | 0.40 | 0.32 | 0.65 | 0.55 |

These are eligibility thresholds, not standalone movement commands. Lux readings must also meet the corresponding weather-factor threshold. The facade exposure factor must reach 0.12 on entry or 0.09 while holding; strong eligibility requires 0.25 or 0.20 respectively. Geometry accounts for incidence on a vertical facade. The percentage is a relative control value, not heating power or a measurement at the window.

The risk model allocates at most 35 points to room temperature, 25 to the temperature forecast, 15 to outside temperature, 15 to facade-specific exposure and 10 to a rising room temperature. Significantly cooler outside air and an observed falling room temperature each reduce the score by at most 10 points. A temperature difference alone is explicitly not evidence of ventilation or actual cooling. Risk entry thresholds remain 35/55/75 points, with the configured risk hysteresis retained. Temperature-driven escalation also requires solar eligibility; escalation to strong protection requires the stronger eligibility. Temperature-driven de-escalation has 0.3 °C hysteresis.

Missing necessary daytime inputs hold the current position instead of opening or shading from assumed replacement values. Invalid units, negative/non-finite solar measurements and restored-only states do not qualify as measurements. Solar measurements are checked using `last_reported`: at most 30 minutes or three evaluation intervals, whichever is longer. Reports more than five minutes in the future are also rejected. Unchanged but freshly reported measurements remain valid. Another valid configured measurement source may replace an unusable one; when no configured measurement is usable, the system does not silently fall back to estimated sunshine.

**An active scheduled night closure takes precedence over the dynamic daytime target.** Ending heat protection does not release it. An older opening retry restored after an outage cannot override a newer closing rule. Opening contacts, manual overrides, movement intervals and explicit operating modes retain their existing roles; configured safety functions can still intervene under their own rules.

Reason, heat-risk and solar-load sensors expose the selected source, weather/measurement values, temperature difference and each facade assessment in their attributes. `dynamic_no_solar_heat_gain` denotes insufficient solar eligibility; `dynamic_inputs_unavailable` denotes holding because necessary data are missing or unusable. These thresholds are conservative control heuristics. They are not a complete room heat-balance model without glazing, window area, local shading, air-exchange and internal-heat-source data.

### Time rules

A time rule performs exactly one opening or closing action at a fixed time, sunrise or sunset, optionally with an offset.

Use **Central settings → Create a new time rule for all rooms** to create exactly one new rule. Completing the wizard appends an independent room rule to every existing room and initially targets all covers assigned to that room. Existing room rules are preserved.

The created rule is not stored centrally. It can afterwards only be edited or deleted inside the respective room. Rooms created later do not automatically inherit rules that were distributed earlier. Every room controller monitors time events once per minute.

### Opening contacts

Contacts only restrict automatic closing caused by a night or close schedule.

- `closed`: closing is allowed after a short debounce period
- `open` or `tilted`: automatic closing is blocked
- `unknown` or `unavailable`: closing is blocked without moving the cover
- no assigned contact: the cover may open and close without contact checks

A real transition from closed to open or tilted can reopen a cover that was previously closed by a night rule. Provider recovery from `unknown` or `unavailable` is not treated as a real opening event.

### Manual overrides

Detected manual movement temporarily excludes the affected cover from normal automatic commands. Physical switches and gateways that only report a changed position are supported as well.

The default duration is 240 minutes. It can be transferred globally and changed per room afterwards. Active overrides are always stored per cover with their absolute expiry. A restart or reload restores only the original remaining time: expired overrides are discarded, and the configured duration is not started again. Temporary overrides end at the next local midnight.

Configured wind, storm, rain or frost protection with a defined safety position may still enforce that position. A manual position request that would move farther into an unsafe direction is clamped to it, while a request in the safer direction remains possible. The frost action **block automation** restricts automatic commands only, as configured. An explicit manual STOP retains precedence as an immediate user or emergency stop.

### Restart and reload behavior

Restart-relevant state is loaded from Home Assistant's persistent storage before the first automatic room evaluation. This includes per-cover manual-override deadlines, cooldowns, last-known positions, markers for the integration's own position and tilt commands, pending and persistent schedule state, absolute weather-protection timers, bounded provider retry state, and a short-lived target marker for an accepted command whose resulting position had not yet been reported.

Live sensor, sun, contact and cover state is read again and the desired target is recomputed. In-flight Python tasks and queued service calls are not blindly replayed. Position changes that happened while an entity or the integration was unavailable are compared with the previous persisted baseline so that a manual movement is not immediately overwritten by automation.

If an existing persistent safety store is corrupt or semantically invalid, the affected room fails closed: its Config Entry stays not ready until the store is recovered or deliberately cleared, instead of starting without the protection state.

### Release history

Version **`20260903.085028`**, released on 3 September 2026, was the **first public Stable release** of Smart Shading Control.

For a first installation, install Smart Shading Control through HACS or manually and configure it entirely through the Home Assistant user interface. A full Home Assistant restart is required after installation.

The first public release already includes the corrected detection of manual multi-cover operation: the first cover manually operated in a room now reliably receives its manual override as well and is not moved back to an automatic target by a later evaluation. This behavior is independent of whether an opening contact is assigned to that cover.

### Support

- Documentation: https://hilfe.q14six.de/shelves/smart-shading-control
- English help portal: https://help.q14six.de
- Issue tracker: https://github.com/Q14siX/smart_shading_control/issues

Please include the Home Assistant version, integration version, affected room and entities, exact timestamp, relevant logs, downloaded diagnostics, expected behavior and actual behavior.

### Privacy and license

The integration does not require its own cloud service and does not transmit data to Q14siX. It is released under the [MIT License](LICENSE).
