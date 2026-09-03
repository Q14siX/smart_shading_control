<p align="center">
  <img src="https://raw.githubusercontent.com/Q14siX/smart_shading_control/main/custom_components/smart_shading_control/brand/icon.png" alt="Smart Shading Control Icon">
</p>

# Smart Shading Control – Release Notes

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
