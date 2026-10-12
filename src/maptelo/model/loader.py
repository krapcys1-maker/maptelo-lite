"""Loading process models from YAML and exporting the JSON Schema."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from maptelo.model.schema import FORMAT_VERSION, ProcessModel

SCHEMA_ID = f"urn:maptelo:process-model:{FORMAT_VERSION}"
# Pydantic adds union-member tags to error locations; they mean nothing to a model author.
_INTERNAL_LOC = re.compile(
    r"^(function-\w+\[.*|union\[.*|list\[.*|dict\[.*|str|bool|int|float|date)$"
)


class ModelLoadError(Exception):
    def __init__(self, source: str, problems: list[str]) -> None:
        super().__init__(f"{source}: " + "; ".join(problems))
        self.source = source
        self.problems = problems


def _yaml() -> YAML:
    # YAML 1.2: 'on', 'yes', 'no' stay strings, duplicate keys are rejected.
    return YAML(typ="safe", pure=True)


def parse_model(text: str, source: str = "<text>") -> ProcessModel:
    try:
        data = _yaml().load(text)
    except YAMLError as exc:
        raise ModelLoadError(source, [f"invalid YAML: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ModelLoadError(source, ["the file must contain a mapping at the top level"])
    try:
        return ProcessModel.model_validate(data)
    except ValidationError as exc:
        raise ModelLoadError(source, format_validation_error(exc)) from exc


def load_model(path: Path) -> ProcessModel:
    return parse_model(path.read_text(encoding="utf-8"), str(path))


def format_validation_error(error: ValidationError) -> list[str]:
    problems = []
    for item in error.errors(include_url=False):
        location = _format_location(item["loc"])
        message = str(item["msg"]).removeprefix("Value error, ")
        problems.append(f"{location}: {message}" if location else message)
    return problems


def _format_location(loc: tuple[int | str, ...]) -> str:
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        elif not _INTERNAL_LOC.match(part):
            text += f".{part}" if text else part
    return text


_RISKY = re.compile(r"^[\s:?!&*|>%@`#,\[\]{}'\"-]|: | #|:$")
"""A plain value YAML may read as something else: an indicator first, a colon followed by a
space or ending it, a comment sign inside."""


def dump_model(model: ProcessModel, header: str | None = None) -> str:
    """YAML text of a model: defaults left out, small mappings kept on one line. The text is
    read back before it is returned: a value the writer left plain where the reader takes it
    for syntax (":30" in a one-line mapping) is quoted, and a text that still reads otherwise
    is never returned."""
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
    text = _dump(data)
    if not _reads_back(text, data):
        text = _dump(_quote_risky(data))
        if not _reads_back(text, data):
            raise ValueError("the model's YAML does not read back as written")
    prefix = "".join(f"# {line}\n" for line in header.splitlines()) if header else ""
    return prefix + text


def _dump(data: Any) -> str:
    yaml = YAML(typ="rt")
    yaml.default_flow_style = None
    yaml.width = 110
    yaml.indent(mapping=2, sequence=4, offset=2)
    stream = io.StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def _reads_back(text: str, data: Any) -> bool:
    try:
        return bool(_yaml().load(text) == data)
    except YAMLError:
        return False


def _quote_risky(data: Any) -> Any:
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString

    if isinstance(data, dict):
        return {key: _quote_risky(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_quote_risky(value) for value in data]
    if isinstance(data, str) and _RISKY.search(data):
        return DoubleQuotedScalarString(data)
    return data


def json_schema() -> dict[str, Any]:
    schema = ProcessModel.model_json_schema(by_alias=True)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
    }
