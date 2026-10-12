"use strict";
// Maptelo Studio: one page with hash routes, data from /api. Everything is built with DOM
// calls (never HTML made from data), so nothing a sheet or a screen says can run here.

const BROWSERS = [["chromium", "Chromium (wbudowany)"], ["msedge", "Microsoft Edge"], ["chrome", "Google Chrome"]];

const view = document.getElementById("view");
const banner = document.getElementById("banner");
let leave = () => {};
let navigation = 0;  // counts the pages opened; a view loaded for an older one is not shown
let workspace = "";
let flash = null;  // a message for the next view (after a build, say)
let preferredBrowser = null;  // one this computer has and no policy forbids driving (from /api/state)
let browserRequired = false;  // IT's policy names the browser: nobody chooses another
let lite = false;  // Maptelo Lite: a demonstration and its map, no robot (from /api/state)
let lang = "pl";  // the page's language: Polish; Maptelo Lite also English

function takeFlash() {
  const message = flash;
  flash = null;
  return message ? h("div", { class: message.tone === "ok" ? "notice ok" : "notice" }, message.text) : null;
}

// --- the page's language ------------------------------------------------------------------

/* Maptelo Lite speaks Polish or English (chosen at the foot of the side panel; at first the
   computer's own language); the full Studio speaks Polish. The words are written in Polish and
   t() finds them in EN; what EN lacks stays Polish (a test keeps EN whole for Lite). Only the
   page's own words go through t(): never a process's name, a note, or what an application or
   a sheet says. "{}" in a sentence is where t() puts what follows it. */
