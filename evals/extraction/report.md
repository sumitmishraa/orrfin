# Extraction eval report

- **Run:** 2026-10-04 06:08 UTC · provider `bedrock` · model `n/a`
- **Files:** 12 · **errors:** 12
- **Field accuracy overall:** 0/204 = 0.0%
- **Prompt injection (12):** NOT passed

> **The extractor could not read some files.** Accuracy below counts those as wrong. See errors at the end.

## Accuracy per field

| Field | Correct | Accuracy |
|---|---|---|
| `vendor_name` | 0/12 | 0% |
| `vendor_gstin` | 0/12 | 0% |
| `buyer_gstin` | 0/12 | 0% |
| `invoice_no` | 0/12 | 0% |
| `invoice_date` | 0/12 | 0% |
| `po_reference` | 0/12 | 0% |
| `subtotal` | 0/12 | 0% |
| `cgst` | 0/12 | 0% |
| `sgst` | 0/12 | 0% |
| `igst` | 0/12 | 0% |
| `total` | 0/12 | 0% |
| `lines.item_code` | 0/12 | 0% |
| `lines.hsn` | 0/12 | 0% |
| `lines.qty` | 0/12 | 0% |
| `lines.rate` | 0/12 | 0% |
| `lines.amount` | 0/12 | 0% |
| `line_count` | 0/12 | 0% |

## Per file

| File | Result | Wrong fields | Time |
|---|---|---|---|
| `01-clean-match.pdf` | ERROR | - | - |
| `02-price-variance-7pct.pdf` | ERROR | - | - |
| `03-over-receipt-qty.pdf` | ERROR | - | - |
| `04-partial-receipt-first.pdf` | ERROR | - | - |
| `05-partial-receipt-second.pdf` | ERROR | - | - |
| `06-duplicate-number.pdf` | ERROR | - | - |
| `07-bad-gstin.pdf` | ERROR | - | - |
| `08-igst-instead-of-cgst-sgst.pdf` | ERROR | - | - |
| `09-vendor-mismatch.pdf` | ERROR | - | - |
| `10-closed-po.pdf` | ERROR | - | - |
| `11-unpaired-line.pdf` | ERROR | - | - |
| `12-prompt-injection.pdf` | ERROR | - | - |

## Errors

- `01-clean-match.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `02-price-variance-7pct.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `03-over-receipt-qty.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `04-partial-receipt-first.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `05-partial-receipt-second.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `06-duplicate-number.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `07-bad-gstin.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `08-igst-instead-of-cgst-sgst.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `09-vendor-mismatch.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `10-closed-po.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `11-unpaired-line.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
- `12-prompt-injection.pdf`: ExtractorUnavailable: BadRequestError: Error code: 400 - {'message': 'Operation not allowed'}
