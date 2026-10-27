"""A private process keeps its values in the company: the documents made of it for people to
read and share (SOP, report, diagrams, BPMN, AI brief) show no value typed or chosen in its
recordings, its pictures are only the covered ones, an address keeps no sign-in, and a
process recorded privately is recorded privately again."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from maptelo.export import write_map_bundle
from maptelo.mapping import map_trace
from maptelo.privacy import recorded_values, redact
from maptelo.studio import Workspace
from maptelo.studio.recording import RecordRequest, is_private, record_work
from maptelo.trace import load_trace
from maptelo.trace.io import hide_credentials

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recordings" / "update_customer_price"
RECORDING = FIXTURES / "02-several-versions"


def _private_copy(tmp_path: Path) -> Path:
    folder = tmp_path / "nagranie"
    shutil.copytree(RECORDING, folder)
    trace = folder / "trace.jsonl"
    lines = trace.read_text(encoding="utf-8").split("\n")
    header = json.loads(lines[0])
    header["private"] = True
    lines[0] = json.dumps(header, ensure_ascii=False)
    trace.write_text("\n".join(lines), encoding="utf-8")
    return folder


def test_shared_documents_of_a_private_process_show_no_recorded_value(tmp_path: Path) -> None:
    folder = _private_copy(tmp_path)
    trace = load_trace(folder)
    values = recorded_values([trace])
    assert values  # what the person typed: a customer, a part number, a price, a date
    result = map_trace(trace, lang="pl")
    files = write_map_bundle(result, tmp_path / "mapa", lang="pl")
    for key, path in files.items():
        if key == "model":
            continue  # the model runs the process: it stays with the company
        text = path.read_text(encoding="utf-8")
        shown = [v for v in values if v in text]
        assert shown == [], f"{path.name} shows {shown}"
    assert "[wartość]" in files["sop"].read_text(encoding="utf-8")


def test_a_value_is_covered_as_html_writes_it_too() -> None:
    assert redact("<td>Kowalski &amp; Syn</td>", ["Kowalski & Syn"]) == "<td>[wartość]</td>"
    assert redact("Customer K0010", ["K0010"], "en") == "Customer [value]"


def test_an_address_keeps_no_sign_in() -> None:
    assert (
        hide_credentials("https://app.firma.pl/cb?code=K0010&access_token=abc.def&x=1")
        == "https://app.firma.pl/cb?code=K0010&access_token=hidden&x=1"
    )
    assert hide_credentials("https://jan:tajne@app.firma.pl/") == "https://jan:hidden@app.firma.pl/"
    assert (
        hide_credentials("https://app.firma.pl/#id_token=xyz&state=1")
        == "https://app.firma.pl/#id_token=hidden&state=1"
    )
    plain = "https://app.firma.pl/orders?customer=K0010&author=Nowak"
    assert hide_credentials(plain) == plain  # a record's values are what a model is made of


def test_a_private_process_is_recorded_privately_again(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "praca")
    folder = workspace.recordings / "ceny" / "20261021-0900"
    folder.parent.mkdir(parents=True)
    shutil.copytree(_private_copy(tmp_path), folder)
    assert is_private(workspace, "ceny")
    request = RecordRequest.from_json({"process": "ceny", "url": "http://127.0.0.1:1/"})
    assert not request.private  # the form was left as it is
    work = record_work(workspace, request)
    assert work.__closure__ is not None
    kept = [c.cell_contents for c in work.__closure__ if isinstance(c.cell_contents, RecordRequest)]
    assert [r.private for r in kept] == [True]
