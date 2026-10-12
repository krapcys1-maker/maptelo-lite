"""MiniERP web application.

Maptelo's test bench: every kind of trouble a real legacy system causes (popups, slow
pages, confirmation dialogs, a success banner that lies, layout drift, duplicate saves,
saves that fail before or after storing, slow saves, a read channel that lags or fails)
can be switched on deterministically, from the command line or the testbed API.
The /api/* endpoints are the independent channel used to verify what really got saved.
"""

from __future__ import annotations

import random
import re
import secrets
import threading
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from minierp.config import Chaos, Settings
from minierp.layout import LAYOUTS, Texts, drifted
from minierp.seed import seed_data
from minierp.store import Product, Store, VersionRow

HERE = Path(__file__).parent
SESSION_COOKIE = "minierp_session"
NBSP = chr(0xA0)  # non-breaking space, common in pasted numbers
_PRICE = re.compile(r"^\d+(\.\d{1,2})?$")
_SAVED = re.compile(r"^V\d+$")
_FAILED_PAGE = (
    "<!doctype html><html><head><title>{code} {reason}</title></head><body>"
    "<h1>{code} {reason}</h1><p>The server could not complete the request.</p></body></html>"
)


class Testbed:
    """Mutable state of one running MiniERP: data, sessions, chaos and the event log."""

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.chaos = settings.chaos
        self.store = Store()
        self.sessions: set[str] = set()
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._rng = random.Random(settings.seed)
        self.reset()

    def today(self) -> date:
        return self.settings.today or date.today()

    def reset(self) -> None:
        with self._lock:
            self._rng = random.Random(self.settings.seed)
            self.events.clear()
        self.store.load(seed_data(self.today()))

    def texts(self) -> Texts:
        """The screens' words and ids: a layout, or one drifted from it by a seed."""
        if self.chaos.drift is None:
            return LAYOUTS[self.chaos.layout]
        return drifted(self.chaos.drift, self.chaos.drift_rate, LAYOUTS[self.chaos.layout])[0]

    def drift_changes(self) -> list[str]:
        if self.chaos.drift is None:
            return []
        return drifted(self.chaos.drift, self.chaos.drift_rate, LAYOUTS[self.chaos.layout])[1]

    def log(self, kind: str, **details: Any) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events) + 1, "type": kind, **details})

    def page_chaos(self, path: str) -> dict[str, int]:
        """Decide, for one page view, whether it loads slowly and shows the session popup."""
        chaos = self.chaos
        decided: dict[str, int] = {}
        with self._lock:
            if chaos.slow_load_max_ms:
                decided["load_delay_ms"] = self._rng.randint(0, chaos.slow_load_max_ms)
            if chaos.session_popup_rate and self._rng.random() < chaos.session_popup_rate:
                decided["session_popup_ms"] = self._rng.randint(*chaos.session_popup_delay_ms)
        if decided.get("load_delay_ms"):
            self.log("slow_load", path=path, delay_ms=decided["load_delay_ms"])
        if "session_popup_ms" in decided:
            self.log("session_popup", path=path, delay_ms=decided["session_popup_ms"])
        return decided

    def banner_lies(self) -> bool:
        with self._lock:
            rate = self.chaos.lying_banner_rate
            return rate > 0 and self._rng.random() < rate

    def save_trouble(self) -> tuple[str | None, int]:
        """For one save: how it fails ("error" before storing, "lost" after) and how slow it
        is. Decided up front, in one go, so a seed always gives the same story."""
        chaos = self.chaos
        failing = chaos.save_error_rate + chaos.lost_response_rate
        with self._lock:  # no draw for trouble that is off: older seeds keep their story
            delay = self._rng.randint(0, chaos.slow_save_max_ms) if chaos.slow_save_max_ms else 0
            roll = self._rng.random() if failing else 1.0
        if roll < chaos.save_error_rate:
            return "error", delay
        if roll < chaos.save_error_rate + chaos.lost_response_rate:
            return "lost", delay
        return None, delay

    def read_fails(self) -> bool:
        with self._lock:
            rate = self.chaos.read_error_rate
            return rate > 0 and self._rng.random() < rate


def parse_price(text: str) -> Decimal | None:
    cleaned = text.strip().replace(" ", "").replace(NBSP, "")
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    if not _PRICE.match(cleaned):
        return None
    try:
        price = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return price if price > 0 else None


