#!/usr/bin/env python3
"""
PDF Redactor - runs fully on your computer.

1. Open a PDF.
2. Drag boxes over anything you want hidden (right-click a box to remove it).
3. "Redact this PDF" saves a redacted copy, or
   "Batch redact..." applies the same boxes to many similar PDFs at once.

Redaction is permanent: the text/images under each box are removed from the
file, not just covered up.

Needs:  pip3 install pymupdf
Run:    python3 redactor.py
"""

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

import pymupdf

BOX_COLOR = "#e53935"
MIN_BOX = 3  # points; ignore accidental tiny clicks


OUTPUT_FOLDER = "Redacted"


def is_redacted_copy(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    in_output = os.path.basename(os.path.dirname(os.path.abspath(path))) == OUTPUT_FOLDER
    return "_redacted" in stem or in_output


def redacted_path(src):
    """<input folder>/Redacted/<name>_redacted.pdf. Never overwrites an existing file:
    adds _2, _3, ... if a redacted copy is already there."""
    folder = os.path.join(os.path.dirname(os.path.abspath(src)), OUTPUT_FOLDER)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(folder, f"{stem}_redacted.pdf")
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(folder, f"{stem}_redacted_{n}.pdf")
        n += 1
    return dst


def tidy_folder(folder):
    """Move any loose *_redacted*.pdf files in folder into its Redacted subfolder.
    Nothing is deleted or overwritten. Returns how many files were moved."""
    moved = 0
    for name in os.listdir(folder):
        src = os.path.join(folder, name)
        if (os.path.isfile(src) and name.lower().endswith(".pdf")
                and "_redacted" in os.path.splitext(name)[0]):
            out = os.path.join(folder, OUTPUT_FOLDER)
            os.makedirs(out, exist_ok=True)
            stem, ext = os.path.splitext(name)
            dst, n = os.path.join(out, name), 2
            while os.path.exists(dst):
                dst = os.path.join(out, f"{stem}_{n}{ext}")
                n += 1
            os.rename(src, dst)
            moved += 1
    return moved


class Redactor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Redactor")
        self.geometry("1000x850")

        self.doc = None
        self.path = None
        self.page_no = 0
        self.zoom = 1.5
        # boxes[page_index] = [(x0, y0, x1, y1), ...] in PDF points (as shown on screen)
        self.boxes = {}
        self.all_pages = tk.BooleanVar(value=False)
        self.drag_start = None
        self.drag_rect = None
        self.photo = None

        self._build_ui()
        self.bind("<Left>", lambda e: self.change_page(-1))
        self.bind("<Right>", lambda e: self.change_page(1))
        self.bind("<Command-z>", lambda e: self.undo())
        self.bind("<Control-z>", lambda e: self.undo())

    # ---------- UI ----------
    def _build_ui(self):
        bar = tk.Frame(self, padx=6, pady=6)
        bar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(bar, text="Open PDF", command=self.open_pdf).pack(side=tk.LEFT)
        tk.Button(bar, text="◀", width=2, command=lambda: self.change_page(-1)).pack(side=tk.LEFT, padx=(10, 0))
        self.page_label = tk.Label(bar, text="Page – / –", width=12)
        self.page_label.pack(side=tk.LEFT)
        tk.Button(bar, text="▶", width=2, command=lambda: self.change_page(1)).pack(side=tk.LEFT)
        tk.Button(bar, text="−", width=2, command=lambda: self.set_zoom(-0.25)).pack(side=tk.LEFT, padx=(10, 0))
        tk.Button(bar, text="+", width=2, command=lambda: self.set_zoom(0.25)).pack(side=tk.LEFT)

        tk.Checkbutton(bar, text="Same boxes on every page", variable=self.all_pages,
                       command=self.render).pack(side=tk.LEFT, padx=10)

        bar2 = tk.Frame(self, padx=6)
        bar2.pack(side=tk.TOP, fill=tk.X)
        tk.Button(bar2, text="Undo", command=self.undo).pack(side=tk.LEFT)
        tk.Button(bar2, text="Clear page", command=self.clear_page).pack(side=tk.LEFT)
        tk.Button(bar2, text="Save template", command=self.save_template).pack(side=tk.LEFT, padx=(10, 0))
        tk.Button(bar2, text="Load template", command=self.load_template).pack(side=tk.LEFT)
        tk.Button(bar2, text="Batch redact…", command=self.batch_redact).pack(side=tk.RIGHT)
        tk.Button(bar2, text="Redact this PDF", command=self.redact_current).pack(side=tk.RIGHT, padx=6)

        wrap = tk.Frame(self)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(wrap, bg="#555", cursor="crosshair", highlightthickness=0)
        vs = tk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.canvas.yview)
        hs = tk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        # right-click (Mac: also Ctrl-click / two-finger) removes a box
        for ev in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.canvas.bind(ev, self.on_right_click)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta), "units"))

        self.status = tk.Label(self, anchor="w", padx=6,
                               text="Open a PDF, then drag boxes over what you want hidden. Right-click a box to remove it.")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # ---------- helpers ----------
    def box_key(self):
        return "all" if self.all_pages.get() else self.page_no

    def current_boxes(self):
        return self.boxes.setdefault(self.box_key(), [])

    def to_canvas(self, x, y):
        return x * self.zoom, y * self.zoom

    def to_pdf(self, x, y):
        return self.canvas.canvasx(x) / self.zoom, self.canvas.canvasy(y) / self.zoom

    def say(self, msg):
        self.status.config(text=msg)

    # ---------- document ----------
    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        try:
            doc = pymupdf.open(path)
        except Exception as e:
            messagebox.showerror("Can't open", str(e))
            return
        if doc.needs_pass:
            messagebox.showerror("Locked PDF", "This PDF is password protected.")
            return
        if self.doc:
            self.doc.close()
        self.doc, self.path, self.page_no = doc, path, 0
        self.title(f"PDF Redactor – {os.path.basename(path)}")
        self.render()

    def change_page(self, step):
        if not self.doc:
            return
        new = self.page_no + step
        if 0 <= new < len(self.doc):
            self.page_no = new
            self.render()

    def set_zoom(self, step):
        self.zoom = min(4.0, max(0.5, self.zoom + step))
        self.render()

    def render(self):
        self.canvas.delete("all")
        if not self.doc:
            return
        page = self.doc[self.page_no]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
        self.photo = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))
        for b in self.current_boxes():
            self.draw_box(b)
        self.page_label.config(text=f"Page {self.page_no + 1} / {len(self.doc)}")
        self.say(f"{len(self.current_boxes())} box(es) "
                 f"{'on every page' if self.all_pages.get() else 'on this page'}.")

    def draw_box(self, b):
        x0, y0 = self.to_canvas(b[0], b[1])
        x1, y1 = self.to_canvas(b[2], b[3])
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=BOX_COLOR, width=2,
                                     fill=BOX_COLOR, stipple="gray25", tags="box")

    # ---------- drawing ----------
    def on_press(self, e):
        if not self.doc:
            return
        self.drag_start = (self.canvas.canvasx(e.x), self.canvas.canvasy(e.y))
        self.drag_rect = self.canvas.create_rectangle(*self.drag_start, *self.drag_start,
                                                      outline=BOX_COLOR, width=2, dash=(4, 2))

    def on_drag(self, e):
        if self.drag_rect:
            self.canvas.coords(self.drag_rect, *self.drag_start,
                               self.canvas.canvasx(e.x), self.canvas.canvasy(e.y))

    def on_release(self, e):
        if not self.drag_rect:
            return
        self.canvas.delete(self.drag_rect)
        self.drag_rect = None
        sx, sy = self.drag_start[0] / self.zoom, self.drag_start[1] / self.zoom
        ex, ey = self.to_pdf(e.x, e.y)
        box = (round(min(sx, ex), 2), round(min(sy, ey), 2), round(max(sx, ex), 2), round(max(sy, ey), 2))
        if box[2] - box[0] < MIN_BOX or box[3] - box[1] < MIN_BOX:
            return
        self.current_boxes().append(box)
        self.render()

    def on_right_click(self, e):
        if not self.doc:
            return
        x, y = self.to_pdf(e.x, e.y)
        boxes = self.current_boxes()
        for i in range(len(boxes) - 1, -1, -1):
            x0, y0, x1, y1 = boxes[i]
            if x0 <= x <= x1 and y0 <= y <= y1:
                del boxes[i]
                self.render()
                return

    def undo(self):
        if self.current_boxes():
            self.current_boxes().pop()
            self.render()

    def clear_page(self):
        self.boxes[self.box_key()] = []
        self.render()

    # ---------- templates ----------
    def save_template(self):
        if not any(self.boxes.values()):
            messagebox.showinfo("Nothing to save", "Draw some boxes first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("Redaction template", "*.json")])
        if path:
            data = {"all_pages": self.all_pages.get(),
                    "boxes": {str(k): v for k, v in self.boxes.items() if v}}
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self.say(f"Template saved: {os.path.basename(path)}")

    def load_template(self):
        path = filedialog.askopenfilename(filetypes=[("Redaction template", "*.json")])
        if not path:
            return
        with open(path) as f:
            data = json.load(f)
        self.boxes = {(k if k == "all" else int(k)): [tuple(b) for b in v]
                      for k, v in data["boxes"].items()}
        self.all_pages.set(data.get("all_pages", False))
        self.render()
        self.say(f"Template loaded: {os.path.basename(path)}")

    # ---------- redaction ----------
    def boxes_for_page(self, i):
        key = "all" if self.all_pages.get() else i
        return self.boxes.get(key, [])

    def redact_file(self, src, dst):
        """Apply the boxes to src and write dst. Returns number of boxes applied."""
        doc = pymupdf.open(src)
        count = 0
        for i, page in enumerate(doc):
            boxes = self.boxes_for_page(i)
            if not boxes:
                continue
            for b in boxes:
                # boxes are in the page as displayed; convert for rotated pages
                rect = pymupdf.Rect(b) * page.derotation_matrix
                page.add_redact_annot(rect, fill=(0, 0, 0))
                count += 1
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
        doc.set_metadata({})       # strip author/title/etc.
        doc.del_xml_metadata()
        doc.save(dst, garbage=4, deflate=True, clean=True)
        doc.close()
        return count

    def has_boxes(self):
        if not any(self.boxes_for_page(i) for i in range(len(self.doc) if self.doc else 999)):
            messagebox.showinfo("No boxes", "Draw at least one box first.")
            return False
        return True

    def redact_current(self):
        if not self.doc:
            messagebox.showinfo("No PDF", "Open a PDF first.")
            return
        if not self.has_boxes():
            return
        try:
            tidy_folder(os.path.dirname(os.path.abspath(self.path)))
        except OSError:
            pass
        dst = redacted_path(self.path)
        try:
            n = self.redact_file(self.path, dst)
        except Exception as e:
            messagebox.showerror("Redaction failed", str(e))
            return
        messagebox.showinfo("Done", f"Applied {n} redaction(s).\nSaved: {dst}")

    def batch_redact(self):
        if not self.has_boxes():
            return
        files = filedialog.askopenfilenames(title="Pick the PDFs to redact",
                                            filetypes=[("PDF files", "*.pdf")])
        if not files:
            return
        # don't re-redact copies that were already made
        skipped = [f for f in files if is_redacted_copy(f)]
        files = [f for f in files if not is_redacted_copy(f)]
        for folder in {os.path.dirname(os.path.abspath(f)) for f in files}:
            try:
                tidy_folder(folder)
            except OSError:
                pass
        done, failed = 0, []
        for i, src in enumerate(files, 1):
            self.say(f"Redacting {i}/{len(files)}: {os.path.basename(src)}")
            self.update_idletasks()
            try:
                self.redact_file(src, redacted_path(src))
                done += 1
            except Exception as e:
                failed.append(f"{os.path.basename(src)}: {e}")
        msg = (f"Redacted {done} of {len(files)} file(s).\n"
               f"Copies are in the \"{OUTPUT_FOLDER}\" folder inside the input folder.")
        if skipped:
            msg += f"\n\nSkipped {len(skipped)} file(s) that were already redacted copies."
        if failed:
            msg += "\n\nProblems:\n" + "\n".join(failed[:10])
        self.say(f"Batch finished: {done}/{len(files)} redacted.")
        messagebox.showinfo("Batch finished", msg)


if __name__ == "__main__":
    Redactor().mainloop()
