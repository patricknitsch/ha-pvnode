# ha-pvnode

Home Assistant Integration für den PV-Prognosedienst [pvnode](https://pvnode.com).

Sie orientiert sich an der pvnode-Anbindung des ioBroker-Adapters
[ioBroker.pvforecast](https://github.com/iobroker-community-adapters/ioBroker.pvforecast)
und unterstützt sowohl **API v1** als auch **API v2**.

## Installation

### Über HACS (empfohlen)

1. HACS → Integrationen → Menü „⋮“ → „Benutzerdefinierte Repositories“.
2. Dieses Repository (`patricknitsch/ha-pvnode`) als Repository vom Typ
   „Integration“ hinzufügen.
3. „pvnode“ installieren und Home Assistant neu starten.

### Manuell

1. Ordner `custom_components/pvnode` in das `custom_components`-Verzeichnis
   deiner Home-Assistant-Konfiguration kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „pvnode“** wählen.

## Einrichtung

Beim Hinzufügen der Integration wählst du zunächst die **API-Version**:

### API v2 (empfohlen)

- Nur der **API-Schlüssel** und die **Site-ID** aus dem pvnode-Portal
  (erstellbar unter <https://pvnode.com/sites/new>) werden benötigt.
- Die **Dachflächen** (Ausrichtung, Neigung, Leistung) sind bereits im
  pvnode-Portal hinterlegt und werden **automatisch abgerufen** – jede
  konfigurierte Anlage erscheint als eigene Dachfläche in Home Assistant,
  ganz ohne weitere lokale Konfiguration.
- Neue, im Portal hinzugefügte Dachflächen werden bei einer der folgenden
  Aktualisierungen automatisch als neue Geräte in Home Assistant angelegt.

### API v1 (veraltet)

pvnode schaltet API v1 zum **31.12.2026** ab; ab dem 01.01.2027 liefert diese
Integration dann keine Daten mehr über v1. Nutze für Neueinrichtungen API v2.

- Für jede Dachfläche werden **Name, Azimut, Neigung und Spitzenleistung**
  manuell eingegeben (kann direkt im Einrichtungsdialog wiederholt werden,
  um mehrere Dachflächen anzulegen).
- Azimut-Konvention wie bei forecast.solar: `-180/180=Norden, -90=Osten,
  0=Süden, 90=Westen`.
- Standort wird aus der Home-Assistant-Konfiguration übernommen.

### Gemeinsame Einstellungen

- **Abonnementstufe** (Free/Light/Plus) – bestimmt automatisch das
  Abfrageintervall (Free: 24 h, Light: 60 min, Plus: 10 min) sowie das
  maximale Prognosefenster (Free: 2 Tage, Light/Plus: 7 Tage).
- **Anzahl Prognosetage** – wird passend zur gewählten Stufe begrenzt.
- Über **Einstellungen → Integration konfigurieren** lassen sich Abonnement,
  Prognosetage und (bei API v1) Dachflächen jederzeit nachträglich anpassen.

## Entitäten

Jede Dachfläche wird als **eigenes Gerät** angelegt (nicht zu einer
gemeinsamen Entität zusammengefasst) mit folgenden Sensoren:

- Leistungsprognose (W, aktueller Zeitschritt, inkl. Zeitreihe als Attribut)
- Energieprognose pro konfiguriertem Prognosetag (heute, morgen, ... –
  richtet sich nach der eingestellten Anzahl Prognosetage)
- Klarhimmel-Leistung **nur bei API v1**, da dort jede Dachfläche einzeln
  abgefragt wird und somit einen echten, eigenen Wert hat

Zusätzlich legt die Integration immer ein **„pvnode“-Übersichtsgerät** an mit:

- Gesamt-Leistungs- und Gesamt-Energieprognose (Summe aller Dachflächen)
- Gesamt-Klarhimmel-Leistung (bei API v1 die Summe aller Dachflächen, bei
  API v2 der von pvnode gelieferte Wert für die gesamte Anlage)
- Temperaturprognose und Wettercode

Temperatur, Wettercode und (bei API v2) Klarhimmel-Leistung sind
Standort-/Anlageeigenschaften, die pvnode nicht pro Dachfläche/String liefert
– sie erscheinen deshalb ausschließlich am Übersichtsgerät statt an den
einzelnen Dachflächen.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
