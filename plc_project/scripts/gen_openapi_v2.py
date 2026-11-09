"""Export the real FastAPI OpenAPI document restricted to /api/v2 paths."""
from __future__ import annotations

import json
from pathlib import Path

from gateway.app.main import app

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "v2" / "contracts" / "api_v2.openapi.json"


def main() -> None:
    schema = app.openapi()
    schema["paths"] = {path: item for path, item in schema.get("paths", {}).items() if path.startswith("/api/v2")}
    schema["info"] = {
        "title": "PLC Agent V2 Unified Engineering API",
        "version": "2.0.0",
        "description": (
            "Generated from gateway.app.main:app. v1 /api/v1/plc routes remain registered "
            "and unchanged. Every response carries evidence_level."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} with {len(schema['paths'])} v2 paths")


if __name__ == "__main__":
    main()
