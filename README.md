# score-to-musicxml

A small shell and Python wrapper for converting PDF sheet music to MusicXML
with [homr](https://github.com/liebharc/homr).

## Requirements

- Git
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- macOS or Linux

## Installation

```bash
git clone https://github.com/lingji-yidong/score-to-musicxml.git
cd score-to-musicxml
uv sync
chmod +x convert_score.sh
```

Python 3.11 is selected automatically. homr downloads its model files the first
time it runs.

## Usage

Convert a PDF and save the MusicXML file beside it:

```bash
./convert_score.sh score.pdf
```

Choose the output path:

```bash
./convert_score.sh score.pdf -o output/score.musicxml
```

Paths containing spaces must be quoted:

```bash
./convert_score.sh "Title - Composer.pdf"
```

Set the playback speed:

```bash
./convert_score.sh score.pdf --tempo 75
```

Add a visible quarter-note metronome marking and set the playback speed:

```bash
./convert_score.sh score.pdf --metronome 75 --tempo 75
```

Override the title or composer stored in the MusicXML file:

```bash
./convert_score.sh score.pdf \
  --title "Score title" \
  --composer "Composer"
```

Replace an existing output file:

```bash
./convert_score.sh score.pdf --overwrite
```

Run the following command to see every available option:

```bash
./convert_score.sh --help
```

## Updating an existing installation

```bash
git pull
uv sync
```

If the installation was created before the project switched to headless OpenCV,
repair the shared `cv2` files once:

```bash
uv sync --reinstall-package opencv-python-headless
```

## License

[GNU Affero General Public License v3.0](LICENSE), following homr upstream.

See [CITATIONS.md](CITATIONS.md) for upstream projects and licenses.

## Thanks

This project builds upon previous work, including:

- The Optical Music Recognition pipeline of [homr](https://github.com/liebharc/homr)
- The PDF rendering library [PyMuPDF](https://github.com/pymupdf/PyMuPDF)
