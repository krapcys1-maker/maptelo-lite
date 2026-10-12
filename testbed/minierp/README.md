# MiniERP — aplikacja testowa

Mały moduł cenowy („Pricing”), który celowo zachowuje się jak kłopotliwy system korporacyjny.
Na nim nagrywamy procesy, testujemy automatyzacje i pokazujemy demo — bez prawdziwych danych firm.

```bash
uv run minierp serve                      # bez chaosu, http://127.0.0.1:8000, konto demo / demo
uv run minierp serve --chaos default      # umiarkowany chaos
uv run minierp serve --chaos heavy --seed 7 --layout b --today 2026-10-07
```

## Proces, który można tu wykonać

Wybierz klienta → wpisz CPN → (jeśli wersji ceny jest kilka) wybierz aktywną → wpisz cenę i datę
„Valid from” → Zapisz (przy zmianie > 20% potwierdź). Dane startowe są liczone względem „dziś”,
więc scenariusze się nie starzeją:

| Klient | CPN | Przypadek |
|---|---|---|
| C001 | 48211-A | jedna wersja ceny — formularz od razu |
| C001 | 48212-B | trzy wersje — trzeba wybrać aktywną |
| C001 | 48213-C | aktywna + zaplanowana na przyszłość |
| C002 | 51002-D | cztery wersje, w tym zaplanowana |
| C003 | 70012-C | wycofany produkt — brak aktywnej wersji (wyjątek biznesowy) |
| dowolny | np. 99999-Z | produkt nie istnieje (wyjątek biznesowy) |

## Chaos (każdy element włączany osobno, deterministyczny dla danego `--seed`)

| Co | Jak włączyć | Co sprawdza |
|---|---|---|
| Okno „Session expiring” w losowym momencie | `session_popup_rate` | obsługę przerwań |
| Spinner 0–N ms przed pokazaniem strony | `slow_load_max_ms` | synchronizację |
| „Price saved”, choć nic nie zapisano | `lying_banner_rate` | weryfikację efektu przez API |
| Układ B: inne etykiety, id, kolumny, przyciski | `layout: b` | drabinę lokatorów i naprawy |
| Potwierdzenie przy zmianie > 20% | zawsze (reguła biznesowa) | gałęzie warunkowe |
| Podwójny zapis tworzy duplikat | zawsze (jak w starych systemach) | idempotencję |
| Błąd 500 przed zapisem | `save_error_rate` | zatrzymanie bez zapisu |
| Zapis, a potem zgubiona odpowiedź (502) | `lost_response_rate` | sprawdzenie odczytem po niejasnym końcu |
| Wolny zapis 0–N ms | `slow_save_max_ms` | limity czasu |
| Odczyt `/api/prices` widzi zmianę po N ms | `read_lag_ms` | spójność „po chwili” |
| Odczyt `/api/prices` zwraca 503 | `read_error_rate` | brak kanału prawdy (nic nie zapisywać na ślepo) |

Preset `--chaos faults` włącza wszystkie kłopoty naraz, umiarkowanie. Laboratorium (`tools/lab.py`, [opis](../../docs/07-laboratorium.md)) losuje je per kampania.

## Scenariusze i nagrania testowe

`minierp.scenarios` opisuje 10 przebiegów procesu zmiany ceny (różne gałęzie, wyjątki, popup,
pomyłki). „Wirtualny użytkownik” (Playwright z pisaniem znak po znaku i pauzami) wykonuje je pod
okiem recordera Maptelo:

```bash
uv run python tools/make_recordings.py            # nagrywa wszystkie do tests/fixtures/recordings/
uv run python tools/make_recordings.py --only 08-session-popup --screenshots
```

Każde nagranie jest sprawdzane przez API (czy cena naprawdę się zmieniła) i czy nie wyciekło hasło.

## API (niezależny kanał odczytu i sterowanie testami)

| Endpoint | Do czego |
|---|---|
| `GET /api/prices?customer=&cpn=&on=YYYY-MM-DD` | cena obowiązująca w dniu (+ `matches` > 1 przy duplikatach) |
| `GET /api/products/{customer}/{cpn}/versions` | wszystkie wersje ze statusem |
| `POST /api/testbed/reset` | przywrócenie danych startowych i ziarna losowości |
| `GET/PUT /api/testbed/chaos` | odczyt / zmiana chaosu w trakcie działania |
| `GET /api/testbed/events` | dziennik decyzji chaosu (prawda do oceny automatyzacji) |
