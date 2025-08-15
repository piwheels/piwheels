from pathlib import Path

def get_log_file_path(build_id: int, output_path: Path) -> Path:
    """
    Generate the log file path for a given build ID
    """
    levels = []
    n = build_id
    for _ in range(3):
        n, m = divmod(n, 10000)
        levels.append(m)
    levels = ["{:04d}".format(level) for level in reversed(levels)]

    log_dir = output_path / "logs" / levels[0] / levels[1]

    return log_dir / (levels[2] + ".txt.gz")

def get_log_url(build_id: int) -> str:
    """
    Return the URL for the log file for a given build ID, relative to the
    root of the web server
    """
    return str(get_log_file_path(output_path=Path("/"), build_id=build_id))

def log_path_to_build_id(output_path: Path, log_path: Path) -> int:
    """
    Get the build ID from a log file path
    """
    logs_dir = output_path / "logs"
    rel_path = log_path.relative_to(logs_dir).with_suffix("").with_suffix("")
    build_id_str = "".join(rel_path.parts)
    return int(build_id_str)