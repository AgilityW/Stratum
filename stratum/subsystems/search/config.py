"""Search configuration — loads engine/routing/curation from ProjectSpace config.yaml.

ProjectSpace puts engine config in config.yaml (engines: section),
not domain.yaml. This adapter bridges to the search subsystem.
"""

import os
from typing import Any

import yaml


def _load_config_yaml(workspace: str) -> dict:
    path = os.path.join(workspace, "config.yaml")
    with open(path) as f:
        raw = f.read()
    # Resolve ${VAR} placeholders
    for var in ["BOCHA_API_KEY", "TAVILY_API_KEY", "DEEPSEEK_API_KEY"]:
        raw = raw.replace(f"${{{var}}}", os.environ.get(var, ""))
    return yaml.safe_load(raw)


def _load_domain_yaml(domain: str, workspace: str) -> dict:
    path = os.path.join(workspace, "domains", domain, "domain.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def load_api_keys() -> dict[str, str]:
    """Load engine API keys from environment."""
    return {
        "bocha": os.environ.get("BOCHA_API_KEY", ""),
        "tavily": os.environ.get("TAVILY_API_KEY", ""),
    }


def load_search_config(domain: str, workspace: str) -> dict[str, Any]:
    """Build search subsystem config from ProjectSpace config.yaml + domain.yaml."""
    cfg = _load_config_yaml(workspace)
    domain_cfg = _load_domain_yaml(domain, workspace)

    # ── Routing: locale → [engine priorities]
    # config.yaml engines.{name}.languages maps languages to engines
    # Build reverse map: locale → [engine_names in priority order]
    routing: dict[str, list[str]] = {}
    engines_raw = cfg.get("engines", {})
    for engine_name, engine_cfg in engines_raw.items():
        for lang in engine_cfg.get("languages", []):
            routing.setdefault(lang, []).append(engine_name)

    # Ensure all source_languages have at least tavily fallback
    for lang in cfg.get("source_languages", []):
        if lang not in routing:
            routing[lang] = ["tavily"]

    # Expand umbrella tags (zh → zh-CN, zh-TW) — MERGE don't overwrite
    locale_map = cfg.get("locales", {"zh": ["zh-CN", "zh-TW"]})
    expanded = {}
    for loc, engines in routing.items():
        if loc in locale_map:
            for sub in locale_map[loc]:
                if sub not in expanded:
                    expanded[sub] = engines
                else:
                    # Merge: prepend new engines, avoid duplicates
                    existing = expanded[sub]
                    for e in engines:
                        if e not in existing:
                            existing.append(e)
        else:
            if loc not in expanded:
                expanded[loc] = engines
    routing = expanded

    # ── Engine configs → subsystem format
    engine_configs = {}
    for name, ecfg in engines_raw.items():
        engine_configs[name] = {
            "max_rps": ecfg.get("max_rps", 3),
            "max_retries": ecfg.get("max_retries", 2),
            "backoff_base": ecfg.get("backoff_base", 1.0),
            "freshness": ecfg.get("freshness", {}).get("day", "oneDay") if isinstance(ecfg.get("freshness"), dict) else "oneDay",
            "count": ecfg.get("count", 10),
            "search_depth": (ecfg.get("extra", {}).get("search_depth", "advanced") if isinstance(ecfg.get("extra"), dict) else "advanced"),
            "max_results": ecfg.get("max_results", 10),
            "include_domains": ecfg.get("include_domains", {}),
        }

    # ── Source classification from domain.yaml
    classifications = {}
    for comp in domain_cfg.get("companies", []):
        aliases = comp.get("aliases", {})
        for loc, name in aliases.items():
            classifications.setdefault("company", []).append(name)
    if "sources" in domain_cfg:
        for src_type, domains in domain_cfg.get("sources", {}).get("classification", {}).items():
            classifications.setdefault(src_type, []).extend(domains)

    # ── Curation: normalize entities from ProjectSpace aliases format
    entities_normalized = []
    for comp in domain_cfg.get("companies", []):
        aliases = comp.get("aliases", {})
        entity = {
            "id": comp["id"],
            "type": comp.get("type", "COMPANY"),
            "name_en": aliases.get("en", comp["id"]),
            "name_zh": aliases.get("zh-CN", comp["id"]),
        }
        entities_normalized.append(entity)

    terms_normalized = []
    for t in domain_cfg.get("terms", []):
        t_aliases = t.get("aliases", {})
        terms_normalized.append({
            "id": t["id"],
            "type": t.get("type", "TECHNOLOGY"),
            "name_en": t_aliases.get("en", t["id"]),
        })

    # ── Curation settings
    curation = cfg.get("curation", {})
    source_weights = curation.get("source_weights", {
        "official": 1.0,
        "analyst": 0.8,
        "media": 0.6,
        "blog": 0.3,
    })

    return {
        "routing": routing,
        "engines": engine_configs,
        "source_weights": source_weights,
        "max_per_locale": curation.get("max_per_locale", 30),
        "max_per_source": curation.get("max_per_source", 3),
        "total_cap": curation.get("total_cap", 200),
        "classifications": classifications,
        "entities": entities_normalized,
        "terms": terms_normalized,
    }