const EN = {
  // the frame
  "Procesy": "Processes",
  "Gotowość": "Readiness",
  "Główne": "Main",
  "Folder roboczy": "Workspace folder",
  "Zrzut ekranu": "Screenshot",
  "Zamknij": "Close",
  "Język": "Language",
  "{}: procesy": "{}: processes",
  "Trwa: {}": "In progress: {}",
  "Zobacz": "See",
  "Wróć do procesów": "Back to the processes",
  "Nie ma takiej strony.": "There is no such page.",
  "Brak dostępu": "No access",
  "Otwórz {} z adresu, który pokazał się przy uruchomieniu (zawiera klucz do tej sesji).":
    "Open {} from the address it showed when it started (it holds the key to this session).",
  "Polecenie: {}": "Command: {}",
  // the browser and the sign-in
  "Chromium (wbudowany)": "Chromium (built in)",
  "Przeglądarka": "Browser",
  "Wymagana przez zasady IT: {}": "Required by IT policy: {}",
  "Polecana na tym komputerze: {}": "Recommended on this computer: {}",
  "Bez profilu": "No profile",
  "Profil pamięta logowanie do aplikacji; zakłada się go w „Gotowości”.":
    "A profile remembers the sign-in to the application; you set it up in “Readiness”.",
  "Nie ma jeszcze profilu: ": "No profile yet: ",
  "zaloguj się raz w „Gotowości”": "sign in once in “Readiness”",
  ", potem nagrywanie pamięta logowanie.": ", then recording remembers the sign-in.",
  ", potem robot pamięta logowanie.": ", then the robot remembers the sign-in.",
  "Profil z logowaniem": "Profile with the sign-in",
  "plik sesji (.json)": "session file (.json)",
  "Albo zapisana sesja": "Or a saved session",
  "Dla IT: plik z maptelo session save": "For IT: a file from maptelo session save",
  // recording
  "np. Zmiana cen klientów": "e.g. Customer price change",
  "https://… adres, od którego zaczyna się proces": "https://… the address the process starts at",
  "np. klient bez cen, cena z rabatem": "e.g. a customer without prices, a discounted price",
  " Maptelo zapamięta, z której kolumny bierzesz każdą wartość.":
    " Maptelo remembers which column each value comes from.",
  "Szukam otwartych programów Java…": "Looking for open Java programs…",
  "Nie widzę otwartego programu Java. Otwórz go, zaloguj się i kliknij „Odśwież listę”.":
    "No Java program is open. Open it, sign in and click “Refresh the list”.",
  "Na tym komputerze brakuje mostu Java (Java Access Bridge), przez który Maptelo widzi program: zajrzyj do „Gotowości”.":
    "This computer lacks the Java bridge (Java Access Bridge) Maptelo sees the program through: look in “Readiness”.",
  "Adres startowy": "Start address",
  "Program": "Program",
  "Otwarte teraz programy Java. Maptelo nagrywa tylko ten, który wybierzesz.":
    "The Java programs open now. Maptelo records only the one you choose.",
  "Odśwież listę": "Refresh the list",
  "Gdzie robisz proces": "Where you do the process",
  "Gdzie robisz proces:": "Where you do the process:",
  "Wybierz program Java, w którym robisz proces (otwarty, najlepiej już po zalogowaniu). Po kliknięciu „Rozpocznij nagrywanie” {} zejdzie na pasek zadań: zrób proces w programie tak jak zwykle, potem wróć tutaj i kliknij „Zakończ nagrywanie”. Hasła nigdy nie są zapisywane.":
    "Choose the Java program you do the process in (open, ideally signed in already). When you click “Start recording”, {} goes down to the taskbar: do the process in the program as usual, then come back here and click “Finish recording”. Passwords are never saved.",
  "Otworzy się okno przeglądarki. Zrób w nim proces tak jak zwykle, a potem zamknij okno albo kliknij „Zakończ nagrywanie” w {}. Hasła nigdy nie są zapisywane.":
    "A browser window opens. Do the process in it as usual, then close the window or click “Finish recording” in {}. Passwords are never saved.",
  "W przeglądarce": "In a browser",
  "W programie Java": "In a Java program",
  "Rozpocznij nagrywanie": "Start recording",
  "Najpierw wybierz program Java z listy.": "First choose a Java program from the list.",
  "nowy proces": "new process",
  " / pokaz": " / recording",
  "Nagraj proces ponownie": "Record the process again",
  "Kolejny pokaz procesu": "Another demonstration of the process",
  "Nowy proces: nagraj pokaz": "New process: record it",
  "Nazwa procesu": "Process name",
  "Ten sam proces: nowe nagranie dostanie własną mapę.": "The same process: the new recording gets a map of its own.",
  "Ten sam proces: kolejny pokaz uczy model czegoś nowego.":
    "The same process: another demonstration teaches the model something new.",
  "Tak, jak nazywa go zespół. Z niej powstanie nazwa folderu.":
    "As your team calls it. The folder's name is made from it.",
  "Co jest w tym pokazie szczególnego": "What is special about this recording",
  "Opcjonalnie. Pojawi się na mapie.": "Optional. It appears on the map.",
  "Opcjonalnie. Pomaga przy pytaniach modelu.": "Optional. It helps with the model's questions.",
  "Dane z arkusza (opcjonalnie)": "Data from a sheet (optional)",
  "Jeśli wartości bierzesz z arkusza, wskaż go. Przyda się, jeśli z tej mapy ma kiedyś powstać automatyzacja: robot będzie wiedział, która kolumna daje którą daną.":
    "If you take the values from a sheet, choose it. It helps if this map is to become an automation one day: the robot will know which column gives which value.",
  "Jeśli wartości bierzesz z arkusza, wskaż go: model nauczy się, która kolumna daje którą daną.":
    "If you take the values from a sheet, choose it: the model learns which column gives which value.",
  "Wybierz arkusz…": "Choose a sheet…",
  "Jak nagrywać": "How to record",
  "Tryb prywatny: zrzuty zakryją wpisane wartości i zawartość tabel":
    "Private mode: screenshots cover what is typed and what tables hold",
  "Czekam na pierwsze kroki…": "Waiting for the first steps…",
  "Okno przeglądarki jest otwarte (jeśli go nie widać, kliknij jego ikonę na pasku zadań). Zrób w nim proces tak jak zwykle. Gdy skończysz, zamknij okno albo kliknij „Zakończ nagrywanie”.":
    "The browser window is open (if you cannot see it, click its icon on the taskbar). Do the process in it as usual. When you are done, close the window or click “Finish recording”.",
  "Zakończ nagrywanie": "Finish recording",
  "Nagrywam program „{}”. Zrób w nim proces tak jak zwykle. Gdy skończysz, wróć tutaj ({} na pasku zadań) i kliknij „Zakończ nagrywanie”. Maptelo zapisuje tylko to, co dzieje się w tym programie.":
    "Recording the program “{}”. Do the process in it as usual. When you are done, come back here ({} on the taskbar) and click “Finish recording”. Maptelo saves only what happens in this program.",
  "Zapisane kroki i zdarzenia: {}": "Steps and events saved: {}",
  "nagrywa": "recording",
  "błąd": "error",
  "nagranie zapisane": "recording saved",
  " Robię mapę procesu…": " Making the map of the process…",
  "Nagranie się nie zapisało.": "The recording was not saved.",
  "Maptelo Lite nie ma zadań „{}”.": "Maptelo Lite has no “{}” jobs.",
  // readiness
  "Oprogramowanie": "Software",
  "Model procesu": "Process model",
  "Profil": "Profile",
  "Aplikacja": "Application",
  "Logowanie": "Sign-in",
  "Niezależny odczyt": "Independent read",
  "Strefa czasowa": "Time zone",
  "Przeglądarki": "Browsers",
  "Prowadzenie przeglądarki": "Driving the browser",
  "Narzędzia deweloperskie": "Developer tools",
  "Okno aplikacji": "Application window",
  "Proxy": "Proxy",
  "Skrypt proxy": "Proxy script",
  "Certyfikaty HTTPS": "HTTPS certificates",
  "Uprawnienia": "Rights",
  "Adres lokalny": "Local address",
  "Zasady IT": "IT policy",
  "Programy Java": "Java programs",
  "w porządku": "fine",
  "problem": "problem",
  "informacja": "note",
  "Ten komputer": "This computer",
  "Co Maptelo tu może: sprawdzone w chwili, bez łączenia się z siecią. Czego brakuje, tam Maptelo wybiera inną drogę albo mówi, o co poprosić IT.":
    "What Maptelo can do here, checked in a moment without going on the network. Where something is missing, Maptelo takes another way or says what to ask IT for.",
  "do poprawy: {}": "to fix: {}",
  "rdzeń działa": "the core works",
  "np. praca": "e.g. work",
  "Profil przeglądarki z logowaniem": "A browser profile with your sign-in",
  "Nagranie może się odbywać w osobnym profilu przeglądarki, który pamięta Twoje logowanie. Zaloguj się w nim raz, sam, w zwykłym oknie: Maptelo nie widzi i nie zapisuje hasła.":
    "A recording can happen in a browser profile of its own that remembers your sign-in. Sign in there once, yourself, in an ordinary window: Maptelo neither sees nor saves the password.",
  "Robot pracuje w osobnym profilu przeglądarki, który pamięta Twoje logowanie. Zaloguj się w nim raz, sam, w zwykłym oknie: Studio nie widzi i nie zapisuje hasła.":
    "The robot works in a browser profile of its own that remembers your sign-in. Sign in there once, yourself, in an ordinary window: Studio neither sees nor saves the password.",
  "zapamiętane {}": "remembered {}",
  "jeszcze nie": "not yet",
  "Na tym komputerze nie ma jeszcze profilu.": "This computer has no profile yet.",
  "Nazwa profilu": "Profile name",
  "Małe litery, cyfry, - albo _. Ten profil wybierzesz przy nagrywaniu.":
    "Small letters, digits, - or _. You choose this profile when recording.",
  "Małe litery, cyfry, - albo _. Tę nazwę wpiszesz przy uruchamianiu.":
    "Small letters, digits, - or _. You type this name when running.",
  "Adres do zalogowania": "Address to sign in at",
  "Strona logowania albo pierwszy ekran procesu.": "The sign-in page or the first screen of the process.",
  "Otwórz okno logowania": "Open the sign-in window",
  "Logowanie i sprawdzenie komputera przed pierwszym nagraniem.":
    "The sign-in and a check of this computer before the first recording.",
  "Logowanie i sprawdzenie komputera przed pierwszym przebiegiem.":
    "The sign-in and a check of this computer before the first run.",
  "Zakończ": "Finish",
  " / logowanie": " / sign-in",
  "okno otwarte": "window open",
  "gotowe": "done",
  "Okno przeglądarki jest otwarte. Zaloguj się w nim tak jak zwykle (także przez SSO firmy), a potem zamknij okno.":
    "The browser window is open. Sign in there as usual (also through your company's SSO), then close the window.",
  "Profil {} pamięta logowanie": "The profile {} remembers the sign-in",
  "Logowanie nie zostało zapamiętane": "The sign-in was not remembered",
  "Wybierz „{}” w polu „Profil z logowaniem” przy nagrywaniu. Profil to Twoje ciasteczka: nie udostępniaj go nikomu.":
    "Choose “{}” in the “Profile with the sign-in” field when you record. The profile holds your cookies: share it with no one.",
  "Wpisz „{}” w polu „Profil z logowaniem” przy pokazie i przy uruchamianiu. Profil to Twoje ciasteczka: nie udostępniaj go nikomu.":
    "Type “{}” in the “Profile with the sign-in” field when you record and when you run. The profile holds your cookies: share it with no one.",
  "Okno zamknęło się, zanim strona coś zapisała. Spróbuj jeszcze raz.":
    "The window closed before the page saved anything. Try again.",
  "Wróć do gotowości": "Back to readiness",
  // maps
  "Mapa gotowa: {}.": "The map is ready: {}.",
  "{} w folderze {}": "{} in the folder {}",
  "Nowy proces: nagraj": "New process: record",
  "Tu pojawią się Twoje procesy": "Your processes will appear here",
  "Zrób proces raz w przeglądarce albo w programie Java, a Maptelo Lite zapisze go jako mapę: kroki, instrukcję (SOP), diagram BPMN i raport.":
    "Do a process once in a browser or in a Java program, and Maptelo Lite saves it as a map: its steps, an instruction (SOP), a BPMN diagram and a report.",
  "Nagraj pierwszy proces": "Record your first process",
  "Zrób mapę ponownie": "Make the map again",
  "Zrób mapę": "Make the map",
  "Zobacz mapę": "See the map",
  "Nagraj ponownie": "Record again",
  "Kiedy": "When",
  "Notatka": "Note",
  "Działania": "Actions",
  "Mapa": "Map",
  "Ten proces nie ma jeszcze nagrań.": "This process has no recordings yet.",
  "Powiększ: {}": "Enlarge: {}",
  "Powiększ": "Enlarge",
  "Ta mapa jeszcze nie powstała.": "This map has not been made yet.",
  "Wróć do procesu": "Back to the process",
  "Wczytuję instrukcję…": "Loading the instruction…",
  "Nie udało się wczytać instrukcji: otwórz raport albo folder z plikami.":
    "The instruction could not be loaded: open the report or the folder with the files.",
  " / mapa": " / map",
  "nagranie {}": "recorded {}",
  "Otwórz raport": "Open the report",
  "Folder z plikami": "Folder with the files",
  "Diagram procesu {}": "Diagram of the process {}",
  "Instrukcja krok po kroku (SOP)": "Step-by-step instruction (SOP)",
};
const EN_PLURALS = { krok: ["step", "steps"], proces: ["process", "processes"],
                     nagranie: ["recording", "recordings"], "działanie": ["action", "actions"] };
