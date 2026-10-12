"""IT's policy for this computer: what Maptelo may do here, set by the company and not by
the person at the keyboard (docs/08-srodowiska.md).

    %ProgramData%\\Maptelo\\policy.yaml       for the whole computer, put there by IT
    policy.yaml next to a portable copy       (the folder with python.exe, or the one above)
    MAPTELO_POLICY=<path>                     another place (tests, pilots)
    (and the first and last under the old name, Stepproof: formerly.py)

    ai:
      allowed: false                # no calls to AI models at all
      endpoint: https://ai.firma.pl/v1   # or: only this one; with the lines below it is the
      api: openai                   #   company's own AI (--agent company): its protocol,
      key_env: FIRMA_AI_KEY         #   the variable holding its key,
      key_header: api-key           #   the header the key goes in (default: Bearer),
      model: gpt-4.1                #   the model it offers
    applications:
      allowed_hosts: [erp.firma.local, "*.firma.pl", login.microsoftonline.com]
    browser:
      channel: msedge               # the company's browser, whatever a person picks
      company_certificates: true    # trust the company's own certificates (or false: never)
    evidence:
      keep_days: 90                 # screenshots of runs (they may show personal data)

A policy that is there but cannot be read stops Maptelo from doing anything (no run, no
AI) until it is fixed: what is not known to be allowed is not done.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from maptelo import formerly
from maptelo.checks import Lang, say

POLICY_ENV = "MAPTELO_POLICY"


class PolicyError(Exception):
    """IT's policy is there but cannot be read: nothing is done until it is fixed."""


class _Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AiRules(_Rules):
    allowed: bool = True
    endpoint: str | None = Field(default=None, pattern=r"^https?://")
    """When set, AI repairs may only call this address (the company's own gateway)."""
    api: Literal["openai", "anthropic"] = "openai"
    """The protocol the company's AI speaks: chat completions (OpenAI, Azure, most gateways)
    or Anthropic's messages."""
    key_env: str | None = None
    """The environment variable (or .env entry) holding the company's key."""
    key_header: str | None = None
    """The header the key goes in, when not ``Authorization: Bearer`` (``api-key``: Azure)."""
    model: str | None = None
    """The model the company's AI offers, used when no model is given."""


class ApplicationRules(_Rules):
    allowed_hosts: list[str] = Field(default_factory=list)
    """Host names the robot may open (``*.firma.pl`` for every host under it); none: any."""


class BrowserRules(_Rules):
    channel: Literal["chromium", "msedge", "chrome"] | None = None
    company_certificates: bool | None = None
    """The company's own certificates (an internal certificate authority its computers trust):
    true accepts them in every run, false never (not even when a run asks); none: a run may
    ask (maptelo run --company-certificates)."""


class EvidenceRules(_Rules):
    keep_days: int | None = Field(default=None, ge=1, le=3650)
    """Screenshots of runs may show personal data: kept only this many days (none: no limit)."""


class PolicyRules(_Rules):
    ai: AiRules = Field(default_factory=AiRules)
    applications: ApplicationRules = Field(default_factory=ApplicationRules)
    browser: BrowserRules = Field(default_factory=BrowserRules)
    evidence: EvidenceRules = Field(default_factory=EvidenceRules)


