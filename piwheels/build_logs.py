def get_log_file_path(build_id, output_path):
    """
    Generate the log file path for a given build ID
    """
    levels = []
    n = build_id
    for _ in range(3):
        n, m = divmod(n, 10000)
        levels.append(m)
    levels = ['{:04d}'.format(level) for level in reversed(levels)]

    log_dir = output_path / 'logs' / levels[0] / levels[1]

    return log_dir / (levels[2] + '.txt.gz')

def log_path_to_build_id(output_path, log_path):
    """
    Get the build ID from a log file path
    """
    logs_dir = output_path / 'logs'
    return int(
        str(log_path)
        .removeprefix(str(logs_dir))
        .removesuffix(".txt.gz")
        .replace("/", "")
    )
