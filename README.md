# ha-pvnode

Home Assistant Integration für den PV-Prognosedienst [pvnode](https://pvnode.com).

Sie orientiert sich an der pvnode-Anbindung des ioBroker-Adapters
[ioBroker.pvforecast](https://github.com/iobroker-community-adapters/ioBroker.pvforecast)
und unterstützt sowohl **API v1** als auch **API v2**.

## Voraussetzungen

- Ein [pvnode](https://pvnode.com)-Konto mit API-Schlüssel.
- Für API v2 (empfohlen) zusätzlich eine unter <https://pvnode.com/sites/new>
  angelegte Site mit mindestens einer konfigurierten Anlage.

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
- Über das „⋮“-Menü des Integrationseintrags → **Neu konfigurieren** lässt sich
  der API-Schlüssel (und bei API v2 die Site-ID) austauschen, ohne den Eintrag
  zu löschen und neu anzulegen.

## Entitäten

Jede Dachfläche wird als **eigenes Gerät** angelegt (nicht zu einer
gemeinsamen Entität zusammengefasst) mit folgenden Sensoren:

- Leistungsprognose (W, aktueller Zeitschritt, inkl. Zeitreihe als Attribut
  `forecast`)
- Energieprognose pro konfiguriertem Prognosetag (heute, morgen, ... –
  richtet sich nach der eingestellten Anzahl Prognosetage)
- Klarhimmel-Leistung **nur bei API v1**, da dort jede Dachfläche einzeln
  abgefragt wird und somit einen echten, eigenen Wert hat

Zusätzlich legt die Integration immer ein **„pvnode“-Übersichtsgerät** an mit:

- Gesamt-Leistungs- und Gesamt-Energieprognose (Summe aller Dachflächen,
  ebenfalls inkl. `forecast`-Attribut)
- Gesamt-Klarhimmel-Leistung (bei API v1 die Summe aller Dachflächen, bei
  API v2 der von pvnode gelieferte Wert für die gesamte Anlage)
- Temperaturprognose und Wettercode

Jeder dieser Sensoren trägt sein eigenes `forecast`-Attribut: eine Liste mit
einem Objekt pro 15-Minuten-Zeitschritt (nur Tageslichtstunden, über alle
konfigurierten Prognosetage), das ausschließlich `datetime` und die eine zu
diesem Sensor passende Kennzahl enthält (`watts`, `watts_clearsky`,
`temperature` bzw. `weather_code`) - bewusst **nicht** in einem einzigen
großen, kombinierten Attribut, damit jedes einzelne Attribut klein bleibt.
Bei API-v2-Dachflächen/Strings gibt es nur `watts`, da pvnode Klarhimmel,
Temperatur und Wettercode dort nicht pro String liefert - am Übersichtsgerät
stehen alle vier Kennzahlen für **beide** API-Versionen zur Verfügung, da sie
dort aus der Summe aller Dachflächen bzw. den Standort-Werten stammen.

Alle `forecast`-Attribute werden bewusst **nicht** vom Recorder in der
History-Datenbank gespeichert (`_unrecorded_attributes`), da sie je nach
Anzahl Prognosetage mehrere KB groß werden können. Für Auswertungen
außerhalb von Home Assistant (z. B. InfluxDB) eignen sie sich trotzdem,
sofern die empfangende Integration selbst auf Zustandsänderungen reagiert
und das jeweilige Attribut ausliest.

Temperatur, Wettercode und (bei API v2) Klarhimmel-Leistung sind
Standort-/Anlageeigenschaften, die pvnode nicht pro Dachfläche/String liefert
– sie erscheinen deshalb ausschließlich am Übersichtsgerät statt an den
einzelnen Dachflächen.

## Energy-Dashboard

Die Integration implementiert die gleiche Schnittstelle wie forecast.solar
und Solcast, um im Energie-Dashboard als **Prognose der Solarerzeugung**
ausgewählt werden zu können:

1. **Einstellungen → Dashboards → Energie** → Solarleistung bearbeiten.
2. Unter „Prognose Solarproduktion“ **pvnode** auswählen.

Die Prognose enthält die kombinierte Leistung **aller Dachflächen** dieses
pvnode-Kontos (nicht einzeln pro Dachfläche, analog dazu wie forecast.solar
und Solcast pro Konfigurationseintrag jeweils eine kombinierte Prognose
liefern). Mehrere Prognosequellen lassen sich im Energie-Dashboard ohnehin
zu einer Solaranlage addieren, falls z. B. ein Teil der Anlage über eine
andere Quelle prognostiziert werden soll.

## Anwendungsfälle

- **Energie-Dashboard**: Solarprognose vs. tatsächliche Erzeugung vergleichen
  (siehe oben).
- **Automatisierungen**: z. B. Verbraucher (Wallbox, Warmwasser) starten, wenn
  `sensor.pvnode_total_power_forecast` einen Schwellenwert übersteigt, oder auf
  Basis der Energieprognose für morgen den Ladezustand eines
  Batteriespeichers planen.
- **Verschattungs-/Ausrichtungsvergleich**: bei mehreren Dachflächen die
  einzelnen Leistungsprognosen gegenüberstellen, um z. B. eine verschattete
  Fläche zu erkennen.

## Bekannte Einschränkungen

- **API v1 wird abgeschaltet** (31.12.2026, siehe oben) – für Neueinrichtungen
  immer API v2 verwenden.
- **Klarhimmel-Leistung, Temperatur und Wettercode** liefert pvnode bei API v2
  nur für die gesamte Anlage, nicht pro Dachfläche/String – diese Werte
  erscheinen deshalb ausschließlich am Übersichtsgerät (siehe „Entitäten“).
- **Kein Discovery**: pvnode ist ein reiner Cloud-Dienst ohne lokale
  Netzwerk-Erkennung (kein mDNS/SSDP/DHCP) – die Integration muss manuell
  eingerichtet werden.
- **Abonnement-Limits werden nicht serverseitig durchgesetzt**: Die
  Abfrageintervalle richten sich nach der gewählten Stufe (Free/Light/Plus),
  ein falsch gewähltes (zu niedriges) Abonnement kann trotzdem zu
  Rate-Limit-Fehlern von pvnode führen.

## Fehlerbehebung

- **Nach einem Update erscheinen neue Funktionen (z. B. Energy-Dashboard,
  neue Sensoren) nicht**: Home Assistant nach jedem Update dieser Integration
  **vollständig neu starten** (nicht nur „Integration neu laden“) – manche
  Erweiterungen (z. B. `energy.py`) werden nur beim vollständigen Start
  erkannt.
- **pvnode erscheint nicht als Prognosequelle im Energie-Dashboard**: sicherstellen,
  dass ein vollständiger Neustart nach der Installation erfolgt ist. Zum
  Prüfen: Entwicklerwerkzeuge der Browser-Konsole → 
  `hass.callWS({type:"energy/info"})` sollte `"pvnode"` unter
  `solar_forecast_domains` auflisten.
- **Fehlermeldung „pvnode rejected the API key“**: API-Schlüssel im
  pvnode-Portal prüfen; die Integration fordert danach automatisch eine
  erneute Anmeldung an (Reauth-Benachrichtigung unter Einstellungen → Geräte
  & Dienste).
- **Diagnosedaten**: über die drei Punkte am Integrationseintrag →
  „Diagnose herunterladen“ lässt sich der interne Zustand (Anzahl geladener
  Zeitreihenwerte je Dachfläche, letzte Aktualisierung, Konfiguration ohne
  API-Schlüssel/Site-ID) für Fehlerberichte exportieren.

## Deinstallation

1. **Einstellungen → Geräte & Dienste → pvnode** → „⋮“-Menü → **Löschen**.
2. Falls manuell installiert: Ordner `custom_components/pvnode` aus der
   Home-Assistant-Konfiguration entfernen.
3. Falls über HACS installiert: pvnode zusätzlich in HACS deinstallieren.
4. Home Assistant neu starten.

Alle von der Integration angelegten Geräte, Entitäten und Reparaturhinweise
werden beim Löschen automatisch entfernt.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