@dataclass(frozen=True)
class Policy:
    source: Path | None = None
    """None: no policy, the defaults apply."""
    rules: PolicyRules = field(default_factory=PolicyRules)

    def host_allowed(self, url: str) -> bool:
        """Whether the robot may be at this address. Pages without a host (about:blank, a
        data: page) are always allowed: they are not an application."""
        patterns = self.rules.applications.allowed_hosts
        host = (urlsplit(url).hostname or "").lower()
        if not patterns or not host:
            return True
        return any(_host_matches(host, pattern.lower()) for pattern in patterns)

    def ai_refusal(self, base_url: str) -> str | None:
        """Why AI may not be asked at this address, or None when it may."""
        if not self.rules.ai.allowed:
            return f"AI is turned off by IT's policy ({self.source})"
        endpoint = self.rules.ai.endpoint
        if endpoint and not _endpoint_matches(base_url, endpoint):
            return f"IT's policy allows AI only at {endpoint} ({self.source})"
        return None

    @property
    def channel(self) -> str | None:
        """The browser the policy names (None for Playwright's Chromium or no rule)."""
        chosen = self.rules.browser.channel
        return None if chosen in (None, "chromium") else chosen

    def describe(self, lang: Lang = "en") -> str:
        """What the policy decides, in one line."""
        rules = self.rules
        parts = []
        if not rules.ai.allowed:
            parts.append(say(lang, "AI off", "AI wyłączone"))
        elif rules.ai.endpoint:
            parts.append(
                say(lang, f"AI only at {rules.ai.endpoint}", f"AI tylko pod {rules.ai.endpoint}")
            )
        if rules.applications.allowed_hosts:
            hosts = ", ".join(rules.applications.allowed_hosts)
            parts.append(say(lang, f"the robot opens only {hosts}", f"robot otwiera tylko {hosts}"))
        if rules.browser.channel:
            parts.append(
                say(
                    lang,
                    f"browser: {rules.browser.channel}",
                    f"przeglądarka: {rules.browser.channel}",
                )
            )
        if rules.browser.company_certificates is not None:
            trusted = rules.browser.company_certificates
            parts.append(
                say(
                    lang,
                    "the company's certificates " + ("trusted" if trusted else "never trusted"),
                    "certyfikaty firmy " + ("zaufane" if trusted else "nigdy zaufane"),
                )
            )
        if rules.evidence.keep_days:
            days = rules.evidence.keep_days
            parts.append(say(lang, f"screenshots kept {days} days", f"zrzuty trzymane {days} dni"))
        return "; ".join(parts) or say(lang, "nothing restricted", "bez ograniczeń")


def _endpoint_matches(url: str, endpoint: str) -> bool:
    """An exact origin and a path boundary, never a textual hostname prefix."""
    try:
        candidate, allowed = urlsplit(url), urlsplit(endpoint)

        def origin(part: object) -> tuple[str, str | None, int | None]:
            parsed = urlsplit(str(part))
            return (
                parsed.scheme,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )

        if candidate.username or candidate.password or candidate.query or candidate.fragment:
            return False
        if origin(url) != origin(endpoint):
            return False
        path, prefix = candidate.path.rstrip("/"), allowed.path.rstrip("/")
        if any(piece in (".", "..") for piece in path.split("/")) or "%" in path:
            return False
        return path == prefix or path.startswith(prefix + "/")
    except ValueError:
        return False


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) or host == pattern[2:]
    return fnmatch.fnmatchcase(host, pattern)


def policy_path(
    environ: Mapping[str, str] | None = None, exists: Callable[[Path], bool] = Path.is_file
) -> Path | None:
    """Where IT's policy is, or None when there is none."""
    env = os.environ if environ is None else environ
    given = env.get(POLICY_ENV) or env.get(formerly.POLICY_ENV)
    if given:
        return Path(given)  # named on purpose: missing is an error, not "no policy"
    data = env.get("ProgramData") or env.get("PROGRAMDATA")
    candidates = (
        [Path(data) / folder / "policy.yaml" for folder in ("Maptelo", formerly.POLICY_FOLDER)]
        if data
        else []
    )
    portable = Path(sys.executable).resolve().parent
    candidates += [portable / "policy.yaml", portable.parent / "policy.yaml"]
    return next((path for path in candidates if exists(path)), None)


def load_policy(path: Path) -> Policy:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"IT's policy {path} cannot be read: {exc.strerror or exc}") from exc
    try:
        data = YAML(typ="safe", pure=True).load(text) or {}
        rules = PolicyRules.model_validate(data)
    except (YAMLError, ValidationError) as exc:
        problem = str(exc).splitlines()[0] if isinstance(exc, YAMLError) else _first(exc)
        raise PolicyError(f"IT's policy {path} is not valid: {problem}") from exc
    return Policy(path, rules)


def _first(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"]) or "the file"
    return f"{where}: {error['msg']}"


def current(environ: Mapping[str, str] | None = None) -> Policy:
    """The policy in force here (raises PolicyError when it is there but unreadable)."""
    path = policy_path(environ)
    return load_policy(path) if path is not None else Policy()
