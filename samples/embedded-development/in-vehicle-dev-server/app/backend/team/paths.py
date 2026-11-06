"""Where the scenario's folder is (D12): the app uses its checks/, bench/, knowledge/ and reference-project/ in place.

``setup.sh`` writes the folder's absolute path into the app's data directory (``sample.json``: ``{"sample": "/abs"}``).
Without that file, ``$VSTATD_SAMPLE``, then the dev checkout (the app's parent folder when it has ``checks/``). The team
file writes ``${sample}/...``, which ``expand`` replaces with that path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .constants import APP_ROOT
from .httpkit import AppError

SAMPLE_FILE = "sample.json"
SAMPLE_VAR = "${sample}"
NEEDED = ("checks", "reference-project")  # what a run cannot go without


def sample_dir(data_dir: Path | str | None) -> Path:
    """The scenario folder, checked; an AppError says what is missing."""
    found, where = None, ""
    record = Path(data_dir) / SAMPLE_FILE if data_dir else None
    if record is not None and record.is_file():
        try:
            found, where = json.loads(record.read_text(encoding="utf-8"))["sample"], str(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AppError(f"场景文件夹的记录 {record} 读不了：{exc}；重新运行 setup.sh", "no_sample", 500, detail=exc) from exc
    elif os.environ.get("VSTATD_SAMPLE"):
        found, where = os.environ["VSTATD_SAMPLE"], "VSTATD_SAMPLE"
    elif (APP_ROOT.parent / "checks").is_dir():
        found, where = str(APP_ROOT.parent), "开发目录"
    if not found:
        raise AppError("不知道场景文件夹在哪：先运行场景的 setup.sh（它把路径记在 app 的数据目录 sample.json 里）",
                       "no_sample", 500)
    path = Path(str(found)).expanduser()
    if not path.is_absolute():
        raise AppError(f"场景文件夹要是绝对路径：{found}（来自 {where}）", "no_sample", 500, detail=found)
    missing = [n for n in NEEDED if not (path / n).is_dir()]
    if missing:
        raise AppError(f"场景文件夹 {path}（来自 {where}）里没有 {'、'.join(m + '/' for m in missing)}：文件夹移动过？"
                       "重新运行 setup.sh", "no_sample", 500)
    return path


def expand(value: Any, sample: Path | str) -> Any:
    """*value* with every ``${sample}`` in its strings replaced by *sample* (lists and objects all the way down)."""
    if isinstance(value, str):
        return value.replace(SAMPLE_VAR, str(sample))
    if isinstance(value, list):
        return [expand(v, sample) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, sample) for k, v in value.items()}
    return value
