// Maptelo recorder: injected into every page of a recording browser context.
// It reports user actions (with a description of the element) and significant DOM
// changes to Python through the exposed binding. It never sends password values.
(() => {
  "use strict";
  // Once a document, not once a window: a window opened by window.open first holds an empty
  // document, and the page that replaces it keeps the same window object (same origin), while
  // the listeners below live on the document (benchmark g031: a chooser window's search).
  if (document.__mapteloInstalled) return;
  document.__mapteloInstalled = true;
  window.__mapteloLastMutation = performance.now();
  window.__mapteloSignificant = 0;

  const emit = (payload) => {
    const send = window.__mapteloEmit;
    if (typeof send !== "function") return;
    payload.ts = Date.now();
    payload.url = location.href;
    payload.title = document.title;
    try {
      send(payload);
    } catch (_) {
      /* the page is going away */
    }
  };

  // Dialogs of the browser itself (alert, confirm, prompt) are no part of the page: what they
  // asked and how the person answered is reported from the page's own functions, which the
  // page calls and waits for (benchmark g032, g034). Once a window: they live on it.
  if (!window.__mapteloDialogs) {
    window.__mapteloDialogs = true;
    for (const kind of ["alert", "confirm", "prompt"]) {
      const native = window[kind];
      if (typeof native !== "function") continue;
      window[kind] = function (...args) {
        const answer = native.apply(window, args);
        const accepted = kind === "alert" ? true : kind === "confirm" ? Boolean(answer) : answer !== null;
        const value = kind === "prompt" && answer !== null && answer !== undefined ? String(answer) : null;
        const message = args.length ? String(args[0] ?? "") : "";
        emit({ type: "dialog", dialog: { kind, message, accepted, value } });
        return answer;
      };
    }
  }

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const TEXT_TYPES = new Set([
    "", "text", "email", "search", "tel", "url", "number", "password",
    "date", "datetime-local", "month", "time", "week",
  ]);
  const CLICKABLE = [
    "a[href]", "button", "input", "select", "textarea", "label", "summary",
    "[role=button]", "[role=link]", "[role=menuitem]", "[role=tab]", "[role=checkbox]",
    "[role=radio]", "[role=option]", "[role=switch]", "[onclick]",
  ].join(",");
  const SIGNIFICANT = "[role=dialog],[role=alertdialog],[role=alert],[role=status],dialog,[aria-modal=true]";
  const INTERACTIVE = "a[href],button,input,select,textarea,[role=button],[role=link]";

  const inputType = (el) => (el.getAttribute("type") || "").toLowerCase();
  const isTextInput = (el) =>
    (el.tagName === "INPUT" && TEXT_TYPES.has(inputType(el))) ||
    el.tagName === "TEXTAREA" ||
    el.isContentEditable === true;

  function implicitRole(el) {
    const tag = el.tagName.toLowerCase();
    const type = inputType(el);
    if (tag === "a") return el.hasAttribute("href") ? "link" : null;
    if (tag === "button" || tag === "summary") return "button";
    if (tag === "input") {
      if (["button", "submit", "reset", "image"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "range") return "slider";
      if (type === "number") return "spinbutton";
      if (type === "search") return "searchbox";
      if (type === "hidden" || type === "file") return null;  // a file has no role of its own
      return "textbox";
    }
    if (tag === "textarea") return "textbox";
    if (tag === "select") return el.multiple || el.size > 1 ? "listbox" : "combobox";
    if (tag === "option") return "option";
    if (tag === "table") return "table";
    if (tag === "tr") return "row";
    if (tag === "td") return "cell";
    if (tag === "th") return "columnheader";
    if (tag === "dialog") return "dialog";
    if (tag === "img") return el.getAttribute("alt") === "" ? null : "img";
    if (/^h[1-6]$/.test(tag)) return "heading";
    return null;
  }

  const roleOf = (el) => clean(el.getAttribute("role")).split(" ")[0] || implicitRole(el);

  // The words a screen reader says for an element: its text without what is hidden from it
  // (aria-hidden: a sort arrow, an icon's glyph), as the browser names it.
  function spoken(el) {
    if (!el.querySelector('[aria-hidden="true"]')) return el.innerText;
    const copy = el.cloneNode(true);
    copy.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
    return copy.textContent;
  }

  function labelText(el) {
    const labels = el.labels ? Array.from(el.labels) : [];
    const text = clean(labels.map(labelWords).join(" "));
    return text || null;
  }

  // A label that holds its field (<label>Waluta <select>...</select></label>) names it with its
  // own words only: not the list's options nor what is typed (as the browser names the field).
  function labelWords(label) {
    if (!label.querySelector("select, input, textarea, button, [contenteditable]")) return spoken(label);
    const copy = label.cloneNode(true);
    copy.querySelectorAll("select, input, textarea, button, [contenteditable]").forEach((c) => c.remove());
    return copy.textContent;
  }

  function byId(el, id) {
    // ids are looked up where the element lives: its document, or its web component's shadow
    const root = el.getRootNode();
    return (root && root.getElementById ? root.getElementById(id) : null) ||
      document.getElementById(id);
  }

  function accessibleName(el) {
    const ids = clean(el.getAttribute("aria-labelledby"));
    if (ids) {
      const text = clean(
        ids.split(" ").map((id) => byId(el, id)).filter(Boolean)
          .map((n) => spoken(n)).join(" "),
      );
      if (text) return text;
    }
    const aria = clean(el.getAttribute("aria-label"));
    if (aria) return aria;
    const label = labelText(el);
    if (label) return label;
    const tag = el.tagName.toLowerCase();
    if (tag === "input" && ["button", "submit", "reset"].includes(inputType(el))) {
      return clean(el.value) || null;
    }
    if (tag === "img") return clean(el.getAttribute("alt")) || null;
    if (tag === "table") {
      const caption = el.querySelector(":scope > caption");
      if (caption) return clean(caption.innerText) || null;
    }
    const role = roleOf(el);
    const byContent = ["button", "link", "tab", "menuitem", "option", "heading", "cell",
      "columnheader", "checkbox", "radio", "switch"];
    if (byContent.includes(role)) {
      const text = clean(spoken(el)).slice(0, 120);
      if (text) return text;
      const labelled = el.querySelectorAll("[aria-label]");  // an icon that says what it is
      if (labelled.length === 1) {
        const said = clean(labelled[0].getAttribute("aria-label"));
        if (said) return said;
      }
    }
    const title = clean(el.getAttribute("title"));
    if (title) return title;
    return clean(el.getAttribute("placeholder")) || null;
  }

  function tooltipOf(el) {
    if (clean(el.innerText) || el.tagName === "INPUT" || el.tagName === "TEXTAREA") return null;
    const own = clean(el.getAttribute("title"));
    if (own) return own;
    const titled = el.querySelectorAll("[title]");
    return titled.length === 1 ? clean(titled[0].getAttribute("title")) || null : null;
  }

  function cssPath(el) {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 8) {
      if (node.id && document.querySelectorAll("#" + CSS.escape(node.id)).length === 1) {
        parts.unshift("#" + CSS.escape(node.id));
        break;
      }
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const same = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      parts.unshift(same.length > 1 ? tag + ":nth-of-type(" + (same.indexOf(node) + 1) + ")" : tag);
      node = parent;
    }
    return parts.join(" > ");
  }

  function rowContext(el) {
    const row = el.closest("tr");
    const table = row ? row.closest("table") : null;
    if (!row || !table) return null;
    // a column's header (sorting by it) is no row of the table's records
    if (row.parentElement && row.parentElement.tagName === "THEAD") return null;
    const headers = Array.from(table.querySelectorAll("thead th")).map((th) => clean(spoken(th)));
    const cells = {};
    Array.from(row.children)
      .filter((c) => c.tagName === "TD" || c.tagName === "TH")
      .forEach((cell, i) => {
        cells[headers[i] || "#" + (i + 1)] = clean(spoken(cell));
      });
    const index = row.parentElement ? Array.from(row.parentElement.children).indexOf(row) : null;
    const context = { table: accessibleName(table), cells, index };
    // the order the table shows its rows in (aria-sort): its first row is then the newest
    // (or the oldest) of something, not a record of its own (benchmark M5)
    const sorted = table.querySelector('thead th[aria-sort="ascending"], thead th[aria-sort="descending"]');
    if (sorted) {
      context.sorted_by = clean(spoken(sorted)) || null;
      context.sort_order = sorted.getAttribute("aria-sort");
    }
    return context;
  }

  function columnOf(el) {
    // The header of the column an element sits in: how people find unlabeled grid inputs.
    const cell = el.closest("td");
    const row = cell ? cell.parentElement : null;
    const table = cell ? cell.closest("table") : null;
    if (!cell || !row || !table) return null;
    const cells = Array.from(row.children).filter((c) => c.tagName === "TD" || c.tagName === "TH");
    const header = table.querySelectorAll("thead th")[cells.indexOf(cell)];
    const text = header ? clean(spoken(header)) : "";
    return text || null;
  }

  function actionOf(el) {
    // What a button does, by name: <button name="action_confirm"> (Odoo writes every
    // business button so). It stays when the words change or are translated.
    const kind = (el.getAttribute("type") || "").toLowerCase();
    const button = el.tagName === "BUTTON" ||
      (el.tagName === "INPUT" && ["submit", "button", "image"].includes(kind));
    const name = button ? clean(el.getAttribute("name")) : null;
    if (!name) return null;
    // A name other buttons have too (name="action", told apart by value: benchmark p02) says
    // nothing about which button it is.
    const others = Array.from(document.querySelectorAll("button[name], input[name]"))
      .filter((other) => other !== el && clean(other.getAttribute("name")) === name);
    return others.length ? null : name;
  }

  function submitsFor(el) {
    // A button that sends a form: the name of a field only that form sends (a visible one
    // first). An update renames the button more often than what its form sends.
    const kind = (el.getAttribute("type") || "").toLowerCase();
    const sends = (el.tagName === "BUTTON" && (kind === "" || kind === "submit"))
      || (el.tagName === "INPUT" && (kind === "submit" || kind === "image"));
    if (!sends || !el.form) return null;
    const named = Array.from(el.form.elements).filter((c) => c !== el && c.name);
    const shown = named.filter((c) => c.type !== "hidden");
    for (const control of [...shown, ...named]) {
      const same = Array.from(document.getElementsByName(control.name));
      if (same.every((other) => other.form === el.form)) return control.name;
    }
    return null;
  }

  function fieldName(el) {
    // The name a form sends the value under: on the control, or on the one element around
    // it that holds only this control (Odoo's field widgets). Words change; it rarely does.
    const tag = el.tagName;
    if (tag !== "INPUT" && tag !== "SELECT" && tag !== "TEXTAREA") return null;
    const own = el.getAttribute("name");
    if (own) return own;
    let node = el.parentElement;
    for (let depth = 0; node && depth < 4; depth++, node = node.parentElement) {
      const name = node.getAttribute("name");
      if (!name || node.tagName === "FORM") continue;
      const controls = Array.from(node.querySelectorAll("input, select, textarea"))
        .filter((c) => c.type !== "hidden" && c.offsetParent !== null);
      return controls.length === 1 ? name : null;
    }
    return null;
  }

  function dialogName(el) {
    const dialog = el.closest("[role=dialog],[role=alertdialog],dialog");
    return dialog ? accessibleName(dialog) || "" : null;
  }

  function describe(el) {
    const box = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || null,
      autocomplete: el.getAttribute("autocomplete") || null,
      role: roleOf(el),
      name: accessibleName(el),
      label: labelText(el),
      field: fieldName(el),
      submits: submitsFor(el),
      placeholder: el.getAttribute("placeholder") || null,
      testid: el.getAttribute("data-testid") || null,
      action: actionOf(el),
      text: el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA"
        ? null : clean(el.innerText).slice(0, 160) || null,
      title: tooltipOf(el),
      id: el.id || null,
      css: cssPath(el),
      bbox: [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)],
      row: rowContext(el),
      column: columnOf(el),
      dialog: dialogName(el),
    };
  }

  // --- Calendars ---------------------------------------------------------------------
  // A click on a day of a calendar carries what is around it, as a person sees it: the other
  // days, the month shown, what moves it, the field it is for. Whether it was a calendar, and
  // which day, is decided when the recording is mapped (mapping/normalize.py).

  const DAYLIKE = /^\d{1,2}$|(?:^|\D)(?:19|20|21)\d\d(?:\D|$)/;
  const YEAR = /(?:^|\D)(?:19|20|21)\d\d(?:\D|$)/;
  const ARROW = /^(?:nast[e\u0119]pn|next|poprzedn|prev|[\u2039\u203a\u00ab\u00bb<>\u2190\u2192])/i;
  let lastField = null;

  const shownNow = (el) => el.getClientRects().length > 0;

  function kindOf(el) {
    const role = roleOf(el);
    if (role) return role;
    const first = el.classList.length ? "." + CSS.escape(el.classList[0]) : "";
    return el.tagName.toLowerCase() + first;
  }

  function ownClasses(el) {
    // A CSS selector of the element's class names that finds only it: names people wrote
    // (o_datetime_picker), not generated ones (css-1x2y3z).
    const tag = el.tagName.toLowerCase();
    const names = Array.from(el.classList).filter((c) =>
      /^[A-Za-z][\w-]{2,39}$/.test(c) && !/^(css|sc|jsx|emotion|svelte)-/.test(c) &&
      !/\d{3}/.test(c));
    const tries = names.map((c) => [c]);
    names.forEach((c, i) => names.slice(i + 1).forEach((d) => tries.push([c, d])));
    for (const parts of tries.slice(0, 40)) {
      const selector = tag + parts.map((c) => "." + CSS.escape(c)).join("");
      if (document.querySelectorAll(selector).length === 1) return selector;
    }
    return null;
  }

  function calendarAround(el) {
    const name = accessibleName(el) || "";
    if (name.length > 80 || !DAYLIKE.test(name)) return null;
    const kind = kindOf(el);
    let box = el.parentElement;
    let days = null;
    for (let depth = 0; box && box !== document.body && depth < 6; depth++) {
      const all = box.getElementsByTagName("*");
      if (all.length > 4000) return null;
      const same = Array.from(all).filter((e) => kindOf(e) === kind && shownNow(e));
      if (same.length >= 28) {
        days = same;
        break;
      }
      box = box.parentElement;
    }
    if (!days || !days.includes(el)) return null;
    const inDay = (e) => days.some((d) => d === e || d.contains(e));
    const ofDays = (e) => inDay(e) || days.some((d) => e.contains(d));
    const MOVES = INTERACTIVE + ",[title],[aria-label],th";
    const controlsIn = (holder) => {
      const found = [];
      for (const c of holder.querySelectorAll(MOVES)) {
        const clicked = c.closest(CLICKABLE) || c;
        if (ofDays(clicked) || !holder.contains(clicked) || !shownNow(clicked)) continue;
        if (!found.includes(clicked)) found.push(clicked);
      }
      return found;
    };
    const said = (c) => accessibleName(c) || tooltipOf(c) || clean(c.innerText);
    const hasArrows = (holder) => controlsIn(holder).some((c) => ARROW.test(said(c)));
    const hasMonth = (holder) => Array.from(holder.querySelectorAll("*")).some((e) => {
      if (inDay(e) || !shownNow(e)) return false;
      const text = clean(e.innerText);
      return text.length <= 40 && YEAR.test(text);
    });
    // The days, up to the month over them and the arrows that move them (the headers of
    // the days of the week may have tooltips too: they move nothing).
    const levels = [box];
    for (let up = box.parentElement; levels.length < 5 && up && up !== document.body;) {
      levels.push(up);
      up = up.parentElement;
    }
    const yearInDays = YEAR.test(name);
    const seen = levels.map((holder) => [yearInDays || hasMonth(holder), hasArrows(holder)]);
    const pick = (test) => levels.find((_, i) => test(seen[i]));
    const around = pick(([month, arrows]) => month && arrows) ||
      pick(([month]) => month) || pick(([, arrows]) => arrows) || box;
    const controls = controlsIn(around).slice(0, 24);
    const texts = [];
    for (const e of around.querySelectorAll("*")) {
      if (inDay(e)) continue;
      const text = shownNow(e) ? clean(e.innerText) : "";
      if (text && text.length <= 40 && !texts.includes(text)) texts.push(text);
      if (texts.length >= 40) break;
    }
    const withClasses = (e) => Object.assign(describe(e), { classes: ownClasses(e) });
    const field = lastField && lastField.isConnected && shownNow(lastField) ? lastField : null;
    return {
      days: days.slice(0, 84).map((d) => accessibleName(d) || clean(d.innerText)),
      index: days.indexOf(el),
      role: roleOf(el),
      css: roleOf(el) ? null : kind,
      texts,
      controls: controls.map(withClasses),
      box: withClasses(around),
      field: field ? describe(field) : null,
    };
  }

  document.addEventListener("focusin", (e) => {
    const el = realTarget(e);
    if (el instanceof Element && isTextInput(el)) lastField = el;
  }, true);

  // Studio's pointer (studio/picker.js) describes the element a person points at the same way.
  window.__mapteloDescribe = describe;

  // --- Actions ---------------------------------------------------------------------

  const edited = new Set();

  // The element a person really used: inside a web component (shadow DOM) the document only
  // sees the component, so the event's path says which field it was.
  function realTarget(e) {
    const path = typeof e.composedPath === "function" ? e.composedPath() : [];
    const first = path.length ? path[0] : e.target;
    return first instanceof Element ? first : e.target;
  }

  function flushFill(el) {
    if (!edited.has(el)) return;
    edited.delete(el);
    const secret = el.tagName === "INPUT" && inputType(el) === "password";
    // a field built from a <div contenteditable> has no value: what it shows is the value
    const value = el.isContentEditable ? clean(el.innerText) : el.value;
    emit({ type: "fill", target: describe(el), value: secret ? null : value, secret });
  }

  function flushAll() {
    Array.from(edited).forEach(flushFill);
  }

  // How much the person typed and when last: the recorder takes the screen's picture again
  // once the typing stops, as what is typed reaches the trace only when the field is left.
  window.__mapteloTyped = 0;
  window.__mapteloTypedAt = 0;

  document.addEventListener("input", (e) => {
    const el = realTarget(e);
    if (e.isTrusted && isTextInput(el)) {
      edited.add(el);
      window.__mapteloTyped += 1;
      window.__mapteloTypedAt = performance.now();
    }
  }, true);

  // Installed once the page had loaded (a window window.open filled, benchmark g031): what
  // the person is typing right now still counts, when they leave the field.
  const typing = document.activeElement;
  if (typing && isTextInput(typing) && typing.value !== typing.defaultValue) edited.add(typing);

  // "change" does not leave a web component, and a <div contenteditable> never fires it:
  // leaving the field ends the typing too.
  document.addEventListener("focusout", (e) => {
    const el = realTarget(e);
    if (e.isTrusted && isTextInput(el)) flushFill(el);
  }, true);

  const isFileInput = (el) => el.tagName === "INPUT" && inputType(el) === "file";

  document.addEventListener("change", (e) => {
    const el = realTarget(e);
    // Automation tools change <select> and choose files with synthetic events; people never
    // do it otherwise.
    if (!e.isTrusted && el.tagName !== "SELECT" && !isFileInput(el)) return;
    // what was typed elsewhere came before this change, though its field may still have the
    // cursor (an automation tool changes a <select> without moving it; benchmark g008, g027)
    if (!isTextInput(el)) flushAll();
    if (isFileInput(el)) {
      // the files' names only: never what is in them, nor the folder they came from
      const files = Array.from(el.files || []).map((file) => file.name);
      if (files.length) emit({ type: "upload", target: describe(el), files });
    } else if (isTextInput(el)) {
      flushFill(el);
    } else if (el.tagName === "SELECT") {
      const option = el.selectedOptions[0];
      emit({ type: "select", target: describe(el), value: el.value,
        option_label: option ? clean(option.textContent) : null });
    } else if (el.tagName === "INPUT" && ["checkbox", "radio"].includes(inputType(el))) {
      emit({ type: el.checked ? "check" : "uncheck", target: describe(el) });
    }
  }, true);

  // A list one chooses from with the keys only (a combo box one cannot type into, a list box:
  // a platform's own list of reasons, benchmark M6): its arrows are the person's steps.
  const keyList = (el) => {
    if (!el || el.tagName === "SELECT") return false;
    const role = roleOf(el);
    return role === "listbox" || (role === "combobox" && (!isTextInput(el) || el.readOnly === true));
  };

  document.addEventListener("keydown", (e) => {
    if (!e.isTrusted) return;
    const el = realTarget(e);
    const arrow = ["ArrowDown", "ArrowUp"].includes(e.key) && keyList(el);
    if (!arrow && !["Enter", "Escape", "Tab"].includes(e.key)) return;
    if (isTextInput(el)) flushFill(el);
    if (e.key === "Tab") return;
    flushAll();  // a key that acts comes after all the typing before it
    const onPage = !el || el === document.body || el === document.documentElement;
    emit({ type: "press", target: onPage ? null : describe(el), value: e.key });
  }, true);

  document.addEventListener("click", (e) => {
    if (!e.isTrusted) return;
    const target = realTarget(e);
    const raw = target instanceof Element ? target : null;
    if (!raw) return;
    const el = raw.closest(CLICKABLE) || raw;
    if (isTextInput(el) || el.tagName === "SELECT" || el.tagName === "OPTION") return;
    if (el.tagName === "INPUT" && ["checkbox", "radio"].includes(inputType(el))) return;
    if (isFileInput(el)) return;  // it opens the file dialog: the files chosen are the step
    if (el.tagName === "LABEL" && el.control) return;  // the control reports its own change
    flushAll();
    const described = describe(el);
    const calendar = calendarAround(el);
    if (calendar) described.calendar = calendar;
    emit({ type: "click", target: described });
  }, true);

  // --- Observations ----------------------------------------------------------------

  // Describe an appeared element once its content is parsed, not at insertion.
  const announced = new WeakSet();

  function reportAppeared(el) {
    if (announced.has(el)) return;
    announced.add(el);
    const report = () => {
      if (el.isConnected) emit({ type: "appeared", target: describe(el) });
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", report, { once: true });
    } else {
      setTimeout(report, 50);
    }
  }

  function watch(root) {
    const observer = new MutationObserver((mutations) => {
      window.__mapteloLastMutation = performance.now();
      for (const m of mutations) {
        if (m.type === "attributes") {
          window.__mapteloSignificant += 1;
          continue;
        }
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          const hits = node.matches(SIGNIFICANT)
            ? [node] : Array.from(node.querySelectorAll(SIGNIFICANT));
          if (hits.length || node.matches(INTERACTIVE) || node.querySelector(INTERACTIVE)) {
            window.__mapteloSignificant += 1;
          }
          hits.forEach(reportAppeared);
        }
      }
    });
    observer.observe(root, {
      subtree: true, childList: true, attributes: true,
      attributeFilter: ["hidden", "aria-hidden", "open"],
    });
  }

  // Observing the document itself also catches elements inserted while the page parses.
  watch(document);

  window.__mapteloPageState = () => ({
    ready: document.readyState,
    quietMs: performance.now() - window.__mapteloLastMutation,
    significant: window.__mapteloSignificant,
    typed: window.__mapteloTyped || 0,
    typedQuietMs: performance.now() - (window.__mapteloTypedAt || 0),
    document: performance.timeOrigin,
    passwords: Array.from(document.querySelectorAll("input[type=password]"))
      .map((input) => input.value).filter((v) => v.length > 0),
  });
})();
