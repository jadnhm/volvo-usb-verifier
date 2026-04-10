from datetime import datetime
import logging
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


def create_run_output_dir(base_dir: Optional[PathLike], prefix: str) -> Path:
    """Create and return a timestamped directory for one tool run."""
    root_dir = Path(base_dir) if base_dir is not None else Path("logs")
    root_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = root_dir / f"{prefix}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def resolve_run_output_dir(logs_dir: Optional[PathLike], prefix: str) -> Path:
    """Use an explicitly provided output directory or create a new timestamped one."""
    if logs_dir:
        run_dir = Path(logs_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir
    return create_run_output_dir(Path("logs"), prefix)


def configure_file_logger(logger_name: str, log_file: Path) -> logging.Logger:
    """Attach a single file handler for this run and remove stale file handlers."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(file_handler)
    return logger