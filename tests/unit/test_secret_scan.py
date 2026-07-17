import re
from pathlib import Path

from scripts.secret_scan import SecretPattern, scan_file


def test_secret_scan_detects_secret_assignment(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text('API_KEY = "abcdefghijklmnopqrstuvwxyz"\n', encoding="utf-8")
    patterns = [
        SecretPattern(
            name="secret-assignment",
            regex=re.compile(
                r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
            ),
        ),
    ]

    findings = scan_file(path, patterns)

    assert findings == [f"{path}:1: secret-assignment"]


def test_secret_scan_ignores_plain_documentation(tmp_path: Path) -> None:
    path = tmp_path / "example.md"
    path.write_text("Never store tokens in logs.\n", encoding="utf-8")
    patterns = [
        SecretPattern(
            name="secret-assignment",
            regex=re.compile(
                r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
            ),
        ),
    ]

    assert scan_file(path, patterns) == []

