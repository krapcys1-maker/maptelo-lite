"""Normalization on small hand-made traces: one behaviour per test."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maptelo.mapping import normalize, slug
from maptelo.mapping.naming import unique
from maptelo.trace import ElementInfo, Trace, TraceEvent, TraceHeader, TraceState

URL = "http://app/form"


def element(name: str, role: str = "button", tag: str = "button", **extra: Any) -> ElementInfo:
    return ElementInfo(tag=tag, role=role, name=name, **extra)


def field(name: str) -> ElementInfo:
    return ElementInfo(tag="input", role="textbox", name=name, label=name)


class Builder:
    def __init__(self, start: str = URL) -> None:
        self.events: list[TraceEvent] = []
        self.states: dict[str, TraceState] = {}
        self.start = start
        self.t = 0.0

    def add(self, kind: str, t: float | None = None, **fields: Any) -> TraceEvent:
        self.t = t if t is not None else self.t + 1
        fields.setdefault("url", URL)
        event = TraceEvent(seq=len(self.events) + 1, t=self.t, type=kind, **fields)  # type: ignore[arg-type]
        self.events.append(event)
        return event

    def state(self, state_id: str, aria: str) -> str:
        self.states[state_id] = TraceState(id=state_id, t=self.t, url=URL, aria=aria)
        return state_id

    def trace(self) -> Trace:
        header = TraceHeader(
            recording_id="t", started_at=datetime(2026, 10, 7, tzinfo=UTC), start_url=self.start
        )
        return Trace(header=header, events=self.events, states=self.states)


def roles(trace: Trace) -> list[tuple[str, str | None, str]]:
    return [
        (a.kind, a.event.target.name if a.event.target else None, a.role)
        for a in normalize(trace).acts
    ]


def test_sign_in_at_the_start_is_a_precondition() -> None:
    b = Builder(start="http://app/login")
    b.add("navigate", value="http://app/login", url="http://app/login")
    b.add("fill", target=field("User"), value="anna", url="http://app/login")
    b.add("fill", target=field("Password"), secret=True, url="http://app/login")
    b.add("click", target=element("Sign in"), url="http://app/login")
    b.add("navigated", url="http://app/home")
    b.add("click", target=element("Report"), url="http://app/home")
    normalized = normalize(b.trace())
    assert [a.role for a in normalized.acts] == ["login", "login", "login", "login", "step"]
    assert normalized.start_url == "http://app/home"


def test_a_password_in_the_work_is_a_step_not_a_sign_in() -> None:
    """A new customer's account: many fields and a password typed twice on one form. Taken
    for a sign-in, the whole process vanished into a precondition (benchmark, OFBiz)."""
    b = Builder(start="http://app/customers/new")
    b.add("navigate", value="http://app/customers/new", url="http://app/customers/new")
    for name in ("First name", "Last name", "Email", "User name"):
        b.add("fill", target=field(name), value="x", url="http://app/customers/new")
    password = ElementInfo(tag="input", role="textbox", name="Password", label="Password")
    confirm = password.model_copy(update={"field": "CONFIRM_PASSWORD"})
    password = password.model_copy(update={"field": "PASSWORD"})
    b.add("fill", target=password, secret=True, url="http://app/customers/new")
    b.add("fill", target=confirm, secret=True, url="http://app/customers/new")
    b.add("click", target=element("Save"), url="http://app/customers/new")
    b.add("navigated", url="http://app/customers/12")
    normalized = normalize(b.trace())
    assert "login" not in [a.role for a in normalized.acts]
    fills = [a for a in normalized.steps if a.kind == "fill"]
    assert len(fills) == 6  # the password and its confirmation are two fields, two steps


def test_a_password_after_other_work_is_not_a_sign_in() -> None:
    b = Builder(start="http://app/home")
    b.add("navigate", value="http://app/home", url="http://app/home")
    b.add("click", target=element("Settings"), url="http://app/home")
    b.add("navigated", url="http://app/settings")
    b.add("fill", target=field("New password"), secret=True, url="http://app/settings")
    b.add("click", target=element("Change"), url="http://app/settings")
    b.add("navigated", url="http://app/settings/done")
    assert "login" not in [a.role for a in normalize(b.trace()).acts]


def test_dialog_that_shows_up_later_by_itself_is_an_interrupt() -> None:
    b = Builder()
    b.add("click", target=element("Search"))
    b.add("navigated", url=URL, t=1.1)
    b.add("appeared", target=element("Session expiring", role="dialog", tag="div"), t=1.8)
    b.add("click", target=element("Continue", dialog="Session expiring"), t=2.0)
    assert roles(b.trace())[-1] == ("click", "Continue", "interrupt")


def test_dialog_opened_by_the_previous_action_is_a_step() -> None:
    b = Builder()
    save = b.add("click", target=element("Save"))
    b.add("navigated", url=URL, t=save.t + 0.05)
    b.add("appeared", target=element("Confirm change", role="dialog", tag="div"), t=save.t + 0.1)
    b.add("click", target=element("Confirm", dialog="Confirm change"))
    assert roles(b.trace())[-1] == ("click", "Confirm", "step")


def test_dialog_already_on_screen_after_the_action_is_a_step() -> None:
    b = Builder()
    b.state("s1", '- dialog "Confirm change":\n  - button "Confirm"')
    b.add("click", target=element("Save"), state_after="s1")
    b.add("navigated", url=URL, t=b.t + 0.1)
    b.add("appeared", target=element("Confirm change", role="dialog", tag="div"), t=b.t + 1.0)
    b.add("click", target=element("Confirm", dialog="Confirm change"))
    assert roles(b.trace())[-1] == ("click", "Confirm", "step")


def test_rejected_then_corrected_attempt_is_folded_into_one_step() -> None:
    b = Builder()
    b.add("fill", target=field("Amount"), value="10")
    b.add("fill", target=field("Date"), value="2020-01-01")
    b.add("click", target=element("Save"))
    b.add("appeared", target=element("", role="alert", tag="div", text="Date is in the past."))
    b.add("fill", target=field("Date"), value="2030-01-01")
    b.add("click", target=element("Save"))
    normalized = normalize(b.trace())
    assert [(a.kind, a.field_name, a.role) for a in normalized.acts] == [
        ("fill", "Amount", "step"),
        ("fill", "Date", "superseded"),
        ("click", "Save", "superseded"),
        ("fill", "Date", "step"),
        ("click", "Save", "step"),
    ]
    attempt = normalized.acts[-1].attempts[0]
    assert attempt.message == "Date is in the past."
    assert attempt.values == {"Date": "2020-01-01"}


def test_clicks_on_plain_text_and_refills_are_noise() -> None:
    b = Builder()
    b.add("click", target=ElementInfo(tag="div", text="some text"))
    b.add("fill", target=field("Name"), value="An")
    b.add("fill", target=field("Name"), value="Anna")
    assert [r[2] for r in roles(b.trace())] == ["noise", "noise", "step"]


def test_a_click_left_out_as_stray_is_said_in_the_notes() -> None:
    """Nothing a person did disappears without a word (WONDERBREAD: a "Submit Comment" span the
    importer could not place in its button was taken for a stray click)."""
    from maptelo.mapping import map_trace

    b = Builder()
    b.add("fill", target=field("Comment"), value="Shipped soon")
    b.add("click", target=ElementInfo(tag="span", text="Submit Comment"))
    result = map_trace(b.trace(), lang="en")
    assert [s.action for s in result.model.steps] == ["navigate", "fill"]
    assert any("“Submit Comment” was left out" in note for note in result.notes)
    polish = map_trace(b.trace(), lang="pl")
    assert any("„Submit Comment” pominięto" in note for note in polish.notes)


def test_an_element_nothing_tells_is_a_persons_step() -> None:
    """An element without a name, words or an id (an imported recording could not place it)
    is a person's step with a note, never a model no robot can read."""
    from maptelo.mapping import map_trace

    b = Builder()
    b.add("click", target=ElementInfo(tag="div", role="button"))
    result = map_trace(b.trace(), lang="en")
    step = result.model.steps[-1]
    assert step.executor == "human"
    assert step.target is not None
    assert step.target[0].role == "button"
    assert any("no name, words or id" in note for note in result.notes)


