"""Gemini adapters: invoice extraction and match explanations (BUILD_PLAN §3 AI row, §6 explanation, §7).

The stand-in provider while Bedrock access is pending (docs/adr/0005). It uses the same prompts
(`ai_prompts.py`) and the same output schema (`ExtractedInvoice`) as Claude, so the rest of the
app cannot tell which model read the invoice, except through the stored `model_id`.

The answer is validated with Pydantic here instead of trusting the SDK's parsing: money stays
a decimal string, and anything off-schema becomes ExtractorUnavailable (retried, then manual entry).
"""

import json
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.adapters.ai_prompts import (
    EXPLAIN_PROMPT_VERSION,
    EXPLAIN_SYSTEM,
    EXTRACT_PROMPT_VERSION,
    EXTRACT_SYSTEM,
    EXTRACT_USER,
)
from app.config import Settings
from app.ports.extractor import ExtractedInvoice, ExtractionResult, ExtractorUnavailable


def build_gemini_client(settings: Settings) -> tuple[Any, str]:
    """Return (client, model_id). Fails fast without a key so the job records a clear reason."""
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        raise ExtractorUnavailable("GEMINI_API_KEY is not set in .env")
    # One attempt per call, 120 s cap: the job queue owns retries and backoff (ADR 0003).
    http_options = types.HttpOptions(timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1))
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value(), http_options=http_options)
    return client, settings.gemini_model


def _finished_normally(response: Any) -> bool:
    candidates = response.candidates or []
    return bool(candidates) and candidates[0].finish_reason == types.FinishReason.STOP


class GeminiExtractor:
    def __init__(self, client: Any, model_id: str):
        self.client = client
        self.model_id = model_id

    def extract(self, pdf: bytes, mime_type: str = "application/pdf") -> ExtractionResult:
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[types.Part.from_bytes(data=pdf, mime_type=mime_type), EXTRACT_USER],
                config=types.GenerateContentConfig(
                    system_instruction=EXTRACT_SYSTEM,
                    response_mime_type="application/json",
                    response_json_schema=ExtractedInvoice.model_json_schema(),
                    max_output_tokens=16000,
                ),
            )
        except errors.APIError as exc:  # outage, quota, bad key: retried by the job
            raise ExtractorUnavailable(f"Gemini {type(exc).__name__}: {exc}") from exc
        # A cut-off or safety-blocked answer is not a reading; treat it like an outage.
        if not _finished_normally(response) or not response.text:
            reason = response.candidates[0].finish_reason if response.candidates else "no candidates"
            raise ExtractorUnavailable(f"No usable output (finish_reason={reason})")
        try:
            invoice = ExtractedInvoice.model_validate_json(response.text)
        except ValidationError as exc:
            raise ExtractorUnavailable(f"Output did not match the invoice schema: {exc.error_count()} errors") from exc
        return ExtractionResult(
            invoice=invoice,
            model_id=self.model_id,
            prompt_version=EXTRACT_PROMPT_VERSION,
            raw_output=invoice.model_dump(),
        )


class GeminiExplainer:
    def __init__(self, client: Any, model_id: str):
        self.client = client
        self.model_id = model_id

    @property
    def source(self) -> str:
        return f"{self.model_id} ({EXPLAIN_PROMPT_VERSION})"

    def explain(self, rule_results: list[dict[str, Any]], outcome: str) -> str:
        # Only the rule results are sent: never the document text (§6).
        payload = json.dumps({"outcome": outcome, "rule_results": rule_results}, ensure_ascii=False)
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=payload,
            config=types.GenerateContentConfig(system_instruction=EXPLAIN_SYSTEM, max_output_tokens=2000),
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Empty explanation")
        return text