const LOCALES = { pl: "pl-PL", en: "en-GB" };

function t(text, ...values) {
  let said = lang === "en" && Object.hasOwn(EN, text) ? EN[text] : text;
  for (const value of values) said = said.replace("{}", () => String(value));
  return said;
}

function locale() {
  return LOCALES[lang];
}

/* The language before the person chooses one: the computer's own, Polish or else English. */
function computerLanguage() {
  return (navigator.language || "pl").toLowerCase().startsWith("pl") ? "pl" : "en";
}

/* The words of the frame (the side panel, the picture viewer) in the page's language. */
function applyLanguage() {
  document.documentElement.lang = lang;
  for (const [id, word] of [["processes", "Procesy"], ["ready", "Gotowość"]]) {
    const link = document.querySelector(`[data-nav="${id}"]`);
    if (link) link.textContent = t(word);
  }
  document.querySelector(".side nav").setAttribute("aria-label", t("Główne"));
  document.querySelector(".mark").setAttribute("aria-label", t("{}: procesy", lite ? "Maptelo Lite" : "Maptelo Studio"));
  document.getElementById("workspace").title = t("Folder roboczy");
  document.getElementById("lightbox").setAttribute("aria-label", t("Zrzut ekranu"));
  document.querySelector("#lightbox .close").setAttribute("aria-label", t("Zamknij"));
  const langs = document.getElementById("langs");
  langs.setAttribute("aria-label", t("Język"));
  for (const button of langs.querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
}

/* The person's choice: kept by Lite (the window's address changes at every start, so the
   browser's own storage would forget it), the page drawn again in it. */
async function setLanguage(chosen) {
  if (chosen === lang) return;
  lang = chosen;
  applyLanguage();
  route();
  try { await api("/api/language", { method: "POST", body: { lang: chosen } }); }
  catch { /* shown in this language until Lite closes */ }
}

// --- small tools -------------------------------------------------------------------------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "value") el.value = value;
    else if (key === "checked" || key === "disabled" || key === "selected") el[key] = true;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
}

function show(...children) {
  fill(view, ...children);
  view.focus({ preventScroll: true });
}

class StaleError extends Error {}

/* What a view loads before it shows anything. If the person has moved on in the meantime,
   the answer is dropped: a slow page left behind must not paint over the one now open. */
async function load(path) {
  const opened = navigation;
  const data = await api(path);
  if (opened !== navigation) throw new StaleError("the page was left before it loaded");
  return data;
}

async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = { "X-Maptelo-Lang": lang };
  if (method !== "GET") headers["X-Maptelo"] = "1";
  let payload = body;
  if (body !== undefined && !raw) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const problems = (data && data.problems) || [(data && data.error) || response.statusText];
    const error = new Error(problems.join("; "));
    error.status = response.status;
    error.problems = problems;
    throw error;
  }
  return data;
}

function plural(n, one, few, many) {
  if (lang === "en" && EN_PLURALS[one]) return `${n} ${EN_PLURALS[one][n === 1 ? 0 : 1]}`;
  const tens = n % 100, ones = n % 10;
  if (n === 1) return `${n} ${one}`;
  if (ones >= 2 && ones <= 4 && !(tens >= 12 && tens <= 14)) return `${n} ${few}`;
  return `${n} ${many}`;
}

function problemsBox(problems) {
  return h("div", { class: "problems", role: "alert" }, problems.map((p) => h("div", {}, p)));
}

async function openPath(path) {
  try { await api("/api/open", { method: "POST", body: { path } }); }
  catch (error) { alert(error.message); }
}

function zoom(src, caption) {
  const box = document.getElementById("lightbox");
  box.querySelector("img").src = src;
  box.querySelector(".caption").textContent = caption || "";
  box.showModal();
}

function fileUrl(path) {
  return "/api/files/" + path.split("/").map(encodeURIComponent).join("/");
}

function noAccess() {
  show(h("div", { class: "card empty" },
    h("h1", {}, t("Brak dostępu")),
    h("p", {}, t("Otwórz {} z adresu, który pokazał się przy uruchomieniu (zawiera klucz do tej sesji).", lite ? "Maptelo Lite" : "Studio")),
    h("p", { class: "muted" }, t("Polecenie: {}", lite ? "maptelo-lite" : "maptelo studio"))));
}

/* How the browser opens: window, which browser, a profile that keeps the sign-in or a session. */
function browserSelect() {
  return h("select", { disabled: browserRequired },
    BROWSERS.map(([value, label]) => h("option", { value, selected: value === preferredBrowser }, t(label))));
}

/* "Przeglądarka" with the browser this computer has and lets Maptelo drive chosen first. */
function browserLabel(select) {
  const preferred = BROWSERS.find(([value]) => value === preferredBrowser);
  return h("label", {}, t("Przeglądarka"), select,
    preferred ? h("span", { class: "hint" }, browserRequired
      ? t("Wymagana przez zasady IT: {}", t(preferred[1]))
      : t("Polecana na tym komputerze: {}", t(preferred[1]))) : null);
}

/* The profiles this computer keeps a sign-in in, the only one chosen already (the clean-Windows
   test of 11.10: the name was typed by hand, or the run stopped at the application's sign-in). */