def test_identifiers() -> None:
    assert slug("Valid from") == "valid_from"
    assert slug("Data ważności — źródło") == "data_waznosci_zrodlo"
    assert slug("123 go") == "x_123_go"
    taken: set[str] = set()
    assert [unique("save", taken) for _ in range(3)] == ["save", "save_2", "save_3"]


def test_saving_and_irreversible_steps_by_their_words_and_their_window() -> None:
    from maptelo.mapping import map_trace
    from maptelo.trace.locators import candidates_for

    def element(name: str, **extra: Any) -> ElementInfo:  # with its ladder, as recorded
        found = ElementInfo(tag="button", role="button", name=name, **extra)
        found.candidates = candidates_for(found)
        return found

    b = Builder(start="http://app/invoices/7")
    b.add("navigate", value="http://app/invoices/7", url="http://app/invoices/7")
    b.add("click", target=element("Wystaw fakturę"), url="http://app/invoices/7")
    b.add("click", target=element("Wyślij do KSeF"), url="http://app/invoices/7")
    warned = b.state(
        "s1",
        '- dialog "Usuń fakturę":\n  - paragraph: Tej operacji nie można cofnąć.\n  - button "Tak"',
    )
    b.add("click", target=element("Tak", dialog="Usuń fakturę"), url="http://app/invoices/7",
          state_before=warned)  # fmt: skip
    steps = map_trace(b.trace()).model.steps
    risks = {s.target[0].name: (s.risk.value if s.risk else None) for s in steps if s.target}
    assert risks == {"Wystaw fakturę": "commit", "Wyślij do KSeF": "irreversible",
                     "Tak": "irreversible"}  # fmt: skip


