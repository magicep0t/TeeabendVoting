# TeeabendVoting 🗳️

Ein erweiterter, interaktiver Telegram-Voting-Bot zur Erstellung, Durchführung und Auswertung von Umfragen mit Echtzeit-Aktualisierung, Diagrammen und interaktiven Menüs.

---

## Inhaltsverzeichnis

- [Features](#features)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Bot starten](#bot-starten)
- [Befehlsübersicht](#befehlsübersicht)
- [Nutzungsbeispiele](#nutzungsbeispiele)
- [Persistenz & Datenspeicherung](#persistenz--datenspeicherung)
- [Tests ausführen](#tests-ausführen)
- [Lizenz](#lizenz)

---

## Features

- 🗳️ **Interaktive Umfragen:** Inline-Buttons zur einfachen Stimmabgabe direkt in Telegram.
- 🔄 **Stimmenänderung:** Nutzer können ihre Stimme jederzeit anpassen oder korrigieren.
- ⚡ **Live-Ergebnisse:** Live-Aktualisierung der Stimmenanzahl direkt auf der Umfragenachricht.
- ⏱️ **Zeitlimits & Ablauf:** Unterstützung für frei wählbare Fristen (in Minuten) mit automatischem Schließen abgelaufener Umfragen oder unbegrenzte Laufzeiten (`0`).
- 📊 **Grafische & textuelle Statistiken:** Ausgabe von Balkendiagrammen (*Bar Chart*) oder Tortendiagrammen (*Pie Chart*) via Matplotlib.
- 🏆 **Schnellergebnis `/results`:** Sofortige Auswertung mit Anzeige des aktuellen Spitzenreiters oder Gleichstands (*Tie*).
- 📜 **Umfrage-Historie:** Übersicht aller in der Gruppe erstellten Umfragen.
- 📱 **Typografische Anführungszeichen:** Automatische Erkennung normaler (`"..."`) sowie typografischer Anführungszeichen (`“...”`, `‘...’`).
- 💾 **Robuste Persistenz:** Atomare JSON-Speicherung, kein Datenverlust bei Neustarts oder Systemabstürzen.
- ⚙️ **Konfigurierbar:** Einfache Konfiguration über Umgebungsvariablen.

---

## Voraussetzungen

- **Python 3.10+** (getestet mit Python 3.12)
- Telegram Bot Token von [@BotFather](https://t.me/BotFather)

---

## Installation

1. **Repository klonen:**
   ```bash
   git clone https://github.com/magicep0t/TeeabendVoting.git
   cd TeeabendVoting
   ```

2. **Virtuelle Umgebung erstellen und aktivieren (empfohlen):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Auf Windows: venv\Scripts\activate
   ```

3. **Abhängigkeiten installieren:**
   ```bash
   pip install -r requirements.txt
   ```
   *Optional für Entwicklung & Tests:*
   ```bash
   pip install -r requirements-dev.txt
   ```

---

## Konfiguration

Der Bot liest die Konfiguration aus Umgebungsvariablen:

| Variable | Beschreibung | Standardwert |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Dein Telegram-Bot-Token von BotFather | *(erforderlich)* |
| `POLLS_DATA_FILE` | Dateipfad für persistente Umfragedaten | `telegram_bot_polls_data.json` |
| `DEFAULT_POLL_DURATION_MINUTES` | Standardlaufzeit für Umfragen in Minuten | `5` |

### Beispiel (Linux/macOS):
```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
export POLLS_DATA_FILE="polls_data.json"
```

### Beispiel (Windows PowerShell):
```powershell
$env:TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
```

---

## Bot starten

```bash
python -m telegram_voting_bot.bot
```
Oder direkt:
```bash
python telegram_voting_bot/bot.py
```

---

## Befehlsübersicht

| Befehl | Beschreibung | Beispiel |
| :--- | :--- | :--- |
| `/start` | Zeigt das Hilfemenü und alle Befehle an. | `/start` |
| `/menu` | Öffnet das interaktive Inline-Hauptmenü. | `/menu` |
| `/startpoll [Minuten] "Thema" "Opt 1" "Opt 2" ...` | Startet eine neue Umfrage mit Inline-Tasten. | `/startpoll 30 "Lieblings-Tee" "Grüntee" "Schwarztee" "Kamille"` |
| `/endpoll <poll_id>` | Beendet eine aktive Umfrage manuell (nur Ersteller). | `/endpoll 5a3f...` |
| `/results <poll_id>` | Schnelle Textauswertung mit Gewinner / Gleichstand. | `/results 5a3f...` |
| `/pollstats <poll_id> [bar\|pie]` | Detaillierte Statistiken inkl. Diagramm (Balken oder Torte). | `/pollstats 5a3f... pie` |
| `/pollhistory` | Listet bisherige Umfragen im aktuellen Chat auf. | `/pollhistory` |

---

## Nutzungsbeispiele

### 1. Umfrage mit Zeitlimit erstellen
```
/startpoll 60 "Nächster Termin?" "Freitag 18:00" "Samstag 15:00" "Sonntag 11:00"
```
Erstellt eine Umfrage, die nach 60 Minuten automatisch schließt und das Voting beendet.

### 2. Umfrage ohne Zeitlimit erstellen
```
/startpoll 0 "Lieblings-Programmiersprache?" "Python" "Rust" "Go" "TypeScript"
```

### 3. Diagramm abrufen
```
/pollstats a1b2c3d4e5 pie
```
Sendet ein hübsch formatiertes Tortendiagramm als Bild in den Chat.

---

## Persistenz & Datenspeicherung

- Bei jeder Abstimmung, Erstellung oder Beendigung wird der Zustand atomar in der JSON-Datei (`POLLS_DATA_FILE`) gesichert.
- Alle `user_id`-Zuordnungen bleiben beim Neuladen typkorrekt als Integer erhalten.
- Beim Beenden des Bots (z. B. via `SIGINT`/`Ctrl+C`) wird der aktuelle Zustand nochmals garantiert gespeichert.

---

## Tests ausführen

Zur Überprüfung aller Komponenten stehen automatisierte Tests mit `pytest` bereit:

```bash
pytest -v
```

Ergebnis:
```
tests/test_bot.py::test_quote_parsing PASSED
tests/test_bot.py::test_persistence_serialization_deserialization PASSED
tests/test_bot.py::test_format_poll_message PASSED
tests/test_bot.py::test_chart_generation PASSED
tests/test_bot.py::test_start_command PASSED
tests/test_bot.py::test_startpoll_command PASSED
tests/test_bot.py::test_button_callback_voting_and_vote_change PASSED
tests/test_bot.py::test_endpoll_permission_and_execution PASSED
tests/test_bot.py::test_results_command PASSED
tests/test_bot.py::test_pollhistory_from_callback_query PASSED
tests/test_bot.py::test_check_active_polls_expiry PASSED
```

---

## Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE).
