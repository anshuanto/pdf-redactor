# PDF Redactor

A small desktop app that permanently redacts PDFs on your own computer. No online service, no uploads.

Draw boxes over what you want hidden, then redact one PDF or a whole batch of PDFs that share the same layout.

## Setup

```bash
pip3 install -r requirements.txt
python3 redactor.py
```

Requires Python 3 with Tkinter (included with the python.org installer).

## How to use

1. **Open PDF** and drag boxes over the text you want hidden.
   Right-click (or Ctrl-click) a box to remove it. Undo with ⌘Z.
2. Use ◀ ▶ or the arrow keys to move between pages. Each page has its own boxes.
   Tick **Same boxes on every page** to reuse one set on all pages.
3. **Redact this PDF** redacts the open file. **Batch redact…** applies the same boxes to many similar PDFs.
4. **Save template** and **Load template** store box positions as JSON for reuse.

## Output

Redacted copies go into a `Redacted` folder inside the input folder, named `<original>_redacted.pdf`.
Originals are never modified and nothing is overwritten (`_redacted_2`, `_redacted_3`, …).
Loose `_redacted` files in the input folder are moved into `Redacted` automatically.

Redaction is real: the text and image pixels under each box are removed from the file, not just covered.
File metadata (author, title, etc.) is cleared too.

Batch mode uses the same box positions on every file, so spot-check a few outputs if layouts may differ slightly.

## Sample PDFs

`Sample PDFs/` holds 10 fake bank statements with made-up data for testing.
