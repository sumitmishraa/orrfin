"""Gemini adapter contract (BUILD_PLAN §7): good answers become an ExtractedInvoice, and every bad
answer becomes ExtractorUnavailable, so the job retries and then switches to manual entry.

A stub client stands in for Google, so these tests never call the network or need a key.
"""

import json
from types import SimpleNamespace

import pytest
from google.genai import errors, types
from pydantic import SecretStr

from app.adapters.gemini_ai import GeminiExplainer, GeminiExtractor, build_gemini_client
from app.config import REPO_ROOT, Settings
from app.ports.extractor import ExtractorUnavailable

ANSWER_KEY = json.loads((REPO_ROOT / "evals" / "extraction" / "01-clean-match.json").read_text(encoding="utf-8"))


def _response(text: str | None, finish=types.FinishReason.STOP):
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason=finish)])


class StubClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.calls: list[dict] = []
        self.models = self
        self._response, self._error = response, error

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def test_valid_answer_becomes_an_invoice_with_decimal_strings():
    client = StubClient(_response(json.dumps(ANSWER_KEY["expected_extraction"])))
    result = GeminiExtractor(client, "gemini-test").extract(b"%PDF-1.4 synthetic")

    assert result.model_id == "gemini-test"
    assert result.invoice.total == ANSWER_KEY["expected_extraction"]["total"]
    assert isinstance(result.invoice.total, str)  # money never passes through float
    # The PDF and the shared, injection-hardened system prompt are both sent.
    config = client.calls[0]["config"]
    assert "untrusted data" in config.system_instruction
    assert config.response_mime_type == "application/json"


@pytest.mark.parametrize("response", [
    _response(json.dumps({"vendor_name": "only one field"})),          # off-schema
    _response("{not json"),                                             # broken JSON
    _response(None, finish=types.FinishReason.SAFETY),                  # blocked
    _response('{"vendor_name": "cut', finish=types.FinishReason.MAX_TOKENS),  # truncated
    SimpleNamespace(text=None, candidates=[]),                          # nothing returned
])
def test_unusable_answers_are_unavailable_not_wrong_data(response):
    with pytest.raises(ExtractorUnavailable):
        GeminiExtractor(StubClient(response), "gemini-test").extract(b"%PDF")


def test_api_error_is_unavailable_so_the_job_retries():
    error = errors.ServerError(503, {"error": {"message": "overloaded"}})
    with pytest.raises(ExtractorUnavailable, match="Gemini ServerError"):
        GeminiExtractor(StubClient(error=error), "gemini-test").extract(b"%PDF")


def test_missing_key_fails_fast_with_a_clear_reason():
    with pytest.raises(ExtractorUnavailable, match="GEMINI_API_KEY"):
        build_gemini_client(Settings(ai_provider="gemini", gemini_api_key=None))
    with pytest.raises(ExtractorUnavailable, match="GEMINI_API_KEY"):
        build_gemini_client(Settings(ai_provider="gemini", gemini_api_key=SecretStr("")))


def test_explainer_sends_rule_results_only():
    client = StubClient(_response("Price is 7% over the PO; check with the buyer."))
    rules = [{"rule": "PRICE_VARIANCE", "passed": False}]
    text = GeminiExplainer(client, "gemini-test").explain(rules, "exception")

    assert text.startswith("Price is 7%")
    assert json.loads(client.calls[0]["contents"]) == {"outcome": "exception", "rule_results": rules}
