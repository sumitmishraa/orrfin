"""FakeExtractor: answers from the Step 6 answer keys instead of a model (PROMPTS Step 7 "FakeExtractor").

Used in tests, and locally while Bedrock access is pending (set AI_PROVIDER=fake). It recognises
a PDF by its SHA-256, so it only "reads" the evaluation PDFs; any other file is reported as
unavailable and goes to manual entry after the retries, exactly like an AI outage. Every
extraction it makes is stored with model_id "fake-answer-key", so it is never mistaken for AI.
"""

import hashlib
import json
from pathlib import Path

from app.ports.extractor import ExtractedInvoice, ExtractionResult, ExtractorUnavailable, FieldEvidence

FAKE_MODEL_ID = "fake-answer-key"
_HEADER_FIELDS = ("vendor_name", "vendor_gstin", "buyer_gstin", "invoice_no", "invoice_date",
                  "po_reference", "subtotal", "cgst", "sgst", "igst", "total")


def _key_from_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("expected_extraction", data)  # Step 6 keys nest it; the Step 2 key is flat


class FakeExtractor:
    def __init__(self, answer_dirs: list[Path]):
        self._by_sha: dict[str, dict] = {}
        for folder in answer_dirs:
            for pdf in folder.glob("*.pdf"):
                key = next((p for p in (pdf.with_suffix(".json"), pdf.with_suffix(".expected.json")) if p.exists()), None)
                if key:
                    self._by_sha[hashlib.sha256(pdf.read_bytes()).hexdigest()] = _key_from_file(key)

    def extract(self, pdf: bytes) -> ExtractionResult:
        key = self._by_sha.get(hashlib.sha256(pdf).hexdigest())
        if key is None:
            raise ExtractorUnavailable(
                "The simulated extractor only knows the evaluation PDFs; enter this invoice by hand "
                "or enable a real AI provider (docs/spikes.md).")
        lines = [{k: line.get(k) for k in ("description", "item_code", "hsn", "qty", "rate", "amount")}
                 for line in key["lines"]]
        evidence = [FieldEvidence(field=f, quote=str(key[f]), page=1) for f in _HEADER_FIELDS if key.get(f)]
        invoice = ExtractedInvoice(
            **{f: key.get(f) for f in _HEADER_FIELDS if f in key},
            place_of_supply=key.get("place_of_supply"), currency=key.get("currency", "INR"),
            lines=lines, evidence=evidence, confidence="high",
        )
        return ExtractionResult(invoice=invoice, model_id=FAKE_MODEL_ID, prompt_version="answer-key",
                                raw_output=invoice.model_dump())