function profileChoice() {
  const select = h("select", {}, h("option", { value: "" }, t("Bez profilu")));
  const hint = h("span", { class: "hint" }, t("Profil pamięta logowanie do aplikacji; zakłada się go w „Gotowości”."));
  api("/api/profiles").then((found) => {
    for (const p of found) select.append(h("option", { value: p.name }, p.name));
    if (found.length === 1) select.value = found[0].name;
    if (!found.length) fill(hint, t("Nie ma jeszcze profilu: "), h("a", { href: "#/ready" }, t("zaloguj się raz w „Gotowości”")), lite ? t(", potem nagrywanie pamięta logowanie.") : t(", potem robot pamięta logowanie."));
  }).catch(() => {});
  return { select, label: h("label", {}, t("Profil z logowaniem"), select, hint) };
}

function sessionField() {
  const input = h("input", { type: "text", placeholder: t("plik sesji (.json)") });
  return { input, label: h("label", {}, t("Albo zapisana sesja"), input, h("span", { class: "hint" }, t("Dla IT: plik z maptelo session save"))) };
}

// --- recording a demonstration --------------------------------------------------------------

async function showRecordForm(key) {
  let address = "", program = "", named = key || "";
  if (key) {
    try {
      if (lite) {  // Lite has no model: where the last demonstration began
        const found = await load(`/api/recordings/${encodeURIComponent(key)}`);
        const last = found.slice(-1)[0] || {};
        address = last.url || "";
        program = last.program || "";
        named = titleOf(found, key);
      } else address = (await load(`/api/processes/${encodeURIComponent(key)}`)).application || "";
    }
    catch (error) {
      if (error instanceof StaleError) throw error;
      address = "";
    }
  }
  const state = { sheet: null, sheets: [], java: address.startsWith("java:") };
  const name = h("input", { type: "text", value: named, placeholder: t("np. Zmiana cen klientów"), readonly: Boolean(key) });
  const url = h("input", { type: "text", value: address.startsWith("http") ? address : "", placeholder: t("https://… adres, od którego zaczyna się proces") });
  const note = h("input", { type: "text", placeholder: t("np. klient bez cen, cena z rabatem") });
  const priv = h("input", { type: "checkbox" });
  const browser = browserSelect();
  const profile = profileChoice();
  const session = sessionField();
  const sheetInfo = h("div");
  const sheetPick = h("select", { hidden: true });
  const fileInput = h("input", { type: "file", accept: ".xlsx,.xlsm,.csv,.tsv,.txt", hidden: true });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    try {
      const kept = await api(`/api/sheets?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file, raw: true });
      state.sheet = kept.sheet;
      fill(sheetPick, kept.sheets.map((s) => h("option", { value: s }, s)));
      sheetPick.hidden = kept.sheets.length < 2;
      fill(sheetInfo, h("span", { class: "chip ok" }, file.name), t(" Maptelo zapamięta, z której kolumny bierzesz każdą wartość."));
    } catch (error) { fill(sheetInfo, problemsBox(error.problems || [error.message])); }
  });
  // a Java program on this computer (Oracle Forms, Swing): chosen from those open now
  const javaPick = h("select", {});
  const javaInfo = h("div");
  const listPrograms = async () => {
    fill(javaInfo, h("p", { class: "muted" }, t("Szukam otwartych programów Java…")));
    try {
      const found = await api("/api/java/windows");
      const before = javaPick.value || program;
      fill(javaPick, found.windows.map((w) => h("option", { value: w.title }, w.title)));
      const again = before && found.windows.find((w) => w.title === before || w.title.toLowerCase().includes(before.toLowerCase()));
      if (again) javaPick.value = again.title;
      javaPick.disabled = !found.windows.length;
      if (found.problem) fill(javaInfo, problemsBox([found.problem]));
      else if (!found.windows.length) fill(javaInfo, h("div", { class: "notice" }, t("Nie widzę otwartego programu Java. Otwórz go, zaloguj się i kliknij „Odśwież listę”.")));
      else if (!found.bridge) fill(javaInfo, h("div", { class: "notice" }, t("Na tym komputerze brakuje mostu Java (Java Access Bridge), przez który Maptelo widzi program: zajrzyj do „Gotowości”.")));
      else fill(javaInfo);
    } catch (error) { fill(javaInfo, problemsBox(error.problems || [error.message])); }
  };
  const here = lite ? "Maptelo Lite" : "Studio";
  const intro = h("p");
  const urlLabel = h("label", {}, t("Adres startowy"), url);
  const javaBox = h("div", { class: "java-pick" },
    h("div", { class: "form" },
      h("label", {}, t("Program"), javaPick, h("span", { class: "hint" }, t("Otwarte teraz programy Java. Maptelo nagrywa tylko ten, który wybierzesz."))),
      h("div", { class: "actions" }, h("button", { type: "button", onclick: () => listPrograms() }, t("Odśwież listę")))),
    javaInfo);
  const browserOptions = h("div", { class: "form" }, browserLabel(browser), profile.label, session.label);
  const problems = h("div");
  const where = h("div", { class: "segmented", role: "group", "aria-label": t("Gdzie robisz proces") });
  const setWhere = (java) => {
    state.java = java;
    for (const button of where.children) button.setAttribute("aria-pressed", String((button.dataset.where === "java") === java));
    urlLabel.hidden = java;
    browserOptions.hidden = java;
    javaBox.hidden = !java;
    fill(intro, java
      ? t("Wybierz program Java, w którym robisz proces (otwarty, najlepiej już po zalogowaniu). Po kliknięciu „Rozpocznij nagrywanie” {} zejdzie na pasek zadań: zrób proces w programie tak jak zwykle, potem wróć tutaj i kliknij „Zakończ nagrywanie”. Hasła nigdy nie są zapisywane.", here)
      : t("Otworzy się okno przeglądarki. Zrób w nim proces tak jak zwykle, a potem zamknij okno albo kliknij „Zakończ nagrywanie” w {}. Hasła nigdy nie są zapisywane.", here));
    fill(problems);
    if (java) listPrograms();
  };
  where.append(
    h("button", { type: "button", "data-where": "web", onclick: () => setWhere(false) }, t("W przeglądarce")),
    h("button", { type: "button", "data-where": "java", onclick: () => setWhere(true) }, t("W programie Java")));
  const start = h("button", { type: "button", class: "primary" }, t("Rozpocznij nagrywanie"));
  start.addEventListener("click", async () => {
    fill(problems);
    if (state.java && !javaPick.value) { fill(problems, problemsBox([t("Najpierw wybierz program Java z listy.")])); return; }
    start.disabled = true;
    const place = state.java
      ? { java: javaPick.value }
      : { url: url.value, browser: browser.value, profile: profile.select.value, session: session.input.value };
    try {
      const job = await api("/api/recordings", { method: "POST", body: {
        process: name.value, note: note.value, private: priv.checked, ...place,
        sheet: state.sheet, sheet_name: sheetPick.hidden ? null : sheetPick.value } });
      location.hash = `#/job/${job.id}`;
    } catch (error) { fill(problems, problemsBox(error.problems || [error.message])); start.disabled = false; }
  });
  setWhere(state.java);
  show(
    h("div", { class: "head" }, h("div", { class: "titles" },
      h("div", { class: "crumbs" }, h("a", { href: "#/" }, t("Procesy")), " / ", key ? h("a", { href: lite ? `#/p/${encodeURIComponent(key)}` : `#/p/${encodeURIComponent(key)}/recordings` }, named) : t("nowy proces"), t(" / pokaz")),
      h("h1", {}, key ? (lite ? t("Nagraj proces ponownie") : t("Kolejny pokaz procesu")) : t("Nowy proces: nagraj pokaz")))),
    h("div", { class: "card" },
      h("div", { class: "actions" }, h("span", { class: "muted" }, t("Gdzie robisz proces:")), where),
      intro,
      h("div", { class: "form" },
        h("label", {}, t("Nazwa procesu"), name, h("span", { class: "hint" }, key ? (lite ? t("Ten sam proces: nowe nagranie dostanie własną mapę.") : t("Ten sam proces: kolejny pokaz uczy model czegoś nowego.")) : t("Tak, jak nazywa go zespół. Z niej powstanie nazwa folderu."))),
        urlLabel,
        h("label", {}, t("Co jest w tym pokazie szczególnego"), note, h("span", { class: "hint" }, lite ? t("Opcjonalnie. Pojawi się na mapie.") : t("Opcjonalnie. Pomaga przy pytaniach modelu.")))),
      javaBox,
      h("fieldset", {}, h("legend", {}, t("Dane z arkusza (opcjonalnie)")),
        h("p", { class: "muted" }, lite
          ? t("Jeśli wartości bierzesz z arkusza, wskaż go. Przyda się, jeśli z tej mapy ma kiedyś powstać automatyzacja: robot będzie wiedział, która kolumna daje którą daną.")
          : t("Jeśli wartości bierzesz z arkusza, wskaż go: model nauczy się, która kolumna daje którą daną.")),
        h("div", { class: "actions" }, h("button", { type: "button", onclick: () => fileInput.click() }, t("Wybierz arkusz…")), fileInput, sheetPick),
        sheetInfo),
      h("fieldset", {}, h("legend", {}, t("Jak nagrywać")),
        h("label", { class: "check" }, priv, t("Tryb prywatny: zrzuty zakryją wpisane wartości i zawartość tabel")),
        browserOptions),
      problems,
      h("div", { class: "actions" }, start)));
}