def test_a_code_from_the_phone_after_the_password_belongs_to_the_sign_in() -> None:
    b = Builder(start="http://bank/login")
    b.add("navigate", value="http://bank/login", url="http://bank/login")
    b.add("fill", target=field("Użytkownik"), value="kasia", url="http://bank/login")
    b.add("fill", target=field("Hasło"), secret=True, url="http://bank/login")
    b.add("click", target=element("Zaloguj"), url="http://bank/login")
    b.add("navigated", url="http://bank/login/totp")
    b.add("fill", target=field("Kod z aplikacji uwierzytelniającej"), value="614373",
          url="http://bank/login/totp")  # fmt: skip
    b.add("click", target=element("Potwierdź"), url="http://bank/login/totp")
    b.add("navigated", url="http://bank/paczki")
    b.add("click", target=element("Paczka 7", role="link", tag="a"), url="http://bank/paczki")
    normalized = normalize(b.trace())
    assert [a.role for a in normalized.acts].count("step") == 1  # only the work is left
    assert normalized.start_url == "http://bank/paczki"


def test_a_one_time_code_in_the_work_is_typed_by_a_person() -> None:
    from maptelo.mapping import map_trace
    from maptelo.trace.locators import candidates_for

    def with_ladder(found: ElementInfo) -> ElementInfo:
        found.candidates = candidates_for(found)
        return found

    b = Builder(start="http://bank/paczki/1")
    b.add("navigate", value="http://bank/paczki/1", url="http://bank/paczki/1")
    b.add("fill", target=with_ladder(field("Kod z aplikacji mobilnej")), value="936565",
          url="http://bank/paczki/1")  # fmt: skip
    b.add("fill", target=with_ladder(field("Kod produktu")), value="48212",
          url="http://bank/paczki/1")  # fmt: skip
    model = map_trace(b.trace()).model
    code = next(
        s for s in model.steps if s.target and s.target[0].name == "Kod z aplikacji mobilnej"
    )
    assert code.executor.value == "human"  # new every time: a robot cannot know it
    spec = model.inputs["kod_z_aplikacji_mobilnej"]
    assert (spec.secret, spec.required, spec.example) == (True, False, None)
    product = next(s for s in model.steps if s.target and s.target[0].name == "Kod produktu")
    assert product.executor.value == "deterministic"  # a code of a product is just data


