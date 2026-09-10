---
description: Read a broker/analyst PDF with Gemini vision and return clean Markdown (pass the PDF path as $1). Use to read any PDF report (Schwab, CFRA, LSEG, broker) so tables and figures are preserved.
---

Convert the analyst-report PDF at `$1` into clean Markdown so its tables and figures are fully readable.

1. Run `python -m finance.pdf2md "$1"` (optionally pass a Gemini model id as `$2`).
   - If `GEMINI_API_KEY` is not set, the tool exits with instructions. Tell the
     user to create a free key (no credit card) at https://aistudio.google.com/apikey,
     run `setx GEMINI_API_KEY <key>`, restart the terminal, then rerun.
2. Read the generated Markdown file the tool prints (written next to the input,
   e.g. `mu3_pdf2md.md`) in full.
3. Analyze the report into the conversation: rating agency and rating, price
   target, key metrics (P/E, EPS, revisions, targets), risks, and a clear verdict.
   Preserve every `[could not read]` marker verbatim; never guess a figure the
   tool could not read.