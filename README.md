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

Aktuelle Version: **`20260903.085028`**  
Veröffentlichungsstatus: **Stable**

[Deutsch](#deutsch) · [English](#english)

---

## Deutsch

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
- optionale Wiederherstellung aktiver manueller Sperren nach einem Neustart
- Trockenlaufmodus ohne physische Fahrbefehle
- virtuelle Raum- und Einzel-Cover
- Status-, Diagnose-, Entscheidungs- und Reparaturentitäten
- optionale Lamellensteuerung für kompatible Cover-Entitäten
- serialisierte Befehlswarteschlange zur Entlastung von Rollladen-Gateways

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

Die Rollläden werden zur Laufzeit ausschließlich nach den in ihrem jeweiligen Raum gespeicherten Vorgaben gesteuert. Die zentrale Konfiguration dient als Verwaltungs- und Übertragungsstelle; sie steuert keinen einzelnen Raum direkt.

#### Räume

Jeder Raum erhält einen eigenen Eintrag mit ausschließlich den Geräten und Einstellungen dieses Raums:

- Raumname und optionaler Raumtemperatursensor
- Rollläden nach Himmelsrichtung
- optional ein Öffnungskontakt je Rollladen
- individuelle Zielpositionen
- individuelle Zeitregeln
- manuelle Sperrzeit
- optionale Speicherung manueller Übersteuerungen
- optionale Lamellenpositionen

Ein Rollladen kann nicht gleichzeitig mehreren Räumen zugeordnet werden.

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
- aktive Sperren können optional über einen Home-Assistant-Neustart erhalten bleiben
- am lokalen Tageswechsel werden temporäre Sperren beendet
- eine neu ausgelöste Zeitregel darf eine ältere manuelle Sperre gezielt ersetzen
- Wiederholungsversuche einer bereits früher ausgelösten Öffnungsregel dürfen eine spätere manuelle Bedienung nicht aufheben

Konfigurierte Sicherheitsmaßnahmen können eine manuelle Sperre übersteuern, wenn dies zum Schutz der Anlage erforderlich ist.

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

### Erstveröffentlichung

Diese Version ist die **erste öffentliche Stable-Veröffentlichung** von Smart Shading Control. Frühere interne Entwicklungs- und Teststände sind keine öffentlichen Releases und werden daher nicht als Update-Historie geführt.

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

**Smart Shading Control** is a Home Assistant custom integration for intelligent, safe and room-based control of shutters and blinds. It is configured entirely through the Home Assistant user interface.

Current version: **`20260903.085028`**  
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
- optional persistence of active manual overrides across restarts
- dry-run mode without physical commands
- virtual room and individual cover entities
- diagnostic, decision, status and repair entities
- optional tilt control for supported covers
- serialized command queue to avoid overloading cover gateways

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

At runtime, covers are controlled exclusively by the values stored in their own room entry. The central entry is a management and transfer interface; it does not directly control one selected room.

Each room contains only its own covers, contacts, temperature sensor, positions, schedules and manual override settings. A physical cover cannot be assigned to more than one room.

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

The default duration is 240 minutes. It can be transferred globally and changed per room afterwards. Active overrides may optionally survive a Home Assistant restart. Safety protection may still enforce a safer position when required.

### First public release

This version is the **first public Stable release** of Smart Shading Control. Earlier internal development and test builds are not public releases and are therefore not presented as an upgrade history.

For a first installation, install Smart Shading Control through HACS or manually and configure it entirely through the Home Assistant user interface. A full Home Assistant restart is required after installation.

The first public release already includes the corrected detection of manual multi-cover operation: the first cover manually operated in a room now reliably receives its manual override as well and is not moved back to an automatic target by a later evaluation. This behavior is independent of whether an opening contact is assigned to that cover.

### Support

- Documentation: https://hilfe.q14six.de/shelves/smart-shading-control
- English help portal: https://help.q14six.de
- Issue tracker: https://github.com/Q14siX/smart_shading_control/issues

Please include the Home Assistant version, integration version, affected room and entities, exact timestamp, relevant logs, downloaded diagnostics, expected behavior and actual behavior.

### Privacy and license

The integration does not require its own cloud service and does not transmit data to Q14siX. It is released under the [MIT License](LICENSE).
