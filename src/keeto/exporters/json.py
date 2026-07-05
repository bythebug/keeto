from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keeto.core.span import Trace


def export_json(traces: list[Trace], path: str | None = None) -> None:
    data = [t.model_dump(mode="json") for t in traces]
    payload = json.dumps(data, indent=2, default=str)

    if path:
        Path(path).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
        sys.stdout.write("\n")