def parse_day(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/pricing"


def _product_url(product: Product) -> str:
    return f"/pricing/product/{product.customer_id}/{quote(product.cpn)}"


def create_app(settings: Settings | None = None) -> FastAPI:
    tb = Testbed(settings or Settings())
    app = FastAPI(title="MiniERP", docs_url="/api/docs", redoc_url=None)
    app.state.testbed = tb
    templates = Jinja2Templates(directory=HERE / "templates")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def logged_in(request: Request) -> bool:
        return request.cookies.get(SESSION_COOKIE) in tb.sessions

    def to_login(next_path: str) -> RedirectResponse:
        return RedirectResponse(f"/login?next={quote(next_path)}", status_code=303)

    def page(request: Request, name: str, status_code: int = 200, **context: Any) -> Response:
        context.update(
            L=tb.texts(),
            layout=tb.chaos.layout,
            chaos=tb.page_chaos(request.url.path),
            user=tb.settings.username if logged_in(request) else None,
        )
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    def product_page(
        request: Request,
        product: Product,
        *,
        base_id: int | None = None,
        saved: str | None = None,
        error: str | None = None,
        form: dict[str, str] | None = None,
        confirm: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> Response:
        texts = tb.texts()
        rows = tb.store.rows(product, tb.today())
        active = [r for r in rows if r.status == "Active"]
        base: VersionRow | None = None
        info = None
        if base_id is not None:
            base = next((r for r in rows if r.version.id == base_id), None)
            if base is None or base.status != "Active":
                error = error or "Only the active price version can be changed."
                base = None
        elif len(rows) == 1 and active:
            base = active[0]
        else:
            info = texts.choose_version if active else texts.no_active
        return page(
            request,
            "product.html",
            status_code,
            product=product,
            customer=tb.store.customer(product.customer_id),
            rows=rows,
            base=base.version if base else None,
            saved=saved if saved and _SAVED.match(saved) else None,
            error=error,
            info=info,
            form=form or {},
            confirm=confirm,
            action=_product_url(product) + "/price",
        )

    # --- Session ---------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/pricing", status_code=303)

    @app.get("/login", include_in_schema=False)
    def login_form(
        request: Request, next_path: Annotated[str, Query(alias="next")] = "/pricing"
    ) -> Response:
        if logged_in(request):
            return RedirectResponse(_safe_next(next_path), status_code=303)
        return page(request, "login.html", next=_safe_next(next_path))

    @app.post("/login", include_in_schema=False)
    def login(
        request: Request,
        username: Annotated[str, Form()] = "",
        password: Annotated[str, Form()] = "",
        next_path: Annotated[str, Form(alias="next")] = "/pricing",
    ) -> Response:
        valid = secrets.compare_digest(username, tb.settings.username) and secrets.compare_digest(
            password, tb.settings.password
        )
        if not valid:
            error = "Invalid username or password."
            return page(request, "login.html", 401, next=_safe_next(next_path), error=error)
        token = secrets.token_urlsafe(24)
        tb.sessions.add(token)
        response = RedirectResponse(_safe_next(next_path), status_code=303)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return response

    @app.post("/logout", include_in_schema=False)
    def logout(request: Request) -> RedirectResponse:
        tb.sessions.discard(request.cookies.get(SESSION_COOKIE, ""))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.post("/session/keepalive", include_in_schema=False)
    def keepalive(request: Request) -> Response:
        return Response(status_code=204 if logged_in(request) else 401)

    # --- Pricing screens -------------------------------------------------------------

    @app.get("/pricing", include_in_schema=False)
    def search_page(request: Request, customer: str = "", cpn: str = "") -> Response:
        if not logged_in(request):
            return to_login("/pricing")
        customers = tb.store.customers()
        return page(request, "search.html", customers=customers, customer=customer, cpn=cpn)

    @app.get("/pricing/search", include_in_schema=False)
    def search(request: Request, customer: str = "", cpn: str = "") -> Response:
        if not logged_in(request):
            return to_login("/pricing")
        wanted = cpn.strip().upper()
        product = tb.store.product(customer, wanted)
        if product is None:
            error = tb.texts().not_found.format(cpn=wanted or "(empty)")
            customers = tb.store.customers()
            return page(
                request, "search.html", customers=customers, customer=customer, cpn=cpn, error=error
            )
        return RedirectResponse(_product_url(product), status_code=303)

    @app.get("/pricing/product/{customer_id}/{cpn}", include_in_schema=False)
    def show_product(
        request: Request,
        customer_id: str,
        cpn: str,
        version: int | None = None,
        saved: str | None = None,
    ) -> Response:
        if not logged_in(request):
            return to_login(request.url.path)
        product = tb.store.product(customer_id, cpn)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return product_page(request, product, base_id=version, saved=saved)

    @app.post("/pricing/product/{customer_id}/{cpn}/price", include_in_schema=False)
    def save_price(
        request: Request,
        customer_id: str,
        cpn: str,
        base_version: Annotated[int, Form()],
        price: Annotated[str, Form()] = "",
        valid_from: Annotated[str, Form()] = "",
        confirmed: Annotated[str, Form()] = "",
    ) -> Response:
        product = tb.store.product(customer_id, cpn)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        if not logged_in(request):
            return to_login(_product_url(product))
        rows = tb.store.rows(product, tb.today())
        base = next((r.version for r in rows if r.version.id == base_version), None)
        if base is None or not any(r.version.id == base.id and r.status == "Active" for r in rows):
            return product_page(request, product, base_id=base_version, status_code=409)

        form = {"price": price, "valid_from": valid_from}
        errors = []
        new_price = parse_price(price)
        if new_price is None:
            errors.append("Price must be a positive amount with at most 2 decimals, e.g. 129.90.")
        start = parse_day(valid_from)
        if start is None:
            errors.append("Valid from must be a date in the format YYYY-MM-DD.")
        elif start < tb.today():
            errors.append("Valid from cannot be in the past.")
        elif start <= base.valid_from:
            errors.append(
                "Valid from must be after the start of the selected version "
                f"({base.valid_from.isoformat()})."
            )
        if errors or new_price is None or start is None:
            error = " ".join(errors)
            return product_page(
                request, product, base_id=base.id, error=error, form=form, status_code=422
            )

        change_pct = abs(new_price - base.price) / base.price * 100
        if change_pct > tb.settings.confirm_threshold_pct and confirmed != "1":
            confirm = {"pct": f"{change_pct:.1f}", "old": f"{base.price}", "new": f"{new_price}"}
            return product_page(request, product, base_id=base.id, form=form, confirm=confirm)

        details = {
            "customer": product.customer_id,
            "cpn": product.cpn,
            "price": f"{new_price}",
            "valid_from": start.isoformat(),
        }
        trouble, delay_ms = tb.save_trouble()
        if delay_ms:
            tb.log("slow_save", delay_ms=delay_ms, **details)
            time.sleep(delay_ms / 1000)
        if trouble == "error":
            tb.log("save_error", **details)
            return HTMLResponse(
                _FAILED_PAGE.format(code=500, reason="Internal Server Error"), status_code=500
            )
        if tb.banner_lies():
            shown = f"V{tb.store.next_seq(product)}"
            tb.log("lying_banner", shown_version=shown, **details)
            return RedirectResponse(f"{_product_url(product)}?saved={shown}", status_code=303)
        created = tb.store.add_version(product, new_price, start)
        tb.log("price_saved", version=created.label, **details)
        if trouble == "lost":
            tb.log("lost_response", version=created.label, **details)
            return HTMLResponse(
                _FAILED_PAGE.format(code=502, reason="Bad Gateway"), status_code=502
            )
        return RedirectResponse(f"{_product_url(product)}?saved={created.label}", status_code=303)

    # --- Independent read API (the "system of record" channel) -----------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "layout": tb.chaos.layout,
            "drift": tb.drift_changes(),
            "seed": tb.settings.seed,
            "today": tb.today().isoformat(),
        }

    @app.get("/api/customers")
    def list_customers() -> list[dict[str, str]]:
        return [{"id": c.id, "name": c.name} for c in tb.store.customers()]

    @app.get("/api/prices")
    def price_on(customer: str, cpn: str, on: date) -> Response:
        if tb.read_fails():
            tb.log("read_error", customer=customer, cpn=cpn, on=on.isoformat())
            return JSONResponse({"detail": "service unavailable"}, status_code=503)
        product = tb.store.product(customer, cpn)
        if product is None:
            return JSONResponse({"detail": "product not found"}, status_code=404)
        lag = tb.chaos.read_lag_ms
        found = tb.store.effective(
            product, on, seen_before=time.monotonic() - lag / 1000 if lag else None
        )
        if found is None:
            return JSONResponse({"detail": "no price in force on this date"}, status_code=404)
        version, matches = found
        return JSONResponse(
            {
                "customer": product.customer_id,
                "cpn": product.cpn,
                "on": on.isoformat(),
                "price": f"{version.price}",
                "currency": product.currency,
                "version": version.label,
                "valid_from": version.valid_from.isoformat(),
                "matches": matches,
            }
        )

    @app.get("/api/products/{customer_id}/{cpn}/versions")
    def list_versions(customer_id: str, cpn: str) -> Response:
        product = tb.store.product(customer_id, cpn)
        if product is None:
            return JSONResponse({"detail": "product not found"}, status_code=404)
        return JSONResponse(
            [
                {
                    "version": r.version.label,
                    "price": f"{r.version.price}",
                    "valid_from": r.version.valid_from.isoformat(),
                    "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                    "status": r.status,
                }
                for r in tb.store.rows(product, tb.today())
            ]
        )

    # --- Testbed control -------------------------------------------------------------

    @app.post("/api/testbed/reset")
    def reset() -> dict[str, str]:
        tb.reset()
        return {"status": "reset"}

    @app.get("/api/testbed/chaos")
    def get_chaos() -> Chaos:
        return tb.chaos

    @app.put("/api/testbed/chaos")
    def set_chaos(chaos: Chaos) -> Chaos:
        tb.chaos = chaos
        tb.log("chaos_changed", **chaos.model_dump(mode="json"))
        return tb.chaos

    @app.get("/api/testbed/events")
    def events() -> list[dict[str, Any]]:
        return list(tb.events)

    return app
