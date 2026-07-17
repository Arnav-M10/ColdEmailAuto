import re
import shutil
import subprocess  # nosec B404
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SecretPattern:
    name: str
    regex: re.Pattern[str]


def load_patterns(config_path: Path) -> list[SecretPattern]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return [
        SecretPattern(name=item["name"], regex=re.compile(item["regex"]))
        for item in config.get("patterns", [])
    ]


def tracked_files(project_root: Path) -> list[Path]:
    git_path = shutil.which("git")
    if git_path is None:
        raise RuntimeError("git executable was not found on PATH.")
    result = subprocess.run(  # noqa: S603
        [git_path, "ls-files"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )  # nosec B603
    return [project_root / line for line in result.stdout.splitlines() if line]


def scan_file(path: Path, patterns: list[SecretPattern]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.regex.search(line):
                findings.append(f"{path}:{line_number}: {pattern.name}")
    return findings


def run(project_root: Path) -> list[str]:
    patterns = load_patterns(project_root / "security" / "secret-scan.toml")
    findings: list[str] = []
    for path in tracked_files(project_root):
        findings.extend(scan_file(path, patterns))
    return findings


def main() -> int:
    project_root = Path.cwd()
    findings = run(project_root)
    if findings:
        print("Potential secrets found:")  # noqa: T201
        for finding in findings:
            print(finding)  # noqa: T201
        return 1
    print("No potential secrets found in tracked files.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
