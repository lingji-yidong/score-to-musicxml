# Upstream projects

This project wraps and redistributes no model weights directly. On first use,
homr downloads its published model artifacts from the upstream release.

## homr

- Project: <https://github.com/liebharc/homr>
- Revision: `6530038beb2a369c0b67a387bd9264c3dc2f8df4`
- License: GNU Affero General Public License v3.0

The revision is pinned because the PyPI 0.6.2 release disables slur and tie
export. The selected revision contains the improved slur model used by the PoC.

homr asks research users to cite oemer and Polyphonic-TrOMR. It also credits
oemer's segmentation models, Polyphonic-TrOMR's transformer model, and Benjamin
Roland's Python Poetry starter template.

## oemer

- Project: <https://github.com/BreezeWhite/oemer>
- Citation DOI: <https://doi.org/10.5281/zenodo.8429346>
- License: MIT

```bibtex
@software{yoyo_2023_8429346,
  author       = {Yoyo and
                  Christian Liebhardt and
                  Sayooj Samuel},
  title        = {BreezeWhite/oemer: v0.1.7},
  month        = oct,
  year         = 2023,
  publisher    = {Zenodo},
  version      = {v0.1.7},
  doi          = {10.5281/zenodo.8429346},
  url          = {https://doi.org/10.5281/zenodo.8429346}
}
```

## Polyphonic-TrOMR

- Project: <https://github.com/NetEase/Polyphonic-TrOMR>
- Paper: <https://arxiv.org/abs/2308.09370>
- License: Apache License 2.0

```bibtex
@article{li2023tromr,
  title   = {TrOMR: Transformer-Based Polyphonic Optical Music Recognition},
  author  = {Li, Yixuan and Liu, Huaping and Jin, Qiang and Cai, Miaomiao and Li, Peng},
  journal = {arXiv preprint arXiv:2308.09370},
  year    = {2023},
  doi     = {10.48550/arXiv.2308.09370}
}
```

## Python Poetry Bootstrap

- Project: <https://github.com/Parici75/python-poetry-bootstrap>
- Author: Benjamin Roland

homr credits this starter template. This project does not directly depend on the
template, but keeps the upstream acknowledgement chain visible.

## PyMuPDF

- Project: <https://pymupdf.readthedocs.io/>
- License information: <https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright>

PyMuPDF rasterizes source PDF pages before homr processes them.

## ONNX Runtime

- Project: <https://onnxruntime.ai/>
- License: MIT

Version 1.23.2 is pinned as the common reproducible version for Intel and Apple
Silicon macOS, x86_64 and ARM64 Linux, and x86_64 Windows. Newer releases no
longer provide an Intel macOS wheel.
