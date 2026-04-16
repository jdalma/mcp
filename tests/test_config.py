import os
from pathlib import Path


def test_vault_path_resolves():
    from config import get_vault_path
    vault_path = get_vault_path()
    assert isinstance(vault_path, Path)
    assert vault_path.is_absolute()


def test_default_config_values():
    from config import COLLECTION_NAME, INDEX_PATTERNS, MAX_RESULTS_DEFAULT
    assert isinstance(COLLECTION_NAME, str)
    assert len(INDEX_PATTERNS) > 0
    assert MAX_RESULTS_DEFAULT > 0