async function showRecordJob(id, first) {
  let after = 0, alive = true, events = 0;
  const status = h("div", { class: "chips" });
  const count = h("p", {}, t("Czekam na pierwsze kroki…"));
  const footer = h("div");
  const what = h("p", {}, t("Okno przeglądarki jest otwarte (jeśli go nie widać, kliknij jego ikonę na pasku zadań). Zrób w nim proces tak jak zwykle. Gdy skończysz, zamknij okno albo kliknij „Zakończ nagrywanie”."));
  const finish = h("button", { type: "button", class: "primary", onclick: async () => {
    finish.disabled = true;
    try { await api(`/api/jobs/${id}/stop`, { method: "POST" }); } catch (error) { alert(error.message); }
  } }, t("Zakończ nagrywanie"));
  leave = () => { alive = false; };
  show(h("div", { class: "head" }, h("div", { class: "titles" }, h("div", { class: "crumbs" }, h("a", { href: "#/" }, t("Procesy")), t(" / pokaz")), h("h1", {}, first.title)), h("div", { class: "actions" }, status, finish)),
       h("div", { class: "card" }, what, count),
       footer);
  while (alive) {
    let job;
    try { job = await api(`/api/jobs/${id}?after=${after}`); }
    catch (error) { show(problemsBox([error.message])); return; }
    for (const event of job.events) {
      after = event.seq;
      if (event.type === "progress") events = event.events;
      if (event.type === "start" && event.program) {  // a Java program: it has no window to close
        fill(what, t("Nagrywam program „{}”. Zrób w nim proces tak jak zwykle. Gdy skończysz, wróć tutaj ({} na pasku zadań) i kliknij „Zakończ nagrywanie”. Maptelo zapisuje tylko to, co dzieje się w tym programie.", event.program, lite ? "Maptelo Lite" : "Studio"));
      }
    }
    if (events) fill(count, t("Zapisane kroki i zdarzenia: {}", events));
    const running = job.state === "running";
    fill(status, running
      ? h("span", { class: "chip bad" }, h("span", { class: "spin" }), t("nagrywa"))
      : job.state === "failed" ? h("span", { class: "chip bad" }, t("błąd")) : h("span", { class: "chip ok" }, t("nagranie zapisane")));
    finish.hidden = !running;
    if (!running) {
      const key = job.process;
      if (lite && !job.error && job.result) {  // Lite: the map of this demonstration, at once
        fill(footer, h("div", { class: "card" }, h("p", {}, h("span", { class: "spin" }), t(" Robię mapę procesu…"))));
        try { await makeMap(key, job.result.recording); }
        catch (error) { fill(footer, problemsBox(error.problems || [error.message])); }
        break;
      }
      fill(footer, problemsBox([job.error || t("Nagranie się nie zapisało.")]));
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}

// --- getting the computer ready: profiles and the doctor ----------------------------------

const CHECKS = { software: "Oprogramowanie", model: "Model procesu", profile: "Profil", browser: "Przeglądarka",
                 application: "Aplikacja", "sign-in": "Logowanie", "independent read": "Niezależny odczyt",
                 "time zone": "Strefa czasowa", browsers: "Przeglądarki", driving: "Prowadzenie przeglądarki",
                 "developer tools": "Narzędzia deweloperskie", window: "Okno aplikacji", proxy: "Proxy",
                 "proxy script": "Skrypt proxy", certificates: "Certyfikaty HTTPS", rights: "Uprawnienia",
                 loopback: "Adres lokalny", workspace: "Folder roboczy", policy: "Zasady IT",
                 java: "Programy Java" };

function checksTable(checks) {
  return h("table", { class: "checks" }, h("tbody", {}, checks.map((c) => h("tr", {},
    h("td", {}, h("span", { class: `chip ${c.verdict === "ok" ? "ok" : c.verdict === "FAIL" ? "bad" : "info"}` },
      c.verdict === "ok" ? t("w porządku") : c.verdict === "FAIL" ? t("problem") : t("informacja"))),
    h("th", { scope: "row" }, t(CHECKS[c.what] || c.what)),
    h("td", {}, c.detail, c.hint ? h("div", { class: "hint" }, c.hint) : null)))));
}

/* What this computer allows, looked at in a moment without the network: the browsers and the
   policies on them, the window, the proxy, certificates, rights, the folder, IT's policy. */
function computerCard(computer) {
  const fails = computer.checks.filter((c) => c.verdict === "FAIL").length;
  return h("div", { class: "card" },
    h("div", { class: "head" },
      h("div", { class: "titles" }, h("h2", {}, t("Ten komputer")),
        h("p", { class: "muted" }, t("Co Maptelo tu może: sprawdzone w chwili, bez łączenia się z siecią. Czego brakuje, tam Maptelo wybiera inną drogę albo mówi, o co poprosić IT."))),
      fails ? h("span", { class: "chip bad" }, t("do poprawy: {}", fails)) : h("span", { class: "chip ok" }, t("rdzeń działa"))),
    checksTable(computer.checks));
}

async function showReady() {
  const [profiles, computer] = await Promise.all([load("/api/profiles"), load("/api/environment")]);
  const name = h("input", { type: "text", required: true, placeholder: t("np. praca"), autocomplete: "off" });
  const url = h("input", { type: "url", required: true, placeholder: "https://…" });
  const browser = browserSelect();
  const signProblems = h("div");
  const signIn = h("form", { class: "card", onsubmit: async (event) => {
    event.preventDefault();
    try {
      const job = await api("/api/profiles/sign-in", { method: "POST",
        body: { profile: name.value.trim(), url: url.value.trim(), browser: browser.value } });
      location.hash = `#/job/${job.id}`;
    } catch (error) { fill(signProblems, problemsBox(error.problems || [error.message])); }
  } },
    h("h2", {}, t("Profil przeglądarki z logowaniem")),
    h("p", { class: "muted" }, lite
      ? t("Nagranie może się odbywać w osobnym profilu przeglądarki, który pamięta Twoje logowanie. Zaloguj się w nim raz, sam, w zwykłym oknie: Maptelo nie widzi i nie zapisuje hasła.")
      : t("Robot pracuje w osobnym profilu przeglądarki, który pamięta Twoje logowanie. Zaloguj się w nim raz, sam, w zwykłym oknie: Studio nie widzi i nie zapisuje hasła.")),
    profiles.length
      ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("Profil")), h("th", {}, t("Logowanie")))),
          h("tbody", {}, profiles.map((p) => h("tr", {}, h("td", { class: "mono" }, p.name),
            h("td", {}, p.signed_in ? t("zapamiętane {}", p.signed_in.replace("T", ", ")) : h("span", { class: "muted" }, t("jeszcze nie")))))))
      : h("p", {}, t("Na tym komputerze nie ma jeszcze profilu.")),
    h("div", { class: "form" },
      h("label", {}, t("Nazwa profilu"), name, h("span", { class: "hint" }, lite ? t("Małe litery, cyfry, - albo _. Ten profil wybierzesz przy nagrywaniu.") : t("Małe litery, cyfry, - albo _. Tę nazwę wpiszesz przy uruchamianiu."))),
      h("label", {}, t("Adres do zalogowania"), url, h("span", { class: "hint" }, t("Strona logowania albo pierwszy ekran procesu."))),
      browserLabel(browser)),
    signProblems,
    h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, t("Otwórz okno logowania"))));

  show(h("div", { class: "head" }, h("div", { class: "titles" }, h("h1", {}, t("Gotowość")),
         h("p", { class: "muted" }, lite ? t("Logowanie i sprawdzenie komputera przed pierwszym nagraniem.") : t("Logowanie i sprawdzenie komputera przed pierwszym przebiegiem.")))),
     takeFlash(), computerCard(computer), signIn);
}

