"""Windows UIA runtime validation.

The UIA sender depends on binary modules that must be built for the same
Python runtime.  Keep this check close to application startup so a stale
embedded environment fails loudly instead of producing a misleading import
or window-binding error later.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import re
import site
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EXPECTED_PACKAGES = {
    "pywin32": "312",
    "uiautomation": "2.0.29",
    "wechatauto-replica": "1.1.7",
}

_CPYTHON_ABI_RE = re.compile(r"\.cp(?P<abi>\d{2,3})(?:-[^/\\]+)?\.pyd$", re.IGNORECASE)


def _site_package_paths() -> list[Path]:
    paths: list[Path] = []
    candidates: list[str] = []
    try:
        candidates.extend(site.getsitepackages())
    except (AttributeError, TypeError):
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(user_site)
    except (AttributeError, TypeError):
        pass
    candidates.extend(path for path in sys.path if path and "site-packages" in path.lower())
    for raw in candidates:
        path = Path(raw).resolve()
        # ``site.getsitepackages()`` may include the venv root on Windows.
        # PyWin32 also adds ``win32``, ``win32/lib`` and ``pythonwin`` to
        # ``sys.path``; these are subdirectories of the same package root,
        # not independent package installations.
        if (
            path.is_dir()
            and path.name.lower() in {"site-packages", "dist-packages"}
            and path not in paths
        ):
            paths.append(path)
    return paths


def _module_path(module_name: str) -> str:
    try:
        module = importlib.import_module(module_name)
        return str(Path(module.__file__).resolve()) if getattr(module, "__file__", None) else ""
    except Exception as exc:
        return f"<import failed: {exc}>"


def inspect_windows_runtime() -> dict[str, Any]:
    """Collect version/path information and return validation errors."""
    result: dict[str, Any] = {
        "platform": sys.platform,
        "python": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_prefix": str(Path(sys.prefix).resolve()),
        "site_packages": [str(path) for path in _site_package_paths()],
        "packages": {},
        "modules": {},
        "errors": [],
    }

    if sys.platform != "win32":
        result["skipped"] = True
        result["ok"] = True
        return result

    if sys.version_info[:2] != (3, 12):
        result["errors"].append(
            f"需要 Python 3.12 x64，当前为 {sys.version_info[0]}.{sys.version_info[1]}"
        )

    for package, expected in EXPECTED_PACKAGES.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "未安装"
        result["packages"][package] = actual
        if actual != expected:
            result["errors"].append(f"{package} 需要 {expected}，当前为 {actual}")

    for module_name in ("fastapi", "uiautomation", "wechatauto", "win32ui"):
        result["modules"][module_name] = _module_path(module_name)

    site_paths = [Path(path).resolve() for path in result["site_packages"]]
    if len(site_paths) > 1:
        result["errors"].append(
            "检测到多个 site-packages: " + ", ".join(str(path) for path in site_paths)
        )

    prefix = Path(sys.prefix).resolve()
    for module_name, raw_path in result["modules"].items():
        if raw_path.startswith("<"):
            result["errors"].append(f"{module_name} 导入失败: {raw_path}")
            continue
        module_path = Path(raw_path).resolve()
        try:
            module_path.relative_to(prefix)
        except ValueError:
            result["errors"].append(
                f"{module_name} 来自当前 Python 环境之外: {module_path}"
            )

        match = _CPYTHON_ABI_RE.search(module_path.name)
        if match and match.group("abi") != "312":
            result["errors"].append(
                f"{module_name} 的 .pyd ABI 为 cp{match.group('abi')}，当前需要 cp312"
            )

    result["ok"] = not result["errors"]
    return result


def assert_windows_runtime() -> dict[str, Any]:
    """Log the runtime and raise a clear error when UIA is unsafe to use."""
    result = inspect_windows_runtime()
    logger.info(
        "Windows UIA 运行环境 | python=%s | executable=%s | site_packages=%s | packages=%s | modules=%s",
        result["python"].splitlines()[0],
        result["python_executable"],
        result["site_packages"],
        result["packages"],
        result["modules"],
    )
    if not result.get("ok", False):
        message = "Windows UIA 运行环境检查失败: " + "；".join(result["errors"])
        logger.error(message)
        raise RuntimeError(message)
    return result
