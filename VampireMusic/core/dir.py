import shutil
import os
from pathlib import Path

from VampireMusic import logger


def ensure_dirs():
    """
    Ensure that the necessary directories exist.
    """
    # Use static_ffmpeg binaries
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        logger.info("Added static_ffmpeg binaries to PATH.")
    except ImportError:
        logger.warning("static_ffmpeg not installed; using system binaries.")

    for dir in ["cache", "downloads"]:
        Path(dir).mkdir(parents=True, exist_ok=True)
    logger.info("Cache directories updated.")
