"""Build React and stage only the files needed by the App Service Python app."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
PACKAGE = SOURCE / ".appservice"


def main():
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("Node.js and npm are required to build the React frontend. Install Node.js 22 or later.")

    frontend = SOURCE / "frontend"
    for command in ("install", "build"):
        arguments = [npx, "--yes", "--package=pnpm@10.6.0", "--", "pnpm", command]
        if command == "install":
            arguments.append("--frozen-lockfile")
        subprocess.run(arguments, cwd=frontend, check=True)

    assets = SOURCE / "api" / "static" / "react" / "assets"
    for name in ("main-react-app.js", "main-react-app.css"):
        if not (assets / name).is_file():
            raise RuntimeError(f"Frontend build did not produce {assets / name}")

    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    PACKAGE.mkdir()
    shutil.copytree(
        SOURCE / "api",
        PACKAGE / "api",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*"),
    )
    for name in ("requirements.txt", "gunicorn.conf.py", ".deployment"):
        shutil.copy2(SOURCE / name, PACKAGE / name)
    shutil.copy2(ROOT / "LICENSE", PACKAGE / "LICENSE")
    print(f"App Service deployment files staged in {PACKAGE}")


if __name__ == "__main__":
    main()
