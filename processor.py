from __future__ import annotations

"""doxtract.processor
=====================

High‑level *preprocess* entry‑point that walks through one or many input
files, extracts structured page metadata, and optionally returns a 🤗
`datasets.Dataset`.  All behavioural toggles are passed **directly as
parameters** rather than via a dataclass.

If an input PDF looks like a *scanned* document (every page is a near
full‑page raster image and contains no embedded text), the run is **aborted**
with a warning so the user can run OCR first.
"""

import os, subprocess
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Union

import fitz  # type: ignore
from tqdm.notebook import tqdm

from .utils.geometry import expand_rect
from .utils.headers import extract_headers_and_footers
from .utils.toc import detect_toc_candidates, filter_page_sequence
from .utils.text import extract_markdown_layout, extract_text_skip_rects
from .utils.images import (
    get_visible_image_xrefs,
    is_full_page_image,
    _detect_diagrams,
)

__all__ = ["preprocess", "process_documents"]  # alias for backward compat

# ╭──────────────────────────────────────────────────────────────────────╮
# │ Conversion helper                                                    │
# ╰──────────────────────────────────────────────────────────────────────╯

def _convert_to_pdf(file_path: os.PathLike | str, output_dir: os.PathLike | str = "/tmp", *, verbose: bool = False) -> Path:
    """Return a *Path* to a freshly converted PDF using LibreOffice."""
    if verbose:
        print(f"Converting {file_path} → PDF…")
    ext = Path(file_path).suffix.lower()
    if ext not in {".docx", ".pptx", ".txt"}:
        raise ValueError(f"Unsupported file type '{ext}' for conversion")

    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(file_path),
        ],
        check=True,
    )
    return Path(output_dir) / Path(file_path).with_suffix(".pdf").name


# ╭──────────────────────────────────────────────────────────────────────╮
# │ OCR‑related guard                                                    │
# ╰──────────────────────────────────────────────────────────────────────╯

def _looks_scanned(pdf_path: Path) -> bool:
    """Heuristic: every page has *zero* text and is a near full‑page image."""
    doc = fitz.open(pdf_path)
    try:
        return all(
            page.get_text().strip() == "" and is_full_page_image(page) for page in doc
        )
    finally:
        doc.close()


# ╭──────────────────────────────────────────────────────────────────────╮
# │ Single page process                                                  │
# ╰──────────────────────────────────────────────────────────────────────╯

def _process_single_page(args):
    (
        pdf_path,
        page_number,
        markdown,
        extract_vectors,
        extract_images,
        strip_headers_footers,
        preserve_layout,
        vector_margin,
        y_tol,
        space_thresh,
        hf,
        toc_pages,
        diag_out,
        img_out,
    ) = args

    doc = fitz.open(pdf_path)
    page = doc[page_number]
    pg = page_number + 1

    # ——— diagrams ————————————————————————————————
    diag_rects = []
    if extract_vectors:
        diag_rects = _detect_diagrams(page)
        for idx, box in enumerate(diag_rects, 1):
            out_image = diag_out / f"p{pg:03d}_{idx}.png"
            page.get_pixmap(clip=expand_rect(box, vector_margin), dpi=300).save(out_image)

    # ——— skip zones ———————————————————————————————
    hdr_r = hf["page_header_rects"].get(pg, [])
    ftr_r = hf["page_footer_rects"].get(pg, [])
    skip_rects = diag_rects + (hdr_r + ftr_r if strip_headers_footers else [])

    # ——— text extraction ————————————————————————————
    if not preserve_layout:
        content = page.get_text("text")
    else:
        if markdown:
            content = "\n".join(
                extract_markdown_layout(page, skip_rects, y_tol=y_tol, space_thresh=space_thresh)
            )
        else:
            content = "\n".join(
                extract_text_skip_rects(page, skip_rects, y_tol=y_tol, space_thresh=space_thresh)
            )

    meta = {
        "document_name": Path(pdf_path).name,
        "page_number": pg,
        "is_toc_page": pg in toc_pages,
        "page_content": content,
        "headers": [page.get_textbox(r).strip() for r in hdr_r],
        "footers": [page.get_textbox(r).strip() for r in ftr_r],
        "diagrams": [],
        "images_on_this_page": [],
    }

    for idx, box in enumerate(diag_rects, 1):
        meta["diagrams"].append(
            {
                "path": str(diag_out / f"p{pg:03d}_{idx}.png"),
                "bbox": [
                    round(box.x0, 2),
                    round(box.y0, 2),
                    round(box.x1, 2),
                    round(box.y1, 2),
                ],
            }
        )

    if extract_images:
        for xref in get_visible_image_xrefs(page):
            pix = fitz.Pixmap(doc, xref)
            img_path = img_out / f"p{pg}_xref{xref}.png"
            pix.save(img_path)
            meta["images_on_this_page"].append(str(img_path))

    doc.close()
    return meta

# ╭──────────────────────────────────────────────────────────────────────╮
# │ Main function                                                        │
# ╰──────────────────────────────────────────────────────────────────────╯

