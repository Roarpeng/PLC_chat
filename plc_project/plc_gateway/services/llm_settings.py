"""Persist LLM slots: up to 3 chat + 3 embed + 3 rerank."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from gateway.app.config import Settings, get_settings
from gateway.app.schemas.llm import (
    LlmAgentBinding,
    LlmModelInfo,
    LlmSettingsResponse,
    LlmSettingsUpdate,
    LlmSlotStatus,
    LlmSlotUpdate,
)

logger = logging.getLogger("researchos.gateway.llm")

# Default: 1 chat + 1 embed + 1 rerank. Extra ids exist as a pool; UI Add enables them.
SLOTS: list[tuple[str, str, str, str, str]] = [
    # id, label, kind, default_model, default_base_url
    ("chat_a", "对话模型", "chat", "gpt-4o-mini", "https://api.openai.com/v1"),
    ("chat_b", "对话模型 2", "chat", "gpt-4o-mini", "https://api.openai.com/v1"),
    ("chat_c", "对话模型 3", "chat", "gpt-4o-mini", "https://api.openai.com/v1"),
    ("embed", "向量模型", "embed", "text-embedding-3-small", "https://api.openai.com/v1"),
    ("embed_b", "向量模型 2", "embed", "text-embedding-3-small", "https://api.openai.com/v1"),
    ("embed_c", "向量模型 3", "embed", "text-embedding-3-small", "https://api.openai.com/v1"),
    ("rerank", "召回模型", "rerank", "jina-reranker-v2-base-multilingual", "https://api.jina.ai/v1"),
    ("rerank_b", "召回模型 2", "rerank", "jina-reranker-v2-base-multilingual", "https://api.jina.ai/v1"),
    ("rerank_c", "召回模型 3", "rerank", "jina-reranker-v2-base-multilingual", "https://api.jina.ai/v1"),
]

_SLOT_META = {
    sid: {
        "label": label,
        "kind": kind,
        "default_model": model,
        "default_base_url": base,
    }
    for sid, label, kind, model, base in SLOTS
}

CHAT_SLOT_IDS = {"chat_a", "chat_b", "chat_c"}
EMBED_SLOT_IDS = {"embed", "embed_b", "embed_c"}
RERANK_SLOT_IDS = {"rerank", "rerank_b", "rerank_c"}
VALID_SLOT_IDS = set(_SLOT_META)
PRIMARY_SLOT_IDS = ("chat_a", "embed", "rerank")
KIND_POOL: dict[str, tuple[str, ...]] = {
    "chat": ("chat_a", "chat_b", "chat_c"),
    "embed": ("embed", "embed_b", "embed_c"),
    "rerank": ("rerank", "rerank_b", "rerank_c"),
}
MAX_SLOTS_PER_KIND = 3


def _settings_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    override = os.getenv("LLM_SETTINGS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(settings.plc_work_dir or tempfile.gettempdir()) / "researchos_llm"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


def _keys_path(settings: Settings | None = None) -> Path:
    return _settings_path(settings).with_name("slot_keys.json")


def _slots_path(settings: Settings | None = None) -> Path:
    return _settings_path(settings).with_name("slot_configs.json")


def _primary_of_kind(kind: str) -> str:
    return KIND_POOL[kind][0]


def _order_enabled(ids: list[str]) -> list[str]:
    wanted = {sid for sid in ids if sid in VALID_SLOT_IDS}
    for primary in PRIMARY_SLOT_IDS:
        wanted.add(primary)
    ordered: list[str] = []
    for kind in ("chat", "embed", "rerank"):
        for sid in KIND_POOL[kind]:
            if sid in wanted:
                ordered.append(sid)
    return ordered


def _load_enabled_slots(
    *,
    data: dict[str, Any] | None = None,
    keys: dict[str, str] | None = None,
) -> list[str]:
    del keys  # extras are opt-in via add_slot, never inferred from leftover keys
    payload = data if data is not None else _load_json(_settings_path())
    raw = payload.get("enabled_slots")
    if isinstance(raw, list) and any(str(x) in VALID_SLOT_IDS for x in raw):
        ids = [str(x) for x in raw if str(x) in VALID_SLOT_IDS]
    else:
        ids = list(PRIMARY_SLOT_IDS)
    return _order_enabled(ids)


def _has_saved_key(sid: str, keys: dict[str, str]) -> bool:
    return bool((keys.get(sid) or "").strip())


def _compact_unconfigured_primary(
    data: dict[str, Any],
    keys: dict[str, str],
    configs: dict[str, dict[str, str]],
    enabled: list[str],
) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, str]], list[str], bool]:
    """If the default slot has no key but an extra does, fold that extra into the default.

    Old A/B/C UI left DeepSeek on chat_c while chat_a stayed the empty OpenAI placeholder.
    """
    agents = dict(data.get("agents") or {})
    changed = False
    current = list(enabled)
    for pool in KIND_POOL.values():
        primary = pool[0]
        first_extra = pool[1] if len(pool) > 1 else None
        later = [sid for sid in pool[2:] if sid in current]
        # 对话模型 3 without 对话模型 2 = leftover from old A/B/C slots, not a real Add.
        if first_extra is None or first_extra in current:
            continue
        if _has_saved_key(primary, keys):
            continue
        donor = next((sid for sid in later if _has_saved_key(sid, keys)), None)
        if donor is None:
            continue
        donor_key = (keys.get(donor) or os.getenv(f"ROS_LLM_{donor.upper()}_API_KEY") or "").strip()
        if donor_key:
            keys[primary] = donor_key
        donor_cfg = configs.get(donor) or {}
        configs[primary] = {
            "model": str(donor_cfg.get("model") or "").strip(),
            "base_url": str(donor_cfg.get("base_url") or "").strip(),
        }
        keys.pop(donor, None)
        configs[donor] = {"model": "", "base_url": ""}
        current = [sid for sid in current if sid != donor]
        for role, mid in list(agents.items()):
            if mid == donor:
                agents[role] = primary
        changed = True
        logger.info("folded extra slot %s into default %s", donor, primary)
    enabled_out = _order_enabled(current)
    if changed:
        data = dict(data)
        data["agents"] = agents
        data["enabled_slots"] = enabled_out
    return data, keys, configs, enabled_out, changed


def _persist_settings_doc(data: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_live_state(*, persist: bool = True) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, str]], list[str]]:
    data = _load_json(_settings_path())
    keys = _migrate_legacy_keys(_load_json(_keys_path()))
    configs = _load_slot_configs()
    enabled = _load_enabled_slots(data=data, keys=keys)
    data, keys, configs, enabled, changed = _compact_unconfigured_primary(data, keys, configs, enabled)
    if persist and changed:
        _persist_settings_doc(data)
        _write_slot_state(keys, configs)
    return data, keys, configs, enabled


def _next_spare_slot(kind: str, enabled: list[str]) -> str | None:
    pool = KIND_POOL.get(kind)
    if not pool:
        return None
    have = set(enabled)
    for sid in pool:
        if sid not in have:
            return sid
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _mask(value: str) -> str:
    v = value.strip()
    if len(v) <= 8:
        return "****"
    return f"{v[:4]}…{v[-4:]}"


def _migrate_legacy_keys(raw_keys: dict[str, Any]) -> dict[str, str]:
    """Accept old provider_keys.json shape if present."""
    legacy_path = _settings_path().with_name("provider_keys.json")
    legacy = _load_json(legacy_path) if not raw_keys else {}
    merged = {**legacy, **raw_keys}
    out: dict[str, str] = {}
    # map old vendor keys onto chat_a if slots empty
    vendor_key = (
        str(merged.get("openai") or merged.get("deepseek") or merged.get("dashscope") or "")
    ).strip()
    for sid in VALID_SLOT_IDS:
        if sid in merged and str(merged[sid]).strip():
            out[sid] = str(merged[sid]).strip()
    if vendor_key and "chat_a" not in out:
        out["chat_a"] = vendor_key
    return out


def _load_slot_configs() -> dict[str, dict[str, str]]:
    raw = _load_json(_slots_path())
    legacy = _load_json(_settings_path().with_name("provider_configs.json"))
    out: dict[str, dict[str, str]] = {}
    for sid, meta in _SLOT_META.items():
        row = raw.get(sid) if isinstance(raw.get(sid), dict) else {}
        if not row and sid == "chat_a" and isinstance(legacy.get("openai"), dict):
            row = legacy["openai"]
        out[sid] = {
            "model": str(row.get("model") or "").strip()
            or (meta["default_model"] if sid in PRIMARY_SLOT_IDS else ""),
            "base_url": str(
                row.get("base_url") if row.get("base_url") is not None else ""
            ).strip()
            or (meta["default_base_url"] if sid in PRIMARY_SLOT_IDS else ""),
        }
    return out


def _write_runtime_artifacts(keys: dict[str, str], configs: dict[str, dict[str, str]]) -> None:
    base = _slots_path().parent
    base.mkdir(parents=True, exist_ok=True)

    env_lines: list[str] = []
    for sid, key in keys.items():
        env_name = f"ROS_LLM_{sid.upper()}_API_KEY"
        env_lines.append(f"{env_name}={key}")
        os.environ[env_name] = key
    for sid, cfg in configs.items():
        if cfg.get("base_url"):
            env_lines.append(f"ROS_LLM_{sid.upper()}_BASE_URL={cfg['base_url']}")
            os.environ[f"ROS_LLM_{sid.upper()}_BASE_URL"] = cfg["base_url"]
        if cfg.get("model"):
            env_lines.append(f"ROS_LLM_{sid.upper()}_MODEL={cfg['model']}")
            os.environ[f"ROS_LLM_{sid.upper()}_MODEL"] = cfg["model"]

    (base / "provider_keys.env").write_text(
        "\n".join(env_lines) + ("\n" if env_lines else ""),
        encoding="utf-8",
    )

    yaml_lines = [
        "# Generated by ResearchOS — enabled chat / embed / rerank slots",
        "model_list:",
    ]
    enabled = set(_load_enabled_slots(keys=keys))
    for sid, cfg in configs.items():
        if sid not in enabled:
            continue
        meta = _SLOT_META[sid]
        model = cfg.get("model") or meta["default_model"]
        kind = meta["kind"]
        if kind == "chat":
            litellm_model = model if "/" in model else f"openai/{model}"
        elif kind == "embed":
            litellm_model = model if "/" in model else f"openai/{model}"
        else:
            # rerank — prefer openai-compatible or jina/
            litellm_model = model if "/" in model else f"jina_ai/{model}"
        yaml_lines.append(f"  - model_name: {sid}")
        yaml_lines.append("    litellm_params:")
        yaml_lines.append(f"      model: {litellm_model}")
        yaml_lines.append(f"      api_key: os.environ/ROS_LLM_{sid.upper()}_API_KEY")
        if cfg.get("base_url"):
            yaml_lines.append(f"      api_base: {cfg['base_url']}")
        # aliases for legacy agent names
        if sid == "chat_a":
            for alias in ("default", "planner", "strong"):
                yaml_lines.append(f"  - model_name: {alias}")
                yaml_lines.append("    litellm_params:")
                yaml_lines.append(f"      model: {litellm_model}")
                yaml_lines.append("      api_key: os.environ/ROS_LLM_CHAT_A_API_KEY")
                if cfg.get("base_url"):
                    yaml_lines.append(f"      api_base: {cfg['base_url']}")
        if sid == "chat_b":
            for alias in ("researcher", "plc"):
                yaml_lines.append(f"  - model_name: {alias}")
                yaml_lines.append("    litellm_params:")
                yaml_lines.append(f"      model: {litellm_model}")
                yaml_lines.append("      api_key: os.environ/ROS_LLM_CHAT_B_API_KEY")
                if cfg.get("base_url"):
                    yaml_lines.append(f"      api_base: {cfg['base_url']}")
        if sid == "chat_c":
            yaml_lines.append("  - model_name: writer")
            yaml_lines.append("    litellm_params:")
            yaml_lines.append(f"      model: {litellm_model}")
            yaml_lines.append("      api_key: os.environ/ROS_LLM_CHAT_C_API_KEY")
            if cfg.get("base_url"):
                yaml_lines.append(f"      api_base: {cfg['base_url']}")

    (base / "litellm_providers.generated.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    (base / "provider_runtime.json").write_text(
        json.dumps({"slots": configs, "keys": list(keys.keys())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _slot_status() -> list[LlmSlotStatus]:
    _data, keys, configs, enabled = _load_live_state()
    out: list[LlmSlotStatus] = []
    for sid in enabled:
        meta = _SLOT_META[sid]
        key = keys.get(sid, "")
        env_key = (os.getenv(f"ROS_LLM_{sid.upper()}_API_KEY") or "").strip()
        configured = bool(key or env_key)
        hint = None
        if env_key:
            hint = f"env:{_mask(env_key)}"
        elif key:
            hint = f"ui:{_mask(key)}"
        cfg = configs.get(sid) or {}
        primary = sid in PRIMARY_SLOT_IDS
        out.append(
            LlmSlotStatus(
                id=sid,
                label=meta["label"],
                kind=meta["kind"],  # type: ignore[arg-type]
                configured=configured,
                hint=hint,
                model=cfg.get("model") or "",
                base_url=cfg.get("base_url") or "",
                default_model=meta["default_model"],
                default_base_url=meta["default_base_url"],
                primary=primary,
                removable=not primary,
            )
        )
    return out


def _catalog() -> list[LlmModelInfo]:
    return [
        LlmModelInfo(
            id=slot.id,
            label=slot.label,
            provider="slot",
            kind=slot.kind,
            requires_key=slot.id,
        )
        for slot in _slot_status()
    ]


def _normalize_binding(value: str, *, allowed: set[str], fallback: str) -> str:
    v = (value or "").strip()
    legacy = {
        "default": "chat_a",
        "planner": "chat_a",
        "strong": "chat_a",
        "researcher": "chat_b",
        "plc": "chat_b",
        "writer": "chat_c",
        "openai-gpt-4o-mini": "chat_a",
        "openai-gpt-4o": "chat_a",
        "openai-custom": "chat_a",
        "anthropic-claude-sonnet": "chat_b",
        "deepseek-chat": "chat_b",
        "qwen-plus": "chat_c",
        "qwen-max": "chat_c",
        "gemini-2.0-flash": "chat_b",
        "local": "chat_c",
        "ollama-qwen": "chat_c",
        "ollama-custom": "chat_c",
    }
    if v in legacy:
        v = legacy[v]
    if v not in allowed:
        return fallback
    return v


def load_agent_bindings() -> LlmAgentBinding:
    data, _keys, _configs, enabled = _load_live_state()
    agents = data.get("agents") or {}
    enabled_set = set(enabled)
    chat_allowed = (CHAT_SLOT_IDS & enabled_set) or CHAT_SLOT_IDS
    embed_allowed = (EMBED_SLOT_IDS & enabled_set) or EMBED_SLOT_IDS
    rerank_allowed = (RERANK_SLOT_IDS & enabled_set) or RERANK_SLOT_IDS
    return LlmAgentBinding(
        research=_normalize_binding(str(agents.get("research") or "chat_a"), allowed=chat_allowed, fallback="chat_a"),
        planner=_normalize_binding(str(agents.get("planner") or "chat_a"), allowed=chat_allowed, fallback="chat_a"),
        researcher=_normalize_binding(
            str(agents.get("researcher") or "chat_a"), allowed=chat_allowed, fallback="chat_a"
        ),
        writer=_normalize_binding(str(agents.get("writer") or "chat_a"), allowed=chat_allowed, fallback="chat_a"),
        plc=_normalize_binding(str(agents.get("plc") or "chat_a"), allowed=chat_allowed, fallback="chat_a"),
        embed=_normalize_binding(str(agents.get("embed") or "embed"), allowed=embed_allowed, fallback="embed"),
        rerank=_normalize_binding(str(agents.get("rerank") or "rerank"), allowed=rerank_allowed, fallback="rerank"),
    )


def get_llm_settings() -> LlmSettingsResponse:
    settings = get_settings()
    bindings = load_agent_bindings()
    slots = _slot_status()
    return LlmSettingsResponse(
        catalog=_catalog(),
        agents=bindings,
        slots=slots,
        providers=slots,
        litellm_base_url=settings.litellm_base_url,
        default_model="chat_a",
        notes=[
            "默认各 1 个对话 / 向量 / 召回模型；点添加再增加（每类最多 3 个）。",
            "每个槽位配置 API Key、Model、Base URL。",
            "保存后生成 litellm_providers.generated.yaml，需重启 LiteLLM。",
        ],
    )


def _merge_slot_updates(
    configs: dict[str, dict[str, str]],
    keys: dict[str, str],
    updates: dict[str, LlmSlotUpdate | dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    for sid, upd in updates.items():
        if sid not in VALID_SLOT_IDS:
            raise ValueError(f"Unknown slot: {sid}")
        if not isinstance(upd, LlmSlotUpdate):
            upd = LlmSlotUpdate.model_validate(upd)
        row = dict(configs.get(sid) or {})
        if upd.model is not None:
            row["model"] = upd.model.strip() or _SLOT_META[sid]["default_model"]
        if upd.base_url is not None:
            cleaned = upd.base_url.strip()
            if _SLOT_META[sid]["kind"] in {"chat", "embed"} and cleaned:
                cleaned = _normalize_openai_compatible_base(cleaned)
            row["base_url"] = cleaned
        configs[sid] = {
            "model": row.get("model") or _SLOT_META[sid]["default_model"],
            "base_url": row.get("base_url", _SLOT_META[sid]["default_base_url"]),
        }
        if upd.api_key is not None:
            key = upd.api_key.strip()
            if not key:
                keys.pop(sid, None)
            else:
                keys[sid] = key
    return configs, keys


def _write_slot_state(keys: dict[str, str], configs: dict[str, dict[str, str]]) -> None:
    keys_path = _keys_path()
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")
    _slots_path().write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_runtime_artifacts(keys, configs)


def _persist_tested_slot(
    slot_id: str,
    *,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
) -> None:
    """Keep a connectivity-tested draft so refresh/load still has URL/model/key."""
    upd = LlmSlotUpdate(
        api_key=(api_key or "").strip() or None,
        model=(model or "").strip() or None,
        base_url=(base_url or "").strip() or None,
    )
    if upd.api_key is None and upd.model is None and upd.base_url is None:
        return
    configs = _load_slot_configs()
    keys = _migrate_legacy_keys(_load_json(_keys_path()))
    configs, keys = _merge_slot_updates(configs, keys, {slot_id: upd})
    _write_slot_state(keys, configs)
    logger.info("LLM slot persisted after connectivity test slot=%s", slot_id)


def update_llm_settings(body: LlmSettingsUpdate) -> LlmSettingsResponse:
    path = _settings_path()
    data = _load_json(path)
    configs = _load_slot_configs()
    keys = _migrate_legacy_keys(_load_json(_keys_path()))
    enabled = _load_enabled_slots(data=data, keys=keys)
    data, keys, configs, enabled, _changed = _compact_unconfigured_primary(
        data, keys, configs, enabled
    )

    if body.add_slot:
        spare = _next_spare_slot(body.add_slot, enabled)
        if not spare:
            raise ValueError(f"{body.add_slot} 最多 {MAX_SLOTS_PER_KIND} 个")
        enabled.append(spare)
        configs[spare] = {"model": "", "base_url": ""}

    updates = body.slots or body.providers
    if body.provider_keys:
        for sid, key in body.provider_keys.items():
            if sid not in VALID_SLOT_IDS:
                # ignore unknown legacy vendor ids quietly for chat_a map
                if sid in {"openai", "anthropic", "deepseek", "dashscope", "gemini"}:
                    keys["chat_a"] = (key or "").strip() or keys.get("chat_a", "")
                    if not keys["chat_a"]:
                        keys.pop("chat_a", None)
                continue
            key = (key or "").strip()
            if not key:
                keys.pop(sid, None)
            else:
                keys[sid] = key
                if sid not in enabled:
                    enabled.append(sid)

    if updates:
        for sid in updates:
            if sid not in VALID_SLOT_IDS:
                raise ValueError(f"Unknown slot: {sid}")
            if sid not in enabled:
                enabled.append(sid)
        configs, keys = _merge_slot_updates(configs, keys, updates)

    if body.remove_slot:
        sid = body.remove_slot.strip()
        if sid not in VALID_SLOT_IDS:
            raise ValueError(f"Unknown slot: {sid}")
        if sid in PRIMARY_SLOT_IDS:
            raise ValueError("默认模型不能删除")
        enabled = [x for x in enabled if x != sid]
        keys.pop(sid, None)
        configs[sid] = {"model": "", "base_url": ""}
        fallback = _primary_of_kind(_SLOT_META[sid]["kind"])
        agents_map = dict(data.get("agents") or {})
        for role, mid in list(agents_map.items()):
            if mid == sid:
                agents_map[role] = fallback
        if agents_map:
            data["agents"] = agents_map

    if body.agents is not None:
        agents = body.agents.model_dump()
        for role, mid in agents.items():
            allowed = VALID_SLOT_IDS
            fallback = "chat_a" if role not in {"embed", "rerank"} else role
            mid = _normalize_binding(mid, allowed=allowed, fallback=fallback)
            agents[role] = mid
            if mid in VALID_SLOT_IDS and mid not in enabled:
                enabled.append(mid)
        data["agents"] = agents

    data, keys, configs, enabled, _folded = _compact_unconfigured_primary(
        data, keys, configs, enabled
    )
    data["enabled_slots"] = _order_enabled(enabled)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    _write_slot_state(keys, configs)
    logger.info("LLM slots updated path=%s enabled=%s", _slots_path(), data["enabled_slots"])
    return get_llm_settings()


def resolve_model_profile(explicit: str | None = None) -> str:
    if explicit and explicit.strip() and explicit.strip() not in {"default", ""}:
        normalized = _normalize_binding(
            explicit.strip(),
            allowed=VALID_SLOT_IDS | CHAT_SLOT_IDS,
            fallback="chat_a",
        )
        return normalized
    return load_agent_bindings().research


def _normalize_openai_compatible_base(base_url: str) -> str:
    """Normalize provider root so `/chat/completions` can be appended.

    DeepSeek docs often give ``https://api.deepseek.com`` (no ``/v1``).
    OpenAI-style clients expect ``…/v1/chat/completions``.
    """
    b = (base_url or "").strip().rstrip("/")
    if not b:
        return b
    lower = b.lower()
    for suffix in (
        "/chat/completions",
        "/embeddings",
        "/rerank",
        "/completions",
        "/models",
    ):
        if lower.endswith(suffix):
            b = b[: -len(suffix)].rstrip("/")
            lower = b.lower()
            break
    # Azure OpenAI uses deployment paths — leave alone
    if "openai.azure.com" in lower:
        return b
    # Already versioned (…/v1, …/v1beta, …/openai/v1)
    while lower.endswith("/v1/v1"):
        b = b[: -3].rstrip("/")
        lower = b.lower()
    if lower.endswith("/v1"):
        return b
    if "/v1/" in lower or lower.endswith("/v1beta") or "/v1beta" in lower:
        return b
    return f"{b}/v1"


def _chat_completion_urls(base: str) -> list[str]:
    """Ordered candidates for OpenAI-compatible chat completions."""
    root = _normalize_openai_compatible_base(base)
    urls = [f"{root}/chat/completions"]
    raw = (base or "").strip().rstrip("/")
    if raw:
        alt = f"{raw}/chat/completions"
        if alt not in urls:
            urls.append(alt)
    return urls


def _ipv4_http_client() -> "httpx.Client":
    import httpx

    # Prefer IPv4 on Windows where IPv6 getaddrinfo often fails for CDN CNAMEs
    try:
        return httpx.Client(
            timeout=20.0,
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )
    except Exception:  # noqa: BLE001
        return httpx.Client(timeout=20.0)


_DNS_A_CACHE: dict[str, str] = {}


def _resolve_ipv4(host: str, *, tries: int = 5) -> str | None:
    import socket
    import time

    cached = _DNS_A_CACHE.get(host)
    if cached:
        return cached

    last: OSError | None = None
    for i in range(max(1, tries)):
        # UDP DNS first — Windows getaddrinfo is intermittently broken for some CNAMEs
        ip = _dns_udp_a_record(host)
        if ip:
            _DNS_A_CACHE[host] = ip
            return ip
        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
            if infos:
                ip = str(infos[0][4][0])
                _DNS_A_CACHE[host] = ip
                return ip
        except OSError as exc:
            last = exc
            time.sleep(0.05 * (i + 1))
    _ = last
    return None


def _dns_udp_a_record(host: str) -> str | None:
    """Minimal DNS A lookup over UDP (bypasses flaky Windows getaddrinfo)."""
    import random
    import socket
    import struct

    name = (host or "").strip().rstrip(".").lower()
    if not name or any(c.isspace() for c in name):
        return None

    def _encode_name(n: str) -> bytes:
        out = bytearray()
        for label in n.split("."):
            raw = label.encode("idna")
            if not raw or len(raw) > 63:
                raise ValueError("bad label")
            out.append(len(raw))
            out.extend(raw)
        out.append(0)
        return bytes(out)

    try:
        qname = _encode_name(name)
    except Exception:  # noqa: BLE001
        return None

    # Prefer env override, then public resolvers (avoid relying on flaky OS DnsClient)
    servers = [
        os.getenv("ROS_DNS_SERVER", "").strip(),
        "223.5.5.5",
        "8.8.8.8",
        "1.1.1.1",
    ]
    txid = random.randint(0, 65535)
    header = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    question = qname + struct.pack("!HH", 1, 1)  # A IN
    packet = header + question

    for server in servers:
        if not server:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1.2)
                sock.sendto(packet, (server, 53))
                data, _addr = sock.recvfrom(512)
        except OSError:
            continue
        if len(data) < 12:
            continue
        r_txid, flags, _qd, an_count, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
        if r_txid != txid or an_count <= 0 or (flags & 0x000F) != 0:
            continue
        # Skip question
        i = 12
        try:
            while i < len(data) and data[i] != 0:
                if data[i] & 0xC0 == 0xC0:
                    i += 2
                    break
                i += 1 + data[i]
            else:
                i += 1
            i += 4  # qtype+qclass
            for _ in range(an_count):
                if i >= len(data):
                    break
                if data[i] & 0xC0 == 0xC0:
                    i += 2
                else:
                    while i < len(data) and data[i] != 0:
                        i += 1 + data[i]
                    i += 1
                if i + 10 > len(data):
                    break
                rtype, _rclass, _ttl, rdlength = struct.unpack("!HHIH", data[i : i + 10])
                i += 10
                if rtype == 1 and rdlength == 4 and i + 4 <= len(data):
                    return socket.inet_ntoa(data[i : i + 4])
                i += rdlength
        except Exception:  # noqa: BLE001
            continue
    return None


def _request_via_ipv4_ip(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
) -> Any:
    """Connect using resolved A-record IP while keeping TLS SNI as the hostname."""
    import http.client
    import json as _json
    import socket
    import ssl
    from urllib.parse import urlparse

    import httpx

    parsed = urlparse(url)
    host = parsed.hostname or ""
    ip = _resolve_ipv4(host) if host else None
    if not ip or not host:
        raise httpx.ConnectError(f"IPv4 resolve failed for {host or url}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    body = None if json_body is None else _json.dumps(json_body).encode("utf-8")
    hdrs = {str(k): str(v) for k, v in headers.items()}
    hdrs.setdefault("Host", host)
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["Content-Length"] = str(len(body))

    class _HTTPS(http.client.HTTPSConnection):
        def connect(self) -> None:  # noqa: ANN202
            sock = socket.create_connection((ip, port), self.timeout)
            context = self._context or ssl.create_default_context()
            self.sock = context.wrap_socket(sock, server_hostname=host)

    if parsed.scheme == "https":
        conn: http.client.HTTPConnection = _HTTPS(host, port=port, timeout=20.0)
    else:
        conn = http.client.HTTPConnection(ip, port=port, timeout=20.0)

    try:
        conn.request(method.upper(), path, body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        body_text = raw.decode("utf-8", errors="replace")
        return httpx.Response(
            status_code=int(resp.status),
            content=body_text.encode("utf-8"),
            request=httpx.Request(method.upper(), url),
        )
    finally:
        conn.close()


def _request_with_dns_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any] | None = None,
    attempts: int = 3,
) -> Any:
    """POST/GET with retries; on ConnectError use IPv4 literal + proper TLS SNI."""
    import time

    import httpx

    last_exc: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            with _ipv4_http_client() as client:
                return client.request(method, url, headers=headers, json=json_body)
        except httpx.ConnectError as exc:
            last_exc = exc
            try:
                return _request_via_ipv4_ip(
                    method, url, headers=headers, json_body=json_body
                )
            except Exception as exc2:  # noqa: BLE001
                last_exc = exc2
            time.sleep(0.1 * (i + 1))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break

    if last_exc:
        raise last_exc
    raise RuntimeError(f"request failed: {url}")


def test_llm_slot(
    slot_id: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Probe a slot with a minimal chat/embed request (does not require LiteLLM)."""
    import time

    import httpx

    sid = (slot_id or "").strip()
    if sid not in VALID_SLOT_IDS:
        raise ValueError(f"Unknown slot id: {sid}")
    meta = _SLOT_META[sid]
    kind = meta["kind"]
    configs = _load_slot_configs()
    keys = _migrate_legacy_keys(_load_json(_keys_path()))

    key = (api_key or "").strip() or keys.get(sid) or ""
    if not key:
        # Fall back to common env keys for chat slots
        if sid in CHAT_SLOT_IDS:
            key = (
                os.getenv(f"ROS_LLM_{sid.upper()}_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY")
                or os.getenv("DASHSCOPE_API_KEY")
                or ""
            ).strip()
        elif sid in EMBED_SLOT_IDS:
            key = (
                os.getenv(f"ROS_LLM_{sid.upper()}_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
            ).strip()

    mdl = (model or "").strip() or configs[sid]["model"] or meta["default_model"]
    raw_base = (base_url or "").strip() or configs[sid]["base_url"] or meta["default_base_url"]
    base = _normalize_openai_compatible_base(raw_base) if kind in {"chat", "embed"} else raw_base.rstrip("/")

    if not base:
        return {
            "ok": False,
            "slot_id": sid,
            "kind": kind,
            "model": mdl,
            "base_url": base,
            "latency_ms": 0,
            "message": "未配置 Base URL",
            "detail": None,
        }
    if not key and "localhost" not in base and "127.0.0.1" not in base:
        return {
            "ok": False,
            "slot_id": sid,
            "kind": kind,
            "model": mdl,
            "base_url": base,
            "latency_ms": 0,
            "message": "未配置 API Key（本地地址可无 Key）",
            "detail": None,
        }

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    t0 = time.perf_counter()
    try:
        if kind == "chat":
            payload = {
                "model": mdl,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            }
            res = None
            last_url = ""
            for url in _chat_completion_urls(raw_base):
                last_url = url
                res = _request_with_dns_retry(
                    "POST", url, headers=headers, json_body=payload
                )
                # 404 usually means missing /v1 — try next candidate
                if res.status_code != 404:
                    break
            assert res is not None
        elif kind == "embed":
            last_url = f"{base}/embeddings"
            res = _request_with_dns_retry(
                "POST",
                last_url,
                headers=headers,
                json_body={"model": mdl, "input": "researchos connectivity probe"},
            )
        else:
            payload = {
                "model": mdl,
                "query": "ping",
                "documents": ["researchos"],
                "top_n": 1,
            }
            last_url = f"{base.rstrip('/')}/rerank"
            res = _request_with_dns_retry(
                "POST", last_url, headers=headers, json_body=payload
            )
            if res.status_code >= 400:
                alt = f"{base.rstrip('/')}/v1/rerank"
                if alt != last_url:
                    last_url = alt
                    res = _request_with_dns_retry(
                        "POST", alt, headers=headers, json_body=payload
                    )
        ms = int((time.perf_counter() - t0) * 1000)
        body_preview = (res.text or "")[:240]
        detail = f"{last_url} · {body_preview}" if body_preview else last_url
        if res.status_code < 400:
            try:
                _persist_tested_slot(sid, api_key=api_key, model=model, base_url=base_url)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist successful llm slot test slot=%s", sid)
            return {
                "ok": True,
                "slot_id": sid,
                "kind": kind,
                "model": mdl,
                "base_url": base,
                "latency_ms": ms,
                "message": f"联通成功（HTTP {res.status_code}，{ms} ms）",
                "detail": detail,
            }
        return {
            "ok": False,
            "slot_id": sid,
            "kind": kind,
            "model": mdl,
            "base_url": base,
            "latency_ms": ms,
            "message": f"联通失败（HTTP {res.status_code}）",
            "detail": detail,
        }
    except Exception as exc:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        err = str(exc)
        hint = ""
        low = err.lower()
        if "getaddrinfo" in low or "name or service not known" in low or "nodename" in low:
            hint = "（DNS 解析失败：请检查本机/容器能否解析该 Base URL 主机名）"
        elif "connect" in low or "timed out" in low:
            hint = "（网络连不上：检查代理、防火墙或 Base URL）"
        return {
            "ok": False,
            "slot_id": sid,
            "kind": kind,
            "model": mdl,
            "base_url": base,
            "latency_ms": ms,
            "message": f"联通失败：{type(exc).__name__}{hint}",
            "detail": err[:400],
        }
