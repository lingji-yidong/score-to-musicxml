"""homr command discovery and execution."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from score_to_musicxml.errors import ConversionError
from score_to_musicxml.pdf import is_low_ink_page
from score_to_musicxml.progress import log

DEFAULT_HOMR_REPO = Path(__file__).resolve().parent.parent.parent / "homr"


def find_homr_repo() -> Path | None:
    """
    Return a local homr checkout, matching the PoC lookup strategy.

    The ``HOMR_REPO`` environment variable wins. If it is not set, the wrapper
    looks for a sibling checkout at ``../homr`` relative to this project.
    """
    configured_path = os.environ.get("HOMR_REPO")
    candidates = [
        Path(configured_path).expanduser() if configured_path else None,
        DEFAULT_HOMR_REPO,
    ]

    for candidate in candidates:
        if candidate is None:
            continue
        resolved_candidate = candidate.resolve()
        if (resolved_candidate / "pyproject.toml").is_file() and (
            resolved_candidate / "homr" / "main.py"
        ).is_file():
            return resolved_candidate

    return None


def homr_command() -> list[str]:
    """
    Build the homr command exactly like the PoC.

    Prefer the installed ``homr`` executable. If it is unavailable, fall back to
    ``uvx`` and use a local homr checkout when available.
    """
    installed_homr = shutil.which("homr")
    if installed_homr:
        return [installed_homr]

    installed_uvx = shutil.which("uvx")
    if installed_uvx:
        local_repo = find_homr_repo()
        if local_repo is not None:
            log(f"Using local homr checkout: {local_repo}")
            return [installed_uvx, "--from", str(local_repo), "homr"]
        return [installed_uvx, "homr"]

    raise ConversionError(
        "homr is unavailable. Install homr, install uv, or set HOMR_REPO."
    )


def run_homr(  # noqa: PLR0912, PLR0913
    page_paths: list[Path],
    *,
    gpu: str,
    debug: bool,
    cache: bool,
    large_page: bool,
    metronome: int | None,
    tempo: int | None,
) -> list[Path]:
    """
    Run homr's CLI on all rendered pages in one directory-mode process.

    The command resolution deliberately mirrors the PoC instead of calling
    ``sys.executable -m homr.main``. That avoids accidentally using a different
    Python environment, homr version, or model setup.
    """
    if not page_paths:
        raise ConversionError("No rendered pages were provided to homr")

    command = [*homr_command(), str(page_paths[0].parent)]
    if gpu != "auto":
        command.extend(["--gpu", gpu])
    if debug:
        command.append("--debug")
    if cache:
        command.append("--cache")
    if large_page:
        command.append("--output-large-page")
    if metronome is not None:
        command.extend(["--output-metronome", str(metronome)])
    if tempo is not None:
        command.extend(["--output-tempo", str(tempo)])

    log(f"Running homr on {page_paths[0].parent}...")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise ConversionError(f"homr exited with status {error.returncode}") from error

    outputs: list[Path] = []
    missing: list[str] = []
    for page_path in page_paths:
        output_path = page_path.with_suffix(".musicxml")
        if output_path.is_file():
            outputs.append(output_path)
        elif is_low_ink_page(page_path):
            log(f"Skipping low-ink page with no homr output: {page_path.name}")
        else:
            missing.append(output_path.name)

    if missing:
        raise ConversionError(f"homr did not produce output for: {', '.join(missing)}")
    if not outputs:
        raise ConversionError("homr did not produce any MusicXML pages")
    return outputs
