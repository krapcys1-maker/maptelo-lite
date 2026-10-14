"""Studio speaks Polish; Maptelo's core and command line speak English. What the core says
on its way to the page is translated here, by the shape of the sentence: what a sentence
names (a step, a value, an address, an exception, a file) is kept as it is, and a sentence
inside another (a reason, a detail) is translated in turn. A sentence not known here stays
in English rather than becoming something it does not say; a test lists every sentence the
core can say and fails when one has no Polish yet.
"""

from __future__ import annotations

import re
from functools import cache

SENTENCES: list[tuple[str, str]] = [
    ("the selected table cell cannot be read", "nie da się odczytać wybranej komórki tabeli"),
    ("the checkbox column cannot be found", "nie znaleziono kolumny z polem wyboru"),
    ("the checkbox table cannot be read", "nie da się odczytać tabeli z polem wyboru"),
    ("the chosen cell is not an enabled checkbox",
     "wybrana komórka nie jest dostępnym polem wyboru"),
    ("the checkbox did not reach the requested state", "pole wyboru nie osiągnęło żądanego stanu"),
    ("{where}: {count} matching rows; expected one",
     "{where}: pasuje {count} wierszy; oczekiwano jednego"),
    ("invalid secret value", "nieprawidłowa wartość poufna"),
    ("missing expected field: {field}", "brak oczekiwanego pola: {field}"),
    ("{path}: another worker is running this batch", "{path}: inny proces wykonuje już ten wsad"),
    # a run
    ("already done: the effect holds, nothing was written",
     "już zrobione: efekt jest w systemie, nic nie zapisano"),
    ("confirmed by an independent read after an unclear ending ({message})",
     "potwierdzone niezależnym odczytem po niejasnym zakończeniu ({message})"),
    ("cannot check whether this was already done ({detail}); nothing was written",
     "nie da się sprawdzić, czy to już zrobione ({detail}); nic nie zapisano"),
    ("the process keeps jumping between steps", "proces krąży między krokami"),
    ("the model declares no effect to verify", "model nie mówi, jak sprawdzić wynik"),
    ("effect '{effect}' not confirmed: {detail}", "efekt „{effect}” niepotwierdzony: {detail}"),
    (
        "effect '{effect}' not confirmed yet after “{step}” ({detail}); the steps left write "
        "nothing: read again at the end",
        "efekt „{effect}” jeszcze niepotwierdzony po „{step}” ({detail}); pozostałe kroki "
        "niczego nie zapisują: odczyt ponowiony na końcu",
    ),
    ("every effect confirmed by an independent read",
     "każdy efekt potwierdzony niezależnym odczytem"),
    ("“{step}” needs a decision ({executor}): there is no rule for it yet",
     "„{step}” wymaga decyzji ({executor}): nie ma jeszcze na to reguły"),
    ("“{step}” is a person's on this way of the process (its rule held): the robot stops "
     "before it",
     "„{step}” na tej drodze procesu robi człowiek (jej reguła się spełniła): robot staje "
     "przed tym krokiem"),
    ("dry run: stopped before “{step}”", "próba bez zapisu: zatrzymany przed „{step}”"),
    ("{message} (the application asks to sign in: the saved session has expired or is missing; "
     "sign in again with 'maptelo session save')",
     "{message} (aplikacja prosi o zalogowanie: robot nie ma zapisanego logowania albo ono "
     "wygasło; zaloguj się raz w Studio, w „Gotowości”)"),
    ("before “{step}” the screen is not as in every recording ({shown}): work left from before "
     "may be on it",
     "przed „{step}” ekran nie jest taki jak w każdym pokazie ({shown}): może na nim być praca "
     "pozostawiona wcześniej"),
    ("the screen is not as recorded", "ekran nie jest taki jak w pokazach"),
    ("“{step}” is chosen only when {shown}, and here it is not: no recording showed when "
     "{others} is chosen, a person decides",
     "„{step}” wybiera się tylko wtedy, gdy {shown}, a tutaj tak nie jest; pokazy nie mówią, "
     "kiedy wybiera się {others}, więc decyzję podejmuje człowiek"),
    ("the decision's rule does not hold", "reguła decyzji nie jest spełniona"),
    ("“{step}” needs {called} from the record, and the record has none",
     "„{step}” potrzebuje z rekordu wartości „{called}”, a rekord jej nie ma"),
    ("a value of the record is missing", "w rekordzie brakuje wartości"),
    # values read after their words in a sentence
    ("different values follow “{words}” on the screen ({values}): which one is meant is for "
     "a person to say",
     "po słowach „{words}” stoją na ekranie różne wartości ({values}): którą wziąć, "
     "rozstrzyga człowiek"),
    ("nothing on the screen follows the words “{words}”",
     "na ekranie nic nie stoi po słowach „{words}”"),
    ("the words “{words}”", "słowa „{words}”"),
    # windows over the main one, and the browser's own questions
    ("its window (one an earlier step opened) is not open: nothing is done in another "
     "window instead",
     "jego okno (otwarte przez wcześniejszy krok) nie jest otwarte: robot nie robi tego "
     "w innym oknie"),
    ("the window it opens did not open", "okno, które otwiera, się nie otworzyło"),
    ("its window did not close", "jego okno się nie zamknęło"),
    ("its window did not close{shows}", "jego okno się nie zamknęło{shows}"),
    ("“{step}”: the application asked “{question}” ({kind}), which no recording answered; "
     "it was cancelled, the rest is for a person",
     "„{step}”: aplikacja zapytała „{question}” ({kind}), a w żadnym pokazie nikt na to nie "
     "odpowiadał; pytanie anulowano, resztę zrobi człowiek"),
    ("the application asked “{question}” ({kind})",
     "aplikacja zapytała „{question}” ({kind})"),
    ("step {step}: the application did not ask “{question}” this time",
     "krok {step}: aplikacja tym razem nie zapytała „{question}”"),
    ("step {step}: the application said “{question}”",
     "krok {step}: aplikacja pokazała „{question}”"),
    ("between steps the application said “{question}”",
     "między krokami aplikacja pokazała „{question}”"),
    ("between steps the application asked “{question}”: cancelled",
     "między krokami aplikacja zapytała „{question}”: anulowano"),
    ("“{step}” later in the process needs a person: the robot does not start a record it cannot "
     "finish (nothing written)",
     "„{step}” dalej w procesie robi człowiek: robot nie zaczyna rekordu, którego nie dokończy "
     "(nic nie zapisano)"),
    ("none of the expected outcomes appeared", "nie pojawił się żaden z oczekiwanych wyników"),
    # Java programs (the Access Bridge)
    ("the expected result did not appear{shows}", "oczekiwany wynik się nie pojawił{shows}"),
    ("none of the expected outcomes appeared{shows}",
     "nie pojawił się żaden z oczekiwanych wyników{shows}"),
    ("the program shows “{title}”, left from the record before: a person looks at it",
     "program pokazuje „{title}”, pozostałe po poprzednim rekordzie: człowiek musi to obejrzeć"),
    ("the program shows “{title}”{words}", "program pokazuje „{title}”{words}"),
    ("not started: {reason}", "nie rozpoczęto: {reason}"),
    ("the record before ended unclear: a person looks at the program before the robot goes on",
     "poprzedni rekord skończył się niejasno: zanim robot pójdzie dalej, człowiek sprawdza "
     "program"),
    ("the program already shows “{title}”, which the recordings opened themselves: close it "
     "(save what is in it first), then run again",
     "program już pokazuje „{title}”, a w pokazach to okno otwierano dopiero w trakcie: zamknij "
     "je (najpierw zapisz, co w nim jest) i uruchom ponownie"),
    ("the frame “{title}” an earlier record opened is behind “{front}”: a person closes it",
     "ramka „{title}” otwarta przez wcześniejszy rekord jest za „{front}”: zamknie ją człowiek"),
    ("the frame “{title}” an earlier record opened: {problem}",
     "ramka „{title}” otwarta przez wcześniejszy rekord: {problem}"),
    ("the frame “{title}” does not close", "ramka „{title}” się nie zamyka"),
    ("“{title}” is not in front (“{front}” is)", "„{title}” nie jest na wierzchu (jest „{front}”)"),
    ("closing “{title}” asks “{question}”: for a person",
     "zamknięcie „{title}” pyta „{question}”: odpowie człowiek"),
    # the result read again in the program
    ("nothing was written ({detail})", "nic nie zapisano ({detail})"),
    ("read on a screen of the program", "odczyt na ekranie programu"),
    ("read again on {where}", "odczytane ponownie: {where}"),
    ("cannot open {where}: {problem}", "nie da się otworzyć {where}: {problem}"),
    ("the menu has no item {item}", "w menu nie ma pozycji {item}"),
    ("{where} shows no table with {columns}", "{where} nie pokazuje tabeli z kolumnami: {columns}"),
    ("{where}: no row with {values}", "{where}: nie ma wiersza z {values}"),
    ("the screen was open before the check: its list may be old",
     "ekran był otwarty przed sprawdzeniem: jego lista może być nieaktualna"),
    ("the screen stays open ({problem})", "ekran zostaje otwarty ({problem})"),
    ("{problem}, left from the record before", "{problem}, pozostałe po poprzednim rekordzie"),
    ("“{title}” waits for a person (its buttons: {buttons})",
     "„{title}” czeka na człowieka (przyciski: {buttons})"),
    ("“{title}” does not close", "„{title}” się nie zamyka"),
    ("the Java program does not answer (a window it opened may be waiting): a person looks at "
     "it",
     "program Java nie odpowiada (może czekać okno, które otworzył): człowiek musi to obejrzeć"),
    ("the Java program does not answer (a window it opened may be waiting)",
     "program Java nie odpowiada (może czekać okno, które otworzył)"),
    ("the Java program still does not answer (a window it opened may be waiting)",
     "program Java nadal nie odpowiada (może czekać okno, które otworzył)"),
    ("no {dll} or {other} in the Java folders", "nie ma {dll} ani {other} w folderach Javy"),
    ("the Java here has only {dll} ({bits}-bit), which this {own}-bit Python cannot load, and "
     "no Python of its bitness was found to load it: install Maptelo again (it brings one "
     "along) or Python 3.12 of that bitness for this user",
     "Java na tym komputerze ma tylko {dll} ({bits} bity), którego ten Python ({own} bity) nie "
     "załaduje, a nie znaleziono Pythona tej samej bitowości, który mógłby go załadować: "
     "zainstaluj ponownie Maptelo (zawiera taki Python) albo zainstaluj dla tego "
     "użytkownika Pythona 3.12 o tej bitowości"),
    ("starting the helper Python {python}", "uruchamianie pomocniczego Pythona {python}"),
    ("the helper Python {python} does not start: {reason}",
     "pomocniczy Python {python} nie uruchamia się: {reason}"),
    ("the helper of the Java Access Bridge ended{words}",
     "proces pomocniczy Java Access Bridge zakończył działanie{words}"),
    ("the Java Access Bridge could not start: {reason}",
     "Java Access Bridge nie mógł wystartować: {reason}"),
    ("the Java Access Bridge did not start ({reason})",
     "Java Access Bridge nie wystartował ({reason})"),
    ("the Java Access Bridge works on Windows only", "Java Access Bridge działa tylko w Windows"),
    ("cannot work on the desktop {desktop}", "nie da się pracować na pulpicie {desktop}"),
    ("window {window} does not answer through the bridge",
     "okno {window} nie odpowiada przez most"),
    ("window {window} has no accessible root", "okno {window} nie ma korzenia dostępności"),
    ("the element at {path} is gone (window changed)",
     "element pod {path} zniknął (okno się zmieniło)"),
    ("{role} {name} is no longer there ({other} instead)",
     "{role} {name} już tam nie ma (jest {other})"),
    ("{element} takes no focus and opens a window: no field beside it to open it from with the "
     "keyboard",
     "{element} nie przyjmuje fokusu i otwiera okno: obok nie ma pola, z którego można je "
     "otworzyć klawiszem"),
    ("{element} takes no focus, and its field opens no window with F9 or Ctrl+L",
     "{element} nie przyjmuje fokusu, a jego pole nie otwiera okna ani F9, ani Ctrl+L"),
    ("“{title}” is over the window: no key is sent",
     "„{title}” jest nad oknem: robot nie wysyła klawiszy"),
    ("“{title}” is over the main window: no key is sent",
     "„{title}” jest nad oknem głównym: robot nie wysyła klawiszy"),
    ("after the last step the program still shows a window: “{window}”{shows}",
     "po ostatnim kroku program nadal pokazuje okno: „{window}”{shows}"),
    ("{element}: the table cannot be read", "{element}: nie da się odczytać tabeli"),
    (
        "{element}: a double click needs the cell's place",
        "{element}: do dwukliku potrzebne jest położenie komórki na ekranie",
    ),
    (
        "{element}: a click where its row should be chose row(s) {chosen}, not {row}; nothing "
        "was opened",
        "{element}: kliknięcie w miejscu, w którym powinien być jego wiersz, wybrało wiersze "
        "{chosen}, a nie {row}; niczego nie otwarto",
    ),
    ("{element} is not chosen after choosing it", "{element} nie jest wybrany mimo wyboru"),
    ("closing “{title}” changed other frames ({frames})",
     "zamknięcie „{title}” zmieniło inne ramki ({frames})"),
    ("the frames earlier records opened did not close",
     "ramki otwarte przez wcześniejsze rekordy się nie zamknęły"),
    ("the status line says: {text}", "pasek stanu mówi: {text}"),
    ("the status line: {said}", "pasek stanu: {said}"),
    ("before “{step}” the program shows a window no recording showed: “{window}”{shows}",
     "przed „{step}” program pokazuje okno, którego nie było w żadnym pokazie: "
     "„{window}”{shows}"),
    ("no Java window titled like {pattern}: open the program (with the Java Access Bridge on) "
     "and run again",
     "nie ma okna Javy o tytule jak {pattern}: otwórz program (z włączonym Java Access "
     "Bridge) i uruchom ponownie"),
    ("the model declares no effect to verify (the program has no other way to read what was "
     "saved)",
     "model nie mówi, jak sprawdzić wynik (program nie ma innej drogi odczytu tego, co "
     "zapisano)"),
    ("'{action}' is not done in Java programs yet",
     "czynności „{action}” robot nie wykonuje jeszcze w programach Java"),
    ("nothing on the screen matches {rungs}", "nic na ekranie nie pasuje do: {rungs}"),
    ("{locator} matches {count} elements", "{locator} pasuje do {count} elementów"),
    ("{element} does not take the focus (it is on {other}); nothing was typed or pressed",
     "{element} nie przyjmuje fokusu (jest na {other}); nic nie wpisano ani nie naciśnięto"),
    ("{element} shows {shown} after typing {value}",
     "{element} pokazuje {shown} po wpisaniu {value}"),
    ("{element} shows {shown} after choosing {value}",
     "{element} pokazuje {shown} po wybraniu {value}"),
    ("{element} can neither take the focus nor be pressed",
     "{element} nie przyjmuje fokusu i nie da się go nacisnąć"),
    ("{element}: its list is not on the screen", "{element}: jego listy nie ma na ekranie"),
    ("{element} has no item {item} ({items})", "{element} nie ma pozycji {item} ({items})"),
    ("{item} is not in the menu {menu}", "{item}: tej pozycji nie ma w menu {menu}"),
    ("{item}: the menu {menu} did not take the keys that choose it (it stayed open, and was "
     "closed)",
     "{item}: menu {menu} nie przyjęło klawiszy, które wybierają pozycję (zostało otwarte, "
     "więc je zamknięto)"),
    ("the menu “{menu}” is open", "menu „{menu}” jest otwarte"),
    ("the application refused the record, which no recording showed: {refusal}; nothing "
     "was written ({checked})",
     "aplikacja odmówiła przyjęcia rekordu, czego nie pokazało żadne nagranie: {refusal}; "
     "nic nie zapisano ({checked})"),
    ("the program refused the record, which no recording showed: {refusal}; nothing was "
     "written ({checked})",
     "program odmówił przyjęcia rekordu, czego nie pokazało żadne nagranie: {refusal}; nic "
     "nie zapisano ({checked})"),
    ("the window “{name}”, which no recording showed, lay over “{step}”: answered with "
     "“{choice}” (no consent beyond what the site needs)",
     "okno „{name}”, którego nie pokazało żadne nagranie, zasłaniało krok „{step}”: wybrano "
     "„{choice}” (bez zgód ponad niezbędne)"),
    ("the row where {said} is not in the table “{table}”, which has no further pages; "
     "nothing was written ({checked})",
     "wiersza, w którym {said}, nie ma w tabeli „{table}”, a tabela nie ma dalszych stron; "
     "nic nie zapisano ({checked})"),
    ("the application warned that the session expires: “{button}” kept it",
     "aplikacja ostrzegła, że sesja wygasa: „{button}” ją przedłużył"),
    ("the save did not happen: {count} lines this record had added to “{table}” were taken "
     "out again",
     "zapis się nie udał: {count} pozycji dodanych przez ten rekord do „{table}” usunięto"),
    ("{count} could not be taken out", "{count} nie dało się usunąć"),
    ("every effect confirmed by an independent read (a moment after the first read)",
     "każdy efekt potwierdzony niezależnym odczytem (chwilę po pierwszym odczycie)"),
    ("open but not shown: {frames}", "otwarte, ale niewidoczne: {frames}"),
    ("the window has no menu bar", "okno nie ma paska menu"),
    ("the menu bar has no menu {menu}", "na pasku menu nie ma menu {menu}"),
    ("the item {item} is in {count} menus: the model has to say which",
     "pozycja {item} jest w {count} menu: model musi powiedzieć, w którym"),
    ("no suggestion contains “{value}”", "żadna podpowiedź nie zawiera „{value}”"),
    ("the expected result did not appear", "oczekiwany wynik się nie pojawił"),
    ("step {step}: {old} now finds {shown}, not {new}; a step that saves is not done on it",
     "krok {step}: {old} znajduje teraz {shown}, a nie {new}; krok, który zapisuje, "
     "nie zostanie na tym wykonany"),
    ("{element} is not visible on the screen", "{element} nie jest widoczny na ekranie"),
    ("{first} and {second} find different elements: the screen changed, and which one is meant "
     "is for a person (or a repair) to say",
     "{first} i {second} wskazują różne elementy: ekran się zmienił, a który jest właściwy, "
     "decyduje człowiek (albo naprawa)"),
    ("{element} does not match exactly one visible element{where}",
     "{element} nie wskazuje dokładnie jednego widocznego elementu{where}"),
    ("the element has no readable name (it is an icon): pick one named in words",
     "element nie ma czytelnej nazwy (to ikona): wybierz taki, który ma nazwę słowami"),
    ("a step that saves needs an element named in words, not a symbol",
     "krok, który zapisuje, potrzebuje elementu nazwanego słowami, nie symbolem"),
    ("the agent found nothing that fits “{step}”",
     "agent nie znalazł niczego, co pasuje do „{step}”"),
    ("the agent found nothing", "agent niczego nie znalazł"),
    ("its element changed: a person must decide",
     "jego element się zmienił: musi zdecydować człowiek"),
    ("“{step}” is irreversible and its element changed: accept the proposed repair "
     "(maptelo repairs accept) before it can run",
     "„{step}” jest nieodwracalny, a jego element się zmienił: przyjmij proponowaną naprawę "
     "(zakładka „Naprawy”), zanim przebieg ruszy"),
    ("the first way to find the element no longer works; a lower one still does",
     "pierwszy sposób znalezienia elementu już nie działa; dalszy wciąż tak"),
    ("“{step}”: its button is now called “{name}” ({how}); accept the proposed repair "
     "before it saves",
     "„{step}”: jego przycisk nazywa się teraz „{name}” ({how}); przyjmij proponowaną naprawę "
     "(zakładka „Naprawy”), zanim zapisze"),
    ("it sends the same form", "wysyła ten sam formularz"),
    ("its words hold the old ones", "jego nowe słowa zawierają dawne"),
    ("a button whose new words hold the old ones: proposed, not pressed",
     "przycisk, którego nowe słowa zawierają dawne: zaproponowany, nie naciśnięty"),
    ("the chosen repair is no longer proposed", "wybranej naprawy już nie ma wśród propozycji"),
    ("dry run: “{step}” tried to send data to the application ({sent}) and it was not "
     "sent; the model does not know this step saves: record the process again or mark the "
     "step as saving (risk: commit)",
     "próba bez zapisu: „{step}” próbował wysłać dane do aplikacji ({sent}) i nie zostały "
     "wysłane; model nie wie, że ten krok zapisuje: nagraj proces jeszcze raz albo oznacz "
     "krok jako zapisujący (risk: commit)"),
    ("it tried to send data to the application ({sent})",
     "próbował wysłać dane do aplikacji ({sent})"),
    ("step {step}: it sent data to the application ({sent}) although it is not marked as "
     "saving",
     "krok {step}: wysłał dane do aplikacji ({sent}), choć nie jest oznaczony jako zapisujący"),
    ("there is no file {path}", "nie ma pliku {path}"),
    ("“{given}” is no date to pick in a calendar",
     "„{given}” to nie data do wybrania w kalendarzu"),
    ("the calendar shows no days", "kalendarz nie pokazuje dni"),
    ("the calendar did not move towards “{wanted}”",
     "kalendarz nie przesunął się w stronę „{wanted}”"),
    ("the day “{wanted}” cannot be picked in the calendar",
     "dnia „{wanted}” nie da się wybrać w kalendarzu"),
    ("the calendar shows the month, but no day “{wanted}” to click",
     "kalendarz pokazuje ten miesiąc, ale nie ma w nim dnia „{wanted}” do kliknięcia"),
    ("the calendar cannot be moved towards “{wanted}”",
     "kalendarza nie da się przesunąć w stronę „{wanted}”"),
    ("the calendar did not reach “{wanted}”", "kalendarz nie doszedł do „{wanted}”"),
    ("“{intent}” is a check a person makes (four eyes): the robot stops before it",
     "„{intent}” to kontrola, którą robi człowiek (cztery oczy): robot zatrzymuje się przed tym "
     "krokiem"),
    ("step {step}: no suggestion contains “{value}”; it was left typed, as people did",
     "krok {step}: żadna podpowiedź nie zawiera „{value}”; wartość zostaje wpisana, jak "
     "robili to ludzie"),
    ("its button has new words: a person must decide",
     "jego przycisk ma nowe słowa: musi zdecydować człowiek"),
    ("the button that sends the same form, under new words: proposed, not pressed",
     "przycisk, który wysyła ten sam formularz, pod nowymi słowami: zaproponowany, nie naciśnięty"),
    ("its words changed; a way to find it that does not depend on them still does",
     "zmieniły się jego słowa; sposób znalezienia, który od nich nie zależy, wciąż działa"),
    ("the only column holding “{value}”", "jedyna kolumna z wartością „{value}”"),
    ("ladder: {how}", "drabina: {how}"),
    ("person: {who}", "osoba: {who}"),
    ("the interrupt handler could not find its button",
     "obsługa przerwania nie znalazła swojego przycisku"),
    ("condition not met", "warunek niespełniony"),
    ("not on the expected screen '{state}'", "to nie jest oczekiwany ekran „{state}”"),
    ("not on the expected screen '{state}'{shows}",
     "to nie jest oczekiwany ekran „{state}”{shows}"),
    ("no unique visible element for {tried}", "brak jednego widocznego elementu dla: {tried}"),
    ("{count} rows match {where}; the model says pick only one",
     "pasujących wierszy: {count} ({where}); model każe wybrać tylko jeden"),
    ("{element} in the row where {where}", "{element} w wierszu, gdzie {where}"),
    ("{element} in rows {where}", "{element} w wierszach {where}"),
    ("no row fits", "żaden wiersz nie pasuje"),
    ("a step done in each row of a table has no one element",
     "krok wykonywany w każdym wierszu tabeli nie ma jednego elementu"),
    ("the table has no column {columns}", "tabela nie ma kolumny {columns}"),
    ("the table “{table}” is not on the screen", "tabeli „{table}” nie ma na ekranie"),
    ("{element} in each row that fits", "{element} w każdym pasującym wierszu"),
    ("the table “{table}” is not on the screen{shows}",
     "tabeli „{table}” nie ma na ekranie{shows}"),
    # a batch
    ("stopped on request; run again to do the rest",
     "zatrzymano na prośbę; uruchom ponownie, żeby zrobić resztę"),
    ("stopped after {count} system failures in a row; the application may be down",
     "zatrzymano po {count} błędach technicznych z rzędu; aplikacja może nie działać"),
    ("the same row as record {record}, which waits for a person to check it; not repeated",
     "ten sam wiersz co rekord {record}, który czeka na sprawdzenie przez człowieka; "
     "nie powtórzono"),
    ("{folder} holds results of another batch ({changed} differ); use another results folder "
     "or start this one over",
     "{folder} ma wyniki innego wsadu (różnią się: {changed}); użyj innego folderu wyników "
     "albo zacznij ten od nowa"),
    ("{source}: {problems} (columns: {shown})", "{source}: {problems} (kolumny: {shown})"),
    ("{source}: the process takes no values from a sheet (it has no inputs); run it without one",
     "{source}: proces nie bierze żadnych wartości z arkusza (nie ma danych wejściowych); "
     "uruchom go bez arkusza"),
    ("no column '{column}' (input {name})", "brak kolumny „{column}” (dana {name})"),
    ("the column '{column}' is there {count} times", "kolumna „{column}” występuje {count} razy"),
    # the browser
    ("the profile {folder} is in use by another Maptelo browser: wait for it to finish, "
     "or use another profile",
     "profil {folder} jest używany przez inną przeglądarkę Maptelo: poczekaj, aż skończy, "
     "albo użyj innego profilu"),
    ("the profile {folder} cannot be opened: {reason}",
     "nie da się otworzyć profilu {folder}: {reason}"),
    # inputs
    ("unknown input '{name}'", "nieznana dana „{name}”"),
    ("input '{name}' is required", "dana „{name}” jest wymagana"),
    ("input '{name}': {problem}", "dana „{name}”: {problem}"),
    ("input '{name}' is required (at least one line)",
     "dana „{name}” jest wymagana (co najmniej jedna pozycja)"),
    ("input '{name}', line {line}: it is required", "dana „{name}”, pozycja {line}: jest wymagana"),
    ("input '{name}', line {line}: {problem}", "dana „{name}”, pozycja {line}: {problem}"),
    ("the record's lines differ in number ({each})",
     "pozycje rekordu różnią się liczbą ({each})"),
    ("the record has no lines for the steps done per line",
     "rekord nie ma pozycji dla kroków robionych dla każdej pozycji"),
    ("the steps of a line keep jumping between them",
     "kroki jednej pozycji wciąż przeskakują między sobą"),
    ("{source}: no column '{column}', which names one record of several rows",
     "{source}: brak kolumny „{column}”, która nazywa rekord z kilku wierszy"),
    ("{source}: the rows of one record do not agree about {what}",
     "{source}: wiersze jednego rekordu nie zgadzają się co do: {what}"),
    ("{value} is below the minimum {limit}", "{value} jest poniżej minimum {limit}"),
    ("{value} is above the maximum {limit}", "{value} jest powyżej maksimum {limit}"),
    ("expected text, got {value}", "oczekiwano tekstu, jest {value}"),
    ("{value} does not match the pattern {pattern}", "{value} nie pasuje do wzorca {pattern}"),
    ("{value} is not one of: {choices}", "{value} nie jest jedną z wartości: {choices}"),
    ("expected an integer, got {value}", "oczekiwano liczby całkowitej, jest {value}"),
    ("expected a number, got {value}", "oczekiwano liczby, jest {value}"),
    ("expected a finite number, got {value}", "oczekiwano skończonej liczby, jest {value}"),
    ("expected a date as YYYY-MM-DD, got {value}", "oczekiwano daty RRRR-MM-DD, jest {value}"),
    ("expected true/false, got {value}", "oczekiwano tak/nie (true/false), jest {value}"),
    # the independent read
    ("confirmed by an independent read", "potwierdzone niezależnym odczytem"),
    ("the answer is not a JSON object", "odpowiedź nie jest obiektem JSON"),
    ("cannot read the system of record: {reason}", "nie da się odczytać systemu: {reason}"),
    ("<urlopen error {reason}>", "brak połączenia z adresem odczytu: {reason}"),
    ("[Errno {code}] getaddrinfo failed", "nie ma serwera o tej nazwie (sprawdź adres odczytu)"),
    ("[WinError {code}] No connection could be made because the target machine actively "
     "refused it",
     "serwer odmówił połączenia (czy działa? czy port w adresie jest dobry?)"),
    ("{field}: expected {wanted}, found {found}", "{field}: oczekiwano {wanted}, jest {found}"),
    ("the record does not exist (404)", "rekordu nie ma (404)"),
    ("the record does not exist ({status})", "rekordu nie ma ({status})"),
    ("the page {url} is a path, but the application has no address",
     "strona {url} to ścieżka, a aplikacja nie ma adresu"),
    ("effect '{effect}' has a relative URL but no api_base_url is set",
     "efekt „{effect}” ma adres względny, a nie ustawiono api_base_url"),
    # shadow mode
    ("the model names no effect", "model nie wskazuje efektu"),
    ("the system holds what the record says", "system ma to, co mówi wiersz"),
    ("the system shows what it showed before", "system pokazuje to samo co wcześniej"),
    ("the system does not hold it yet", "systemu jeszcze tego nie ma"),
    ("the record's values are not valid", "wartości z wiersza są niepoprawne"),
    # sheets
    ("{file} is not a workbook: it has no sheets", "{file} to nie skoroszyt: nie ma arkuszy"),
    ("{file} cannot be read as a workbook: {reason}",
     "{file} nie da się odczytać jako skoroszytu: {reason}"),
    ("{file} has no sheet '{sheet}' (sheets: {sheets})",
     "{file} nie ma arkusza „{sheet}” (arkusze: {sheets})"),
    # AI repairs
    ("the model API cannot be reached: {reason}", "API modelu jest nieosiągalne: {reason}"),
    ("the model API cannot be reached", "API modelu jest nieosiągalne"),
    ("no model given for provider '{provider}'", "nie podano modelu dla dostawcy „{provider}”"),
    ("{key} is not set: put it in the environment or in a .env file",
     "{key} nie jest ustawiony: dodaj go do zmiennych środowiska albo do pliku .env"),
    ("the agent used up its budget of {count} questions",
     "agent wyczerpał limit pytań ({count})"),
    ("the model did not answer with a JSON object", "model nie odpowiedział obiektem JSON"),
    ("the model did not answer with JSON", "model nie odpowiedział w JSON"),
    ("unknown AI provider '{name}': one of {names}",
     "nieznany dostawca AI „{name}”: do wyboru {names}"),
    ("IT's policy names no company AI: ai.endpoint, ai.api, ai.key_env and ai.model describe it",
     "polityka IT nie opisuje AI firmy: opisują je ai.endpoint, ai.api, ai.key_env i ai.model"),
    ("the company's own AI, as IT's policy describes it", "AI firmy, opisane w polityce IT"),
    ("the model did not answer with JSON: {reason}",
     "model nie odpowiedział w JSON: {reason}"),
    ("the model API answered HTTP {code}", "API modelu odpowiedziało HTTP {code}"),
    ("the model API did not return JSON", "API modelu nie zwróciło JSON"),
    ("the API key was refused (HTTP {code})", "klucz API został odrzucony (HTTP {code})"),
    # IT's policy
    ("{problem}; nothing is done until it is fixed",
     "{problem}; do czasu poprawki nic nie zostanie zrobione"),
    ("IT's policy {path} cannot be read: {reason}",
     "nie da się odczytać zasad IT {path}: {reason}"),
    ("IT's policy {path} is not valid: {reason}", "zasady IT {path} są niepoprawne: {reason}"),
    ("the address {host} is not allowed by IT's policy ({path})",
     "adresu {host} nie dopuszczają zasady IT ({path})"),
    ("“{step}” opens {other}, but this run works in {here} instead of {recorded}: where that "
     "other application is for this run is not known, so nothing is opened there",
     "„{step}” otwiera {other}, a ten przebieg pracuje w {here} zamiast w {recorded}: nie "
     "wiadomo, gdzie jest ta druga aplikacja w tym przebiegu, więc nic tam nie jest otwierane"),
    ("AI is turned off by IT's policy ({path})", "AI jest wyłączone przez zasady IT ({path})"),
    ("IT's policy allows AI only at {endpoint} ({path})",
     "zasady IT dopuszczają AI tylko pod adresem {endpoint} ({path})"),
    # processes as tools for AI agents
    ("choose at least one process for the agent", "wybierz co najmniej jeden proces dla agenta"),
    ("{key} cannot be offered yet: {problems}",
     "{key} nie może jeszcze być narzędziem: {problems}"),
    ("nothing defines 'done' (no effects): no run could ever be VERIFIED",
     "nic nie mówi, kiedy jest zrobione (brak efektów): żaden przebieg nie dostanie VERIFIED"),
    ("steps without a rule yet ({steps}): answer questions.yaml and build again",
     "kroki bez reguły ({steps}): odpowiedz na pytania i zbuduj model ponownie"),
    ("'{name}' cannot be a tool name (letters, digits, _ and - only)",
     "„{name}” nie może być nazwą narzędzia (tylko litery, cyfry, _ i -)"),
    ("two processes are called '{name}'", "dwa procesy nazywają się „{name}”"),
    ("'processes' must be a list of process names", "„processes” musi być listą nazw procesów"),
    ("the MCP extra is not installed: pip install 'maptelo[mcp]'",
     "brak dodatku MCP: pip install 'maptelo[mcp]'"),
    # a person points at an element
    ("paused before “{step}” for a person to point at its element",
     "pauza przed „{step}”: osoba wskazuje element"),
    ("“{step}” has no element to point at", "„{step}” nie ma elementu do wskazania"),
    ("“{step}” comes after a step that saves: it cannot be reached without saving; a repair "
     "for it comes from a real run",
     "„{step}” jest po kroku, który zapisuje: nie da się do niego dojść bez zapisu; naprawę "
     "da prawdziwy przebieg"),
    ("the element clicked cannot be found again: point at another one",
     "klikniętego elementu nie da się odnaleźć ponownie: wskaż inny"),
    # Maptelo Lite: a demonstration and its map, no robot
    ("the full Maptelo runs processes: Maptelo Lite only maps them",
     "procesy uruchamia pełne Maptelo: Maptelo Lite tylko je mapuje"),
    ("there is no recording {name} of {key}", "nie ma nagrania {name} procesu {key}"),
    # a demonstration in a Java program, recorded from Studio
    ("a Java program can be recorded on Windows only",
     "program Java można nagrać tylko w Windows"),
    ("the Java program “{program}” is not open, or the Java Access Bridge is off for it: IT "
     "turns it on with jabswitch -enable, then the program is started again",
     "program Java „{program}” nie jest otwarty albo most Java (Java Access Bridge) jest dla "
     "niego wyłączony: dział IT włącza go poleceniem jabswitch -enable, potem program trzeba "
     "uruchomić ponownie"),
    # a menu clicked before the page was ready, clicked once more
    ("“{step}” clicked once more: only then was “{next}” there",
     "„{step}” kliknięte jeszcze raz: dopiero wtedy było „{next}”"),
    ("{via} (after “{step}” once more)", "{via} (po ponownym „{step}”)"),
    ("there is no step {name}", "nie ma kroku {name}"),
    ("paused for a person", "pauza dla osoby"),
    ("pointed at in Studio: {element}", "wskazane w Studio: {element}"),
    ("'values' must be an object", "„values” musi być obiektem"),
    # Studio's own checks of a request
    ("there is no run {name}", "nie ma przebiegu {name}"),
    ("this process has no model to draw yet", "ten proces nie ma jeszcze modelu do narysowania"),
    ("this process has no report yet", "ten proces nie ma jeszcze raportu"),
    ("there is no such file or folder", "nie ma takiego pliku ani folderu"),
    ("there is no such file", "nie ma takiego pliku"),
    ("there is no such job", "nie ma takiego zadania"),
    ("there is no process {name}", "nie ma procesu {name}"),
    ("the description is empty", "opis jest pusty"),
    ("a step is described while its recording runs",
     "opis kroku dodaje się w trakcie jego nagrywania"),
    ("which step: its first action's number", "który krok: numer jego pierwszego działania"),
    ("which step: its action's number", "który krok: numer jego działania"),
    ("the card: its answers by question", "karta procesu: odpowiedzi na kolejne pytania"),
    ("there is no map of the recording {recording} of {key}",
     "nie ma mapy nagrania {recording} procesu {key}"),
    ("{name} could not be deleted (Windows says {code})",
     "nie udało się usunąć {name} (Windows zgłasza kod {code})"),
    ("the file is empty", "plik jest pusty"),
    ("the file is larger than 50 MB", "plik ma więcej niż 50 MB"),
    ("the language is pl or en", "język to pl albo en"),
    ("{title} is still running", "wciąż trwa: {title}"),
    ("the process needs a name with letters or digits, e.g. Ceny klientów",
     "proces potrzebuje nazwy z literami albo cyframi, np. Ceny klientów"),
    ("the profile name must be small letters, digits, - or _ (up to 64), e.g. praca",
     "nazwa profilu: małe litery, cyfry, - albo _ (do 64 znaków), np. praca"),
    ("the profile name must be small letters, digits, - or _",
     "nazwa profilu: małe litery, cyfry, - albo _"),
    ("the address must start with http:// or https://",
     "adres musi zaczynać się od http:// albo https://"),
    ("the browser must be one of: {names}", "przeglądarka musi być jedną z: {names}"),
    ("a profile keeps the sign-in itself: choose a profile or a session",
     "profil sam pamięta logowanie: wybierz profil albo plik sesji"),
    ("this process has no questions", "ten proces nie ma pytań"),
    ("there is no session file {name}", "nie ma pliku sesji {name}"),
    ("no recordings of {name} to build from",
     "nie ma nagrań procesu {name}, z których da się zbudować model"),
    ("there is no question {name}", "nie ma pytania {name}"),
    ("there are no proposed repairs", "nie ma proponowanych napraw"),
    ("no repair was confirmed by a verified run yet: run the process, or accept all",
     "żadnej naprawy nie potwierdził jeszcze przebieg VERIFIED: uruchom proces albo "
     "przyjmij wszystkie"),
    ("there is no sheet {name}", "nie ma arkusza {name}"),
    ("{question}: the answer must look like the example (fields)",
     "{question}: odpowiedź musi wyglądać jak przykład (pola)"),
    ("{question}: the answer is not valid ({kind})",
     "{question}: odpowiedź jest niepoprawna ({kind})"),
    ("'{name}' must be text", "„{name}” musi być tekstem"),
    ("the sheet has no rows to run", "arkusz nie ma wierszy do zrobienia"),
    ("'{name}' must start with http:// or https://",
     "„{name}” musi zaczynać się od http:// albo https://"),
    ("'inputs' must be an object", "„inputs” musi być obiektem"),
    ("'timeout_ms' must be a whole number from 1000 to 120000",
     "„timeout_ms” musi być liczbą całkowitą od 1000 do 120000"),
    ("'answers' must be an object: question id → answer",
     "„answers” musi być obiektem: id pytania → odpowiedź"),
    ("choose the sheet people work through", "wybierz arkusz, z którym pracują ludzie"),
    ("there is no shadow check {name}", "nie ma takiego sprawdzenia: {name}"),
    ("a sheet must be one of: {suffixes}", "arkusz musi mieć jedno z rozszerzeń: {suffixes}"),
    ("{path} is outside the workspace", "{path} jest poza folderem roboczym"),
    ("the other way was taken ({step})", "proces poszedł drugą drogą ({step})"),
    ("not read in this run: {names}", "nieodczytane w tym przebiegu: {names}"),
    ("{how} in the frame “{frame}”", "{how} w ramce „{frame}”"),
    ("no single option of the list is named in “{text}”",
     "żadnej opcji listy (albo więcej niż jednej) nie wymienia tekst „{text}”"),
    ("“{step}” types what no step read in this run ({names}): the step that reads it was skipped",
     "„{step}” wpisuje to, czego żaden krok nie odczytał w tym przebiegu ({names}): krok odczytu "
     "został pominięty"),
    # values read from a document's picture (a scan, a photo) by a model that sees images
    ("document image read by {reader} ({count} fields)",
     "obraz dokumentu odczytał {reader} (pól: {count})"),
    ("“{field}” on the document's image: {problem}; a person reads it from the document",
     "„{field}” na obrazie dokumentu: {problem}; odczyta to człowiek z dokumentu"),
    ("“{step}” reads “{field}” from a document's image: the run has no model that sees images "
     "(--vision), so a person reads it",
     "„{step}” odczytuje „{field}” z obrazu dokumentu: przebieg nie ma modelu, który widzi "
     "obrazy (--vision), więc odczyta to człowiek"),
    ("“{field}”: the document's image does not give it ({problem}); the form's reading passes "
     "its check digits and is kept",
     "„{field}”: obraz dokumentu tego nie daje ({problem}); odczyt w formularzu przechodzi sumę "
     "kontrolną i zostaje"),
    ("“{field}”: the document's image reads “{read}”, the form holds “{held}”; a person "
     "decides which is right",
     "„{field}”: na obrazie dokumentu jest „{read}”, w formularzu „{held}”; który odczyt jest "
     "dobry, rozstrzyga człowiek"),
    ("not read", "nie odczytano"),
    ("the value is empty", "wartość jest pusta"),
    ("a tax number has 10 digits, here {count}", "NIP ma 10 cyfr, tu {count}"),
    ("the tax number's check digit does not match", "cyfra kontrolna NIP się nie zgadza"),
    ("not an account number", "to nie jest numer rachunku"),
    ("the account number's checksum does not match",
     "suma kontrolna numeru rachunku się nie zgadza"),
    ("not a date: {value}", "to nie jest data: {value}"),
    ("not an amount: {value}", "to nie jest kwota: {value}"),
    ("not a number: {value}", "to nie jest liczba: {value}"),
    ("not found on the document", "nie ma tego na dokumencie"),
    ("the model is not sure of it", "model nie jest tego pewny"),
    ("net {net} + VAT {vat} is not the gross {gross}",
     "netto {net} + VAT {vat} to nie brutto {gross}"),
]  # fmt: skip

