# Spikes

Short experiments that settle a technical question before we build on it. Each entry records what we tried, what we found, and what still needs doing.

## Spike 1: Claude on Bedrock from Mumbai (Step 2, 29 Sep)

**Question:** Can the laptop user `orrfin-dev-laptop` send an invoice PDF to Claude on Amazon Bedrock from ap-south-1 and get correct fields back? Which model ID should we use, and where does the inference actually run?

**Status:** code ready, **blocked on AWS console setup** (see "What the founder must do" below).

### Findings so far
| Item | Result |
|---|---|
| AWS credentials | `default` CLI profile → IAM user `orrfin-dev-laptop`, region `ap-south-1`. Works (STS and Bedrock list calls succeed). |
| Models visible from Mumbai | Current Claude models (Sonnet 5 / 5.5, Opus 5 / 5.5, Haiku 4.5, Fable 5 / 5.1) are offered **only as `global.` cross-region inference profiles**. The `apac.` profiles stop at Claude Sonnet 4. |
| Chosen model ID | **`global.anthropic.claude-sonnet-5-5`** (the model the founder picked in the console). Override with `--model` or `BEDROCK_MODEL_ID`. |
| Current blocker | Every call returns `400 Operation not allowed`. `--check-access` shows: **Anthropic use-case form not submitted**; model agreement `NOT_AVAILABLE`, authorization `NOT_AUTHORIZED`. This is an account-level gate, not an IAM permission problem. |
| Routed region | Not measured yet (needs a successful call). With a `global.` profile, the call may run in **any AWS commercial region, including outside India**. It must be disclosed on the Trust page (BUILD_PLAN §3). |
| Extraction result | Not measured yet. |

### What the founder must do (AWS console, about 10 minutes)
Sign in as **`orrfin-admin`**, not as the laptop user. The first model call also creates an AWS Marketplace subscription, and the laptop user has only Bedrock permissions.

```
Sign in (orrfin-admin) → region: Asia Pacific (Mumbai)
   → Amazon Bedrock → Model catalog → filter "Anthropic" → Claude Sonnet 5.5
   → "Submit use case details" form → Submit
   → wait ~1–15 min → "Open in playground" → attach the invoice PDF → Run
   → it answers? → tell Claude Code "Bedrock is enabled"
```

1. Go to https://console.aws.amazon.com and sign in as `orrfin-admin`.
2. In the region menu at the top right, choose **Asia Pacific (Mumbai) ap-south-1**.
3. In the search bar, type **Bedrock** and open **Amazon Bedrock**.
4. In the left menu, click **Model catalog**. Under **Providers**, tick **Anthropic**.
5. Click **Claude Sonnet 5.5**. If a banner says **"Submit use case details"** (or "Anthropic requires use case details"), click it.
6. Fill in the form. These answers are true for Orrfin:
   - Company name: *Orrfin*; website: *https://orrfin.ai*; industry: *Financial services / software*.
   - Intended users: *Internal employees* (a demo for our own team and investors).
   - Use case: *"Extract fields (vendor, GSTIN, invoice number, dates, line items, taxes, totals) from synthetic Indian GST invoice PDFs for an accounts-payable matching prototype. No real customer data."*
   - Click **Submit**. Approval is usually instant and can take up to 15 minutes.
7. Back on the model page, click **Open in playground** (or left menu **Playgrounds → Chat**). Pick **Anthropic → Claude Sonnet 5.5**, attach `seed/invoices/INV-SAMPLE-001.pdf`, type *"Extract the invoice number and total"* and press **Run**. An answer means access now works for the whole account, including the laptop user.

**If something goes wrong:**
- *The form won't submit, or you see "account verification" / "not yet activated":* finish the **"Verify your identity"** email from AWS and check that **Billing → Payment methods** has a valid card. Then reload and submit again.
- *The playground says "You don't have access":* wait 15 minutes after submitting the form and try again.
- *An error mentions `aws-marketplace`:* you are signed in as the laptop user. Sign in as `orrfin-admin`.

### Then run the spike (Claude Code will do this)
```powershell
backend\.venv\Scripts\python backend\scripts\bedrock_spike.py --check-access   # expect authorization=AUTHORIZED
backend\.venv\Scripts\python backend\scripts\bedrock_spike.py                  # prints JSON; "MATCHES ground truth"
backend\.venv\Scripts\python backend\scripts\bedrock_spike.py --routing-only   # routed region, 5-15 min later
```
The laptop user cannot read CloudTrail, so if `--routing-only` says "not readable", look it up in the console instead: **CloudTrail → Event history** → filter *Event source* = `bedrock.amazonaws.com` → open the latest `InvokeModel` event → find `additionalEventData.inferenceRegion`. Record it in the table above.

### Files
- `backend/scripts/make_sample_invoice.py` writes `seed/invoices/INV-SAMPLE-001.pdf` and `.expected.json`: fake Mumbai vendor, format-valid GSTINs with correct check characters, 3 lines, CGST 9% + SGST 9%, total ₹31,942.60.
- `backend/scripts/bedrock_spike.py`: `AnthropicBedrock` client with the CLI profile, a PDF document block, and structured output into a Pydantic schema. Money is returned as strings and compared as `Decimal`. Prompt version `spike-v1`.
