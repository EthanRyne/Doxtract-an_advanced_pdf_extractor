[![PyPI version](https://img.shields.io/pypi/v/doxtract.svg)](https://pypi.org/project/doxtract/)

# 📄 doxtract

**doxtract** is a high-level document preprocessing toolkit that extracts per-page structured metadata from PDFs, DOCX, PPTX, or TXT files — with optional diagram/image detection and support for returning data as a 🤗 HuggingFace `datasets.Dataset`.

---

## ✨ Features

- 🔍 Detects and skips repeating headers and footers
- 🧠 Heuristically filters out Table of Contents pages
- 🖼 Extracts vector diagrams and embedded raster images
- 📑 Reconstructs clean plain-text or Markdown layouts
- 🔁 Returns either:
  - A nested Python dictionary (`dict[doc_name → list[pages]]`)
  - A 🤗 `datasets.Dataset` for ML/NLP pipelines
- 🚫 Warns on scanned PDFs without OCR — no extraction guesswork

---

## 📦 Installation

```bash
pip install doxtract
````

Or for local development:

```bash
git clone https://github.com/EthanRyne/Advanced_pdf_extractor
cd Advanced_pdf_extractor
pip install -e .
```

Make sure you have [LibreOffice](https://www.libreoffice.org/) installed and available as `soffice` in your `PATH` (required for `.docx`, `.pptx`, `.txt` conversion).

---

## 🧪 Quick Example

```python
from doxtract.processor import preprocess

output = preprocess(
    ["input/spec_sheet.pdf", "notes.docx"],
    markdown=True,               # Output GitHub-flavored Markdown
    extract_vectors=True,        # Extract vector diagrams
    extract_images=True,         # Extract raster images
    strip_headers_footers=True,  # Remove headers/footers from text
    preserve_layout=False,       # If True, use exact spacing from the PDF
    max_workers=None,            # If given, will be used for parallel doc processing
    as_dataset=True              # Return a HuggingFace Dataset
)
print(output)
```

---

## ⚙️ Parameters

| Name                      | Type          | Description                                            |
| ------------------------- | ------------- | ------------------------------------------------------ |
| `paths`                   | `list[str]`   | List of input files (`.pdf`, `.docx`, `.pptx`, `.txt`) |
| `markdown`                | `bool`        | If `True`, output uses GitHub‑flavored Markdown        |
| `extract_vectors`         | `bool`        | Save and log bounding boxes of detected diagrams       |
| `extract_images`          | `bool`        | Save visible images per page                           |
| `output_root`             | `str or Path` | Directory to store outputs and extracted media         |
| `strip_headers_footers`   | `bool`        | Remove recurring headers/footers from output text      |
| `preserve_layout`         | `bool`        | If True, use exact spacing from the PDF                |
| `max_workers`             | `int`         | If given, will be used for parallel doc processing     |
| `as_dataset`              | `bool`        | Return as HuggingFace `datasets.Dataset`               |
| *(advanced tuning knobs)* |               |                                                        |
| `vector_margin`           | `int`         | Padding around diagrams (in px)                        |
| `page_top_pct`            | `float`       | % height for detecting headers                         |
| `page_bottom_pct`         | `float`       | % height for detecting footers                         |
| `min_header_pages`        | `int`         | Min pages with similar header/footer to consider valid |
| `toc_threshold`           | `int`         | TOC detection sensitivity                              |
| `y_tol`                   | `int`         | Line grouping tolerance (vertical)                     |
| `space_thresh`            | `int`         | Horizontal gap → one space                             |

---

## 🛑 OCR Handling

If a PDF is detected to be a **scanned document with no embedded text**, `doxtract` will **abort the run with a warning**:

> ⚠️ `scanned_file.pdf` looks like a scanned PDF with no text layer. Please run OCR first; aborting.

To preprocess such files, run OCR first using [OCRmyPDF](https://ocrmypdf.readthedocs.io/) or similar tools.

---

## 📁 Output Example (simplified)

Each output "page" is a dictionary with:

```json
{
  "document_name": "spec.pdf",
  "page_number": 3,
  "page_content": "...",
  "is_toc_page": false,
  "headers": ["My Spec Sheet"],
  "footers": [],
  "diagrams": [
    {"path": "Doc Data/spec/diagrams/p003_1.png", "bbox": [12.1, 55.2, 430.6, 310.4]}
  ],
  "images_on_this_page": [
    "Doc Data/spec/images/p003_xref12.png"
  ]
}
```

---

## 🤗 Dataset Mode

If `as_dataset=True`, the output is a HuggingFace-compatible `datasets.Dataset`, ideal for training/evaluation workflows:

```python
from datasets import Dataset

ds = preprocess(["spec.pdf"], as_dataset=True)
print(ds[0]["page_content"])
```

---

## 🧱 Dependencies

* `PyMuPDF` (fitz)
* `tqdm`
* `datasets` (optional, for dataset output)
* LibreOffice (`soffice`) for office conversion

---

## 🧑‍💻 License

MIT License © 2025

---

## 📬 Contributing

Pull requests welcome! For major changes, please open an issue first to discuss what you’d like to change or improve.