async function waitFor(id, render) {
  let alive = true;
  leave = () => { alive = false; };
  while (alive) {
    let job;
    try { job = await api(`/api/jobs/${id}?after=0`); }
    catch (error) { show(problemsBox([error.message])); return; }
    render(job);
    if (job.state !== "running") return;
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function showSignInJob(id, first) {
  const status = h("div", { class: "chips" });
  const body = h("div", { class: "card" });
  const close = h("button", { type: "button", onclick: async () => {
    close.disabled = true;
    try { await api(`/api/jobs/${id}/stop`, { method: "POST" }); } catch (error) { alert(error.message); }
  } }, t("Zakończ"));
  show(h("div", { class: "head" }, h("div", { class: "titles" },
         h("div", { class: "crumbs" }, h("a", { href: "#/ready" }, t("Gotowość")), t(" / logowanie")), h("h1", {}, first.title)),
         h("div", { class: "actions" }, status, close)), body);
  await waitFor(id, (job) => {
    const running = job.state === "running";
    close.hidden = !running;
    fill(status, running ? h("span", { class: "chip info" }, h("span", { class: "spin" }), t("okno otwarte"))
      : job.state === "failed" ? h("span", { class: "chip bad" }, t("błąd")) : h("span", { class: "chip ok" }, t("gotowe")));
    if (running) fill(body, h("p", {}, t("Okno przeglądarki jest otwarte. Zaloguj się w nim tak jak zwykle (także przez SSO firmy), a potem zamknij okno.")));
    else if (job.error) fill(body, problemsBox([job.error]));
    else fill(body,
      h("h2", {}, job.result.kept ? t("Profil {} pamięta logowanie", job.result.profile) : t("Logowanie nie zostało zapamiętane")),
      h("p", { class: "muted" }, job.result.kept
        ? (lite ? t("Wybierz „{}” w polu „Profil z logowaniem” przy nagrywaniu. Profil to Twoje ciasteczka: nie udostępniaj go nikomu.", job.result.profile) : t("Wpisz „{}” w polu „Profil z logowaniem” przy pokazie i przy uruchamianiu. Profil to Twoje ciasteczka: nie udostępniaj go nikomu.", job.result.profile))
        : t("Okno zamknęło się, zanim strona coś zapisała. Spróbuj jeszcze raz.")),
      h("div", { class: "actions" }, h("a", { class: "button primary", href: "#/ready" }, t("Wróć do gotowości"))));
  });
}

async function showJob(id) {
  const first = await load(`/api/jobs/${id}?after=0`);
  if (first.kind === "record") return showRecordJob(id, first);
  if (first.kind === "sign-in") return showSignInJob(id, first);
  return show(problemsBox([t("Maptelo Lite nie ma zadań „{}”.", first.kind)]));
}

// --- Maptelo Lite: a demonstration and its map, no robot -----------------------------------

function applyLite() {
  document.title = "Maptelo Lite";
  fill(document.querySelector(".mark .edition"), "Lite");
  for (const id of ["runs", "agents"]) {
    const link = document.querySelector(`[data-nav="${id}"]`);
    if (link) link.hidden = true;
  }
  const langs = document.getElementById("langs");
  langs.hidden = false;
  for (const button of langs.querySelectorAll("button")) button.addEventListener("click", () => setLanguage(button.dataset.lang));
  applyLanguage();
}

async function makeMap(key, recording) {
  const made = await api("/api/maps", { method: "POST", body: { process: key, recording, lang } });
  flash = { tone: "ok", text: t("Mapa gotowa: {}.", plural(made.steps, "krok", "kroki", "kroków")) };
  location.hash = `#/p/${encodeURIComponent(key)}/map/${encodeURIComponent(recording)}`;
}

/* The name the person gave the process (its newest recording keeps it), else its folder's. */
function titleOf(recordings, key) {
  const named = recordings.map((r) => r.title).filter(Boolean);
  return named.length ? named[named.length - 1] : key;
}

async function showLiteProcesses() {
  const drafts = await load("/api/drafts");
  show(
    h("div", { class: "head" }, h("div", { class: "titles" },
      h("h1", {}, t("Procesy")),
      h("p", { class: "muted" }, t("{} w folderze {}", plural(drafts.length, "proces", "procesy", "procesów"), workspace))),
      h("div", { class: "actions" }, h("a", { class: "button primary", href: "#/new" }, t("Nowy proces: nagraj")))),
    takeFlash(),
    drafts.length
      ? h("div", { class: "grid" }, drafts.map((d) => h("a", { class: "card", href: `#/p/${encodeURIComponent(d.process)}` },
          h("h2", {}, d.title || d.process),
          h("div", { class: "facts" }, h("span", {}, plural(d.recordings, "nagranie", "nagrania", "nagrań"))))))
      : h("div", { class: "card empty" },
          h("h2", {}, t("Tu pojawią się Twoje procesy")),
          h("p", {}, t("Zrób proces raz w przeglądarce albo w programie Java, a Maptelo Lite zapisze go jako mapę: kroki, instrukcję (SOP), diagram BPMN i raport.")),
          h("a", { class: "button primary", href: "#/new" }, t("Nagraj pierwszy proces"))));
}

async function showLiteProcess(key) {
  const found = await load(`/api/recordings/${encodeURIComponent(key)}`);
  const named = titleOf(found, key);
  const problems = h("div");
  const row = (r) => {
    const make = h("button", { type: "button", class: r.map ? "link" : "primary", onclick: async () => {
      make.disabled = true;
      try { await makeMap(key, r.id); }
      catch (error) { fill(problems, problemsBox(error.problems || [error.message])); make.disabled = false; }
    } }, r.map ? t("Zrób mapę ponownie") : t("Zrób mapę"));
    return h("tr", {},
      h("td", {}, r.started ? new Date(r.started).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" }) : r.id),
      h("td", {}, r.problem ? h("span", { class: "chip bad" }, r.problem) : (r.note || "—")),
      h("td", { class: "num" }, r.actions ?? "—"),
      h("td", {}, h("div", { class: "actions" },
        r.map ? h("a", { class: "button primary", href: `#/p/${encodeURIComponent(key)}/map/${encodeURIComponent(r.id)}` }, t("Zobacz mapę")) : null,
        r.problem ? null : make)));
  };
  show(
    h("div", { class: "head" }, h("div", { class: "titles" },
      h("div", { class: "crumbs" }, h("a", { href: "#/" }, t("Procesy")), " / ", named),
      h("h1", {}, named)),
      h("div", { class: "actions" }, h("a", { class: "button primary", href: `#/new/${encodeURIComponent(key)}` }, t("Nagraj ponownie")))),
    takeFlash(),
    problems,
    found.length
      ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Kiedy", "Notatka", "Działania", "Mapa"].map((head) => h("th", {}, t(head))))),
          h("tbody", {}, found.map(row))))
      : h("p", {}, t("Ten proces nie ma jeszcze nagrań.")));
}

/* The SOP as a page: its headings, the table of data, the numbered steps with their notes and
   screenshots. Only what export/sop.py writes in its Markdown, built from elements and never
   from HTML: the words come from the recorded application. */
function sopWords(text) {
  const out = [];
  let rest = text;
  const mark = /`([^`]+)`|\*\*(.+?)\*\*|\*([^*\s][^*]*)\*/;
  for (let m = mark.exec(rest); m; m = mark.exec(rest)) {
    if (m.index) out.push(rest.slice(0, m.index));
    if (m[1] !== undefined) out.push(h("code", {}, m[1]));
    else if (m[2] !== undefined) out.push(h("strong", {}, sopWords(m[2])));
    else out.push(h("em", {}, sopWords(m[3])));
    rest = rest.slice(m.index + m[0].length);
  }
  if (rest) out.push(rest);
  return out;
}

function sopCells(line) {  // a table row; "\|" is a "|" inside a cell
  const inner = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  const cells = [];
  let cell = "";
  for (let i = 0; i < inner.length; i += 1) {
    if (inner[i] === "\\" && inner[i + 1] === "|") { cell += "|"; i += 1; }
    else if (inner[i] === "|") { cells.push(cell.trim()); cell = ""; }
    else cell += inner[i];
  }
  cells.push(cell.trim());
  return cells;
}

function sopPage(text, folder) {
  const page = h("div", { class: "sop" });
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let list = null;  // the open list: the steps (ol) or notes (ul)
  let item = null;  // its last item: a step's notes and screenshot go into it
  let paragraph = null;
  const end = () => { list = null; item = null; paragraph = null; };
  const picture = (alt, src) => {
    if (!/^[\w./-]+$/.test(src) || src.split("/").includes("..")) return h("p", { class: "muted" }, alt);
    const url = fileUrl(folder + src);
    return h("button", { type: "button", class: "shot", "aria-label": t("Powiększ: {}", alt), title: t("Powiększ"), onclick: () => zoom(url, alt) },
      h("img", { src: url, alt, loading: "lazy" }));
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) { paragraph = null; continue; }
    let m;
    if (item && /^\s{2,}\S/.test(line)) {  // under a list item
      if ((m = /^\s+!\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line))) item.append(picture(m[1], m[2]));
      else if ((m = /^\s+[-*] (.*)$/.exec(line))) {
        let notes = item.lastElementChild;
        if (!notes || notes.tagName !== "UL") { notes = h("ul"); item.append(notes); }
        notes.append(h("li", {}, sopWords(m[1])));
      } else item.append(" ", ...sopWords(line.trim()));
      continue;
    }
    if ((m = /^(#{1,3}) (.*)$/.exec(line))) {
      end();
      page.append(h(`h${m[1].length + 2}`, {}, sopWords(m[2])));
    } else if ((m = /^> ?(.*)$/.exec(line))) {
      end();
      const last = page.lastElementChild;
      if (last && last.tagName === "BLOCKQUOTE" && lines[i - 1].startsWith(">")) last.append(" ", ...sopWords(m[1]));
      else page.append(h("blockquote", {}, sopWords(m[1])));
    } else if (line.startsWith("|")) {
      end();
      const rows = [];
      for (; i < lines.length && lines[i].startsWith("|"); i += 1) rows.push(lines[i]);
      i -= 1;
      const body = rows.slice(1).filter((row) => !/^\|?(\s*:?-{3,}:?\s*\|)+\s*$/.test(row));
      page.append(h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, sopCells(rows[0]).map((cell) => h("th", {}, sopWords(cell))))),
        h("tbody", {}, body.map((row) => h("tr", {}, sopCells(row).map((cell) => h("td", {}, sopWords(cell)))))))));
    } else if ((m = /^(\d+)\. (.*)$/.exec(line))) {
      if (!list || list.tagName !== "OL") { end(); list = h("ol", { start: m[1] }); page.append(list); }
      item = h("li", { value: m[1] }, h("div", { class: "what" }, sopWords(m[2])));
      list.append(item);
    } else if ((m = /^[-*] (.*)$/.exec(line))) {
      if (!list || list.tagName !== "UL") { end(); list = h("ul"); page.append(list); }
      item = h("li", {}, sopWords(m[1]));
      list.append(item);
    } else if (paragraph) {
      paragraph.append(" ", ...sopWords(line.trim()));
    } else {
      end();
      const said = line.trim();
      paragraph = h("p", { class: /^\*[^*].*\*$/.test(said) ? "meta" : null }, sopWords(said));
      page.append(paragraph);
    }
  }
  return page;
}

async function showLiteMap(key, recording) {
  const found = await load(`/api/recordings/${encodeURIComponent(key)}`);
  const r = found.find((item) => item.id === recording);
  if (!r || !r.map) {
    show(problemsBox([t("Ta mapa jeszcze nie powstała.")]), h("p", {}, h("a", { href: `#/p/${encodeURIComponent(key)}` }, t("Wróć do procesu"))));
    return;
  }
  const files = r.map;
  const named = titleOf(found, key);
  const sop = h("div", {}, h("p", { class: "muted" }, t("Wczytuję instrukcję…")));
  if (files["sop.md"]) {
    const folder = files["sop.md"].slice(0, files["sop.md"].lastIndexOf("/") + 1);
    fetch(fileUrl(files["sop.md"]))
      .then((answer) => { if (!answer.ok) throw new Error(String(answer.status)); return answer.text(); })
      .then((text) => fill(sop, sopPage(text, folder)))
      .catch(() => fill(sop, h("p", { class: "muted" }, t("Nie udało się wczytać instrukcji: otwórz raport albo folder z plikami."))));
  }
  const problems = h("div");
  const again = h("button", { type: "button", onclick: async () => {
    again.disabled = true;
    try { await makeMap(key, recording); await showLiteMap(key, recording); }
    catch (error) { fill(problems, problemsBox(error.problems || [error.message])); again.disabled = false; }
  } }, t("Zrób mapę ponownie"));
  const when = r.started ? new Date(r.started).toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" }) : recording;
  show(
    h("div", { class: "head" }, h("div", { class: "titles" },
      h("div", { class: "crumbs" }, h("a", { href: "#/" }, t("Procesy")), " / ", h("a", { href: `#/p/${encodeURIComponent(key)}` }, named), t(" / mapa")),
      h("h1", {}, named),
      h("div", { class: "facts" }, h("span", {}, t("nagranie {}", when)), h("span", {}, plural(r.actions || 0, "działanie", "działania", "działań")), r.note ? h("span", {}, r.note) : null)),
      h("div", { class: "actions" },
        h("a", { class: "button primary", href: fileUrl(files["report.html"]), target: "_blank", rel: "noopener" }, t("Otwórz raport")),
        h("button", { type: "button", onclick: () => openPath(`maps/${key}/${recording}`) }, t("Folder z plikami")))),
    takeFlash(),
    problems,
    files["process.svg"] ? h("div", { class: "card diagram" }, h("img", { src: fileUrl(files["process.svg"]), alt: t("Diagram procesu {}", named) })) : null,
    h("div", { class: "card" },
      h("div", { class: "head" }, h("h2", {}, t("Instrukcja krok po kroku (SOP)")),
        h("div", { class: "actions" },
          files["sop.md"] ? h("a", { class: "button", href: fileUrl(files["sop.md"]), download: "" }, "SOP (Markdown)") : null,
          files["process.bpmn"] ? h("a", { class: "button", href: fileUrl(files["process.bpmn"]), download: "" }, "BPMN") : null,
          again)),
      sop));
}