def preprocess(
    paths: List[os.PathLike | str],
    *,
    markdown: bool = False,
    extract_vectors: bool = False,
    extract_images: bool = False,
    output_root: os.PathLike | str | None = None,
    strip_headers_footers: bool = True,
    preserve_layout: bool = False,
    max_workers: int | None = None,
    as_dataset: bool = False,
    # advanced knobs
    vector_margin: int = 20,
    page_top_pct: float = 0.12,
    page_bottom_pct: float = 0.12,
    min_header_pages: int = 3,
    toc_threshold: int = 3,
    y_tol: int = 2,
    space_thresh: int = 5,
    verbose: bool = False,
) -> Union[Dict[str, List[Dict]], "datasets.Dataset", None]:
    """Pre‑process documents into page‑level metadata.

    Parameters
    ----------
    paths
        List of input file paths (`PDF`, `DOCX`, `PPTX`, `TXT`). Office files
        are auto‑converted to PDF via LibreOffice.
    markdown
        If *True*, `page_content` is returned in GitHub‑flavoured Markdown.
        Otherwise a left‑indented plain‑text approximation is used.
    extract_vectors
        Save detected vector diagrams to *diagrams/* and include their file
        paths + bounding boxes in metadata.
    extract_images
        Save visible raster images to *images/* and list their paths in
        metadata.
    output_root
        Output directory where one sub‑folder per document is created.  When
        *None* (default) this falls back to ``"Doc Data"``.
    strip_headers_footers
        When *True* (default) repeating headers/footers are removed from
        `page_content` but still listed separately in metadata.
    preserve_layout
        If *True*, extracts page text with spacing preserved as-is from the PDF.
        This disables all layout rebuilding and formatting logic (e.g., markdown,
        indentation heuristics). Default is *False*.
    max_workers
        Number of workers for multi processing.
        If given, will set to the minimum out of given and available cpu cores.
        If not given, will set to the available cpu cores.
    as_dataset
        Return a `datasets.Dataset` instead of a nested ``dict``.
    vector_margin, page_top_pct, page_bottom_pct, min_header_pages,
    toc_threshold, y_tol, space_thresh
        Advanced tuning knobs — keep defaults unless you know what you’re
        doing.
            vector_margin - Padding around diagrams (in px)
            page_top_pct - % height for detecting headers
            page_bottom_pct - % height for detecting footers
            min_header_pages - Min pages with similar header/footer to consider valid
            toc_threshold - TOC detection sensitivity 
            y_tol - Line grouping tolerance (vertical)
            space_thresh - Horizontal gap → one space

    Returns
    -------
    dict | datasets.Dataset | None
        *Nested* ``{doc_name → [page_meta, …]}`` or a 🤗 Dataset when
        *as_dataset=True*.  Returns **None** if any input PDF appears to be
        a scanned document requiring OCR (a warning is printed).
    """

    out_root = Path(output_root or "Doc Data")
    out_root.mkdir(parents=True, exist_ok=True)

    # Collate rows (for Dataset) or dict (legacy)
    dataset_rows: List[Dict] = []
    legacy: Dict[str, List[Dict]] = defaultdict(list)

    for p in paths:
        path = Path(p)
        ext = path.suffix.lower()

        # ─── office → PDF ─────────────────────────────────────────────
        if ext in {".docx", ".pptx", ".txt"}:
            path = _convert_to_pdf(path, verbose=verbose)
        elif ext != ".pdf":
            raise ValueError(f"Unsupported file type: {path}")

        # ─── abort if scanned ─────────────────────────────────────────
        if _looks_scanned(path):
            print(f"⚠️  {path.name} looks like a scanned PDF with no text layer.  "
                  "Please run OCR first; aborting.")
            return None

        doc = fitz.open(path)
        doc_outdir = out_root / path.stem
        doc_outdir.mkdir(parents=True, exist_ok=True)

        diag_out = doc_outdir / "diagrams"
        img_out = doc_outdir / "images"
        if extract_vectors:
            diag_out.mkdir(exist_ok=True)
        if extract_images:
            img_out.mkdir(exist_ok=True)

        hf = extract_headers_and_footers(
            doc,
            top_pct=page_top_pct,
            bottom_pct=page_bottom_pct,
            min_pages=min_header_pages,
            verbose=verbose,
        )

        toc_candidates = detect_toc_candidates(doc, threshold=toc_threshold, verbose=verbose)
        toc_pages = filter_page_sequence(toc_candidates)

        # ——— multi processing ————————————————————————————————
        tasks = []
        total_pages = len(doc)
        
        for i in range(total_pages):
            tasks.append(
                (
                    str(path),
                    i,
                    markdown,
                    extract_vectors,
                    extract_images,
                    strip_headers_footers,
                    preserve_layout,
                    vector_margin,
                    y_tol,
                    space_thresh,
                    hf,
                    toc_pages,
                    diag_out,
                    img_out,
                )
            )

        if max_workers:
            max_workers = max(1, min(max_workers, mp.cpu_count() - 1))
        else:
            max_workers = max(1, mp.cpu_count() - 1)
        if max_workers == 1:
            print("Max Workers is set to 1, document processing won't speed up ") 
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_process_single_page, t) for t in tasks]
        
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Processing {path.name}",
                disable=not verbose,
            ):
                meta = future.result()
                dataset_rows.append(meta)
                legacy[path.name].append(meta)

    # ——— return value ————————————————————————————————
    if as_dataset:
        try:
            from datasets import Dataset, DatasetDict  # type: ignore
        except ImportError as e:
            raise RuntimeError("as_dataset=True but the 'datasets' package is missing.  pip install datasets") from e

        grouped = defaultdict(list)
        for row in dataset_rows:
            grouped[row["document_name"]].append(row)

        return DatasetDict({
            doc_name: Dataset.from_list(pages)
            for doc_name, pages in grouped.items()
        })
    else:
        return dict(legacy)

# Backward compatibility alias
process_documents = preprocess