SENTENCE_SLOTS = {
    "message",
    "detail",
    "reason",
    "problem",
    "problems",
    "tried",
    "how",
    "refusal",
    "checked",
}
"""Slots that hold a sentence of their own, translated in turn; the others name things."""
_SLOT = re.compile(r"\\\{(\w+)\\\}")


def _whole(english: str) -> bool:
    """A sentence tried before a text is split at "; ": it has "; " inside it, or a slot
    that holds several sentences joined that way."""
    return "; " in english or "{problems}" in english


@cache
def _rules() -> tuple[list[tuple[re.Pattern[str], str]], list[tuple[re.Pattern[str], str]]]:
    """(whole sentences, the others): the first are tried before a text is split into its
    sentences, the others after, so no slot swallows the next sentence."""
    compiled = [
        (re.compile(_SLOT.sub(lambda m: f"(?P<{m.group(1)}>.*?)", re.escape(english))), pl)
        for english, pl in SENTENCES
    ]
    pairs = list(zip(compiled, SENTENCES, strict=True))
    return (
        [rule for rule, (english, _) in pairs if _whole(english)],
        [rule for rule, (english, _) in pairs if not _whole(english)],
    )


def _apply(text: str, rules: list[tuple[re.Pattern[str], str]]) -> str | None:
    for pattern, template in rules:
        found = pattern.fullmatch(text)
        if found is not None:
            slots = {
                name: polish(value) if name in SENTENCE_SLOTS else value
                for name, value in found.groupdict().items()
            }
            return template.format(**slots)
    return None


def polish(text: str) -> str:
    """The sentence in Polish when its shape is known; else as it is (in English)."""
    joined, single = _rules()
    whole = _apply(text, joined)
    if whole is not None:
        return whole
    if "; " in text:  # several sentences in one
        parts = text.split("; ")
        translated = [polish(part) for part in parts]
        if translated != parts:
            return "; ".join(translated)
    whole = _apply(text, single)
    if whole is not None:
        return whole
    head, colon, rest = text.partition(": ")
    if colon:  # "<a step>: <what went wrong>"
        after = polish(rest)
        if after != rest:
            return head + colon + after
    return text


def polish_all(texts: list[str]) -> list[str]:
    return [polish(text) for text in texts]