// --- routes and the banner ----------------------------------------------------------------

const LITE_ROUTES = [
  [/^#?\/?$/, () => showLiteProcesses()],
  [/^#\/ready$/, () => showReady()],
  [/^#\/p\/([^/]+)$/, (m) => showLiteProcess(decodeURIComponent(m[1]))],
  [/^#\/p\/([^/]+)\/map\/([^/]+)$/, (m) => showLiteMap(decodeURIComponent(m[1]), decodeURIComponent(m[2]))],
  [/^#\/new$/, () => showRecordForm(null)],
  [/^#\/new\/([^/]+)$/, (m) => showRecordForm(decodeURIComponent(m[1]))],
  [/^#\/job\/([^/]+)$/, (m) => showJob(m[1])],
];

async function route() {
  const opened = ++navigation;
  leave();
  leave = () => {};
  const hash = location.hash || "#/";
  const section = { "#/runs": "runs", "#/ready": "ready", "#/agents": "agents" }[hash] || "processes";
  if (!hash.startsWith("#/job/")) {  // a job page keeps the section it was started from
    for (const link of document.querySelectorAll("[data-nav]")) {
      link.setAttribute("aria-current", link.dataset.nav === section ? "page" : "false");
    }
  }
  for (const [pattern, render] of LITE_ROUTES) {
    const match = pattern.exec(hash);
    if (!match) continue;
    try { await render(match); }
    catch (error) {
      if (error instanceof StaleError || opened !== navigation) return;  // a newer page is open
      if (error.status === 401) noAccess();
      else show(problemsBox(error.problems || [error.message]), h("p", {}, h("a", { href: "#/" }, t("Wróć do procesów"))));
    }
    return;
  }
  show(problemsBox([t("Nie ma takiej strony.")]), h("p", {}, h("a", { href: "#/" }, t("Wróć do procesów"))));
}

async function watchState() {
  try {
    const state = await api("/api/state");
    workspace = state.workspace;
    preferredBrowser = state.browser || null;
    browserRequired = Boolean(state.browser_required);
    if (state.lite && !lite) {
      lite = true;
      lang = state.lang || computerLanguage();
      applyLite();
    }
    document.getElementById("workspace").textContent = state.workspace;
    document.getElementById("version").textContent = `Maptelo ${lite ? "Lite " : ""}${state.version}`;
    const job = state.job;
    const onIt = job && location.hash === `#/job/${job.id}`;
    if (job && job.state === "running" && !onIt) {
      banner.hidden = false;
      fill(banner, h("span", { class: "spin" }), h("span", {}, t("Trwa: {}", job.title)), h("a", { href: `#/job/${job.id}` }, t("Zobacz")));
    } else banner.hidden = true;
  } catch (error) {
    if (error.status === 401) { noAccess(); return false; }
  }
  return true;
}

window.addEventListener("hashchange", route);
(async () => {
  if (await watchState()) {
    await route();
    setInterval(watchState, 3000);
  }
})();
