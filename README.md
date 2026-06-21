# score-to-musicxml

A small shell and Python wrapper for converting PDF sheet music to MusicXML
with [homr](https://github.com/liebharc/homr).

## Setup

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
uv sync
chmod +x convert_score.sh
./scripts/install-git-hooks.sh
```

Python 3.11 is selected automatically. The lockfile supports Intel and Apple
Silicon Macs plus x86_64 and ARM64 Linux. ONNX Runtime uses the available CPU
provider by default.

## Usage

```bash
./convert_score.sh score.pdf
./convert_score.sh score.pdf -o output/score.musicxml
./convert_score.sh score.pdf --metronome 75 --tempo 75
./convert_score.sh "Title - Composer.pdf"
./convert_score.sh score.pdf --title "Score title" --composer "Composer"
```

Run `./convert_score.sh --help` for all options. homr downloads its model
weights on first use. The converter reads useful PDF title/author metadata and
falls back to filenames in the `Title - Composer.pdf` form.

The HOMR dependency is pinned to the same upstream revision used by the PoC.
The older 0.6.2 release deliberately disables slur/tie export and must not be
substituted if output parity matters.

The wrapper also repairs HOMR's invalid cross-staff `backup` placement when
both staff streams already contain the correct number of beats. Genuine
irregular final measures are preserved and marked as such for MuseScore.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

The pre-commit hook applies safe Ruff fixes and formatting. If it changes a
Python file, review and stage the result before committing again.

See [CITATIONS.md](CITATIONS.md) for upstream projects and licenses.

## License

[GNU Affero General Public License v3.0](LICENSE), following homr upstream.