LIST, ERP = "http://wl.test", "http://erp.test"


def test_opening_another_application_is_a_step_of_its_own() -> None:
    """The person looked a supplier up on the VAT white list, then typed the ERP's address:
    nothing was clicked, the page changed after the list's screen had settled. Taken for what
    “Szukaj” did, the model waited for the ERP's form after the search (benchmark)."""
    b = Builder(start=f"{LIST}/")
    b.add("navigate", value=f"{LIST}/", url=f"{LIST}/", state_after="s1")
    b.add("click", target=element("Szukaj"), url=f"{LIST}/", state_before="s1", state_after="s2")
    b.add("navigated", url=f"{LIST}/szukaj?nip=3123435783", state_before="s1", state_after="s2")
    b.add("navigated", url=f"{ERP}/dostawcy/nowy", state_before="s2", state_after="s3")
    b.add("fill", target=field("Nazwa"), value="Zbiciak", url=f"{ERP}/dostawcy/nowy")
    acts = normalize(b.trace()).acts
    assert [(a.kind, a.event.url, a.role) for a in acts] == [
        ("navigate", f"{LIST}/", "step"),
        ("click", f"{LIST}/", "step"),
        ("navigate", f"{ERP}/dostawcy/nowy", "step"),
        ("fill", f"{ERP}/dostawcy/nowy", "step"),
    ]
    assert acts[1].navigated_to() == f"{LIST}/szukaj?nip=3123435783"
    assert acts[2].event.value == f"{ERP}/dostawcy/nowy"


def test_opening_another_application_after_a_file_opened_in_a_tab_of_its_own() -> None:
    """The courier's label opens in a tab of its own and downloads; the person closes the tab
    and types the ERP's address (benchmark p10). The click's own screen is the tab's, the
    person's window stayed as it was: going to the ERP is still the person's step."""
    courier = "http://kurier.test"
    b = Builder(start=f"{courier}/przesylki/1")
    b.add(
        "navigate", value=f"{courier}/przesylki/1", url=f"{courier}/przesylki/1", state_after="s1"
    )
    b.states["s1"] = TraceState(id="s1", t=1, url=f"{courier}/przesylki/1", aria="", window=0)
    link = element("Pobierz etykietę (PDF)", role="link", tag="a")
    b.add("click", target=link, url=f"{courier}/przesylki/1", state_before="s1", state_after="s2")
    b.states["s2"] = TraceState(id="s2", t=2, url="", aria="", window=1)  # the label's tab
    b.add("downloaded", url=f"{courier}/przesylki/1", state_before="s1", state_after="s2")
    b.add("navigated", url=f"{ERP}/zamowienia/54", state_before="s1", state_after="s3")
    b.add("fill", target=field("Numer przesyłki"), value="SP1", url=f"{ERP}/zamowienia/54")
    acts = normalize(b.trace()).acts
    assert [(a.kind, a.event.url) for a in acts] == [
        ("navigate", f"{courier}/przesylki/1"),
        ("click", f"{courier}/przesylki/1"),
        ("navigate", f"{ERP}/zamowienia/54"),
        ("fill", f"{ERP}/zamowienia/54"),
    ]


def test_a_page_that_changes_again_within_its_application_is_still_the_result() -> None:
    """Within one application a page may change once more after it settled (a list that
    reloads itself): that is what the click did, not a step the person took."""
    b = Builder(start=f"{ERP}/orders")
    b.add("navigate", value=f"{ERP}/orders", url=f"{ERP}/orders", state_after="s1")
    b.add(
        "click", target=element("Save"), url=f"{ERP}/orders/1", state_before="s1", state_after="s2"
    )
    b.add("navigated", url=f"{ERP}/orders/1?saved=1", state_before="s2", state_after="s3")
    assert [a.kind for a in normalize(b.trace()).acts] == ["navigate", "click"]


