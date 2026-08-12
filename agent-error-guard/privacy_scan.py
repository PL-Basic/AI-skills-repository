from __future__ import annotations

import argparse
import re
from pathlib import Path


TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".ps1",
    ".cmd",
    ".json",
    ".tsv",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
}
SENSITIVE_PATTERNS = {
    "windows-user-path": re.compile(r"(?i)[a-z]:[\\/]+users[\\/]+[^\\/\s]+"),
    "workspace-path": re.compile(r"(?i)[a-z]:[\\/]+(?:myproject|projects?)[\\/]"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[a-z0-9._~-]{20,}"),
    "jwt": re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\."),
    "password-assignment": re.compile(r"(?i)\bpassword\s*[:=]\s*[\"'][^\"']+[\"']"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a release tree for private data.")
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    findings: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(root)}: {name}")
    if findings:
        print("\n".join(findings))
        return 1
    print(f"Privacy scan passed: {sum(1 for path in root.rglob('*') if path.is_file())} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
