def _get_version_from_metadata(default: str = '0.1.0') -> str:
    try:
        from importlib.metadata import version, PackageNotFoundError
    except Exception:
        return default

    try:
        return version('ts-scan-agent')
    except PackageNotFoundError:
        return default


__version__ = _get_version_from_metadata()