def test_coming_back_from_a_sign_in_service_is_not_a_step() -> None:
    b = Builder(start=f"{ERP}/orders")
    b.add("navigate", value=f"{ERP}/orders", url=f"{ERP}/orders", state_after="s1")
    b.add(
        "click", target=element("Report"), url=f"{ERP}/orders", state_before="s1", state_after="s2"
    )
    callback = "http://bi.test/auth/callback?code=x1&state=y2"
    b.add("navigated", url=callback, state_before="s2", state_after="s3")
    assert [a.kind for a in normalize(b.trace()).acts] == ["navigate", "click"]


def test_signing_in_to_the_other_application_belongs_to_the_sign_in() -> None:
    """The ERP asked to sign in when the person opened it: that is a precondition (a robot
    comes with its session), and the ERP is opened where the sign-in led."""
    login = f"{ERP}/login?next=/dostawcy/nowy"
    b = Builder(start=f"{LIST}/")
    b.add("navigate", value=f"{LIST}/", url=f"{LIST}/", state_after="s1")
    b.add("click", target=element("Szukaj"), url=f"{LIST}/", state_before="s1", state_after="s2")
    b.add("navigated", url=login, state_before="s2", state_after="s3")
    b.add("fill", target=field("Użytkownik"), value="anna", url=login)
    b.add("fill", target=field("Hasło"), secret=True, url=login)
    b.add("click", target=element("Zaloguj"), url=login, state_before="s3", state_after="s4")
    b.add("navigated", url=f"{ERP}/dostawcy/nowy", state_before="s3", state_after="s4")
    b.add("fill", target=field("Nazwa"), value="Zbiciak", url=f"{ERP}/dostawcy/nowy")
    normalized = normalize(b.trace())
    assert [(a.kind, a.role) for a in normalized.acts] == [
        ("navigate", "step"),
        ("click", "step"),
        ("navigate", "step"),
        ("fill", "login"),
        ("fill", "login"),
        ("click", "login"),
        ("fill", "step"),
    ]
    assert normalized.acts[2].event.url == f"{ERP}/dostawcy/nowy"
    assert normalized.start_url == f"{LIST}/"


def test_enter_and_the_click_the_browser_makes_for_it_are_one_act() -> None:
    """Enter in a form's field makes the browser click the form's button at once: one act,
    the click, as for people who click it (benchmark: style_rule_on_user)."""
    b = Builder()
    b.add("navigate", value=URL, state_after="s1")
    b.add("fill", target=field("Produkt"), value="12187-H", state_before="s1")
    b.add("press", target=field("Produkt"), value="Enter", t=3.0, state_before="s2")
    b.add("click", target=element("Szukaj"), t=3.01, state_before="s2", state_after="s3")
    assert roles(b.trace()) == [
        ("navigate", None, "step"),
        ("fill", "Produkt", "step"),
        ("press", "Produkt", "superseded"),
        ("click", "Szukaj", "step"),
    ]


def test_enter_with_no_button_to_click_is_a_step() -> None:
    b = Builder()
    b.add("navigate", value=URL, state_after="s1")
    b.add("press", target=field("Szukaj"), value="Enter", t=3.0, state_before="s1")
    b.add("click", target=element("Dalej"), t=9.0, state_before="s2", state_after="s3")
    assert [role for *_, role in roles(b.trace())] == ["step", "step", "step"]


def test_a_click_that_only_opened_the_file_dialog_is_part_of_the_upload() -> None:
    """A "Wybierz plik" button over a hidden file field: the robot puts the file in directly,
    and a click on the button would open a dialog nobody answers."""
    b = Builder()
    b.add("navigate", value=URL, state_after="s1")
    b.add("click", target=element("Wybierz plik"), state_before="s1")
    chosen = ElementInfo(tag="input", type="file", name="Etykieta", label="Etykieta")
    b.add("upload", target=chosen, files=["etykieta.pdf"], state_before="s1")
    b.add("click", target=element("Dodaj załącznik"), state_before="s1", state_after="s2")
    b.add("appeared", target=element("Plik", role="textbox"), state_before="s1", state_after="s2")
    b.add("upload", target=chosen, files=["skan.pdf"], state_before="s2")
    assert [role for *_, role in roles(b.trace())] == [
        "step",
        "superseded",
        "step",
        "step",
        "step",
    ]  # fmt: skip  (a click that showed the field first stays a step)
