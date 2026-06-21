# Upstream projects

This project wraps and redistributes no model weights directly. On first use,
HOMR downloads its published model artifacts from the upstream release.

## HOMR

- Project: <https://github.com/liebharc/homr>
- Revision: `6530038beb2a369c0b67a387bd9264c3dc2f8df4`
- License: GNU Affero General Public License v3.0

The revision is pinned because the PyPI 0.6.2 release disables slur and tie
export. The selected revision contains the improved slur model used by the PoC.

## PyMuPDF

- Project: <https://pymupdf.readthedocs.io/>
- License information: <https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright>

PyMuPDF rasterizes source PDF pages before HOMR processes them.

## ONNX Runtime

- Project: <https://onnxruntime.ai/>
- License: MIT

Version 1.23.2 is pinned as the common reproducible version for Intel and Apple
Silicon macOS, x86_64 and ARM64 Linux, and x86_64 Windows. Newer releases no
longer provide an Intel macOS wheel.
