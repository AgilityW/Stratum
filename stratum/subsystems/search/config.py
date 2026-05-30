"""Search configuration — loads engine/routing/curation from ProjectSpace config.yaml.

ProjectSpace puts engine config in config.yaml (engines: section),
not domain.yaml. This adapter bridges to the search subsystem.
"""

import os
from typing import Any, Optional

import yaml


def _load_env_file(config_dir: str) -> None:
    """Load KEY=VALUE lines from config directory .env without overriding the environment."""
    env_path = os.path.join(config_dir, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _load_config_yaml(workspace: str, config_path: Optional[str] = None) -> dict:
    path = config_path or os.path.join(workspace, "config.yaml")
    _load_env_file(os.path.dirname(os.path.abspath(path)))
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


def _unique_values(values) -> list[str]:
    """Return non-empty string values in first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def load_search_config(
    domain: str,
    workspace: str,
    config_path: Optional[str] = None,
) -> dict[str, Any]:
    """Build search subsystem config from the selected config YAML + domain.yaml."""
    cfg = _load_config_yaml(workspace, config_path)
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
        extra = ecfg.get("extra", {}) if isinstance(ecfg.get("extra"), dict) else {}
        engine_configs[name] = {
            "max_rps": ecfg.get("max_rps", 3),
            "max_retries": ecfg.get("max_retries", 2),
            "backoff_base": ecfg.get("backoff_base", 1.0),
            "freshness": ecfg.get("freshness", {}).get("day", "oneDay") if isinstance(ecfg.get("freshness"), dict) else "oneDay",
            "count": ecfg.get("count", 10),
            "search_depth": extra.get("search_depth", "advanced"),
            "topic": extra.get("topic", "news"),
            "topic_by_intent": extra.get("topic_by_intent", {}),
            "topic_by_dimension": extra.get("topic_by_dimension", {}),
            "max_results": ecfg.get("max_results", 10),
            "include_domains": ecfg.get("include_domains", {}),
        }

    # ── Source classification from domain.yaml
    # This map is consumed as source_type -> URL/domain patterns. Company
    # aliases belong to entity scoring below, not to source-type classification.
    classifications = {}
    pipeline_cfg = domain_cfg.get("pipeline", {})
    for src_type, domains in pipeline_cfg.get("source_classification", {}).items():
        classifications.setdefault(src_type, []).extend(domains)
    if "sources" in domain_cfg:
        for src_type, domains in domain_cfg.get("sources", {}).get("classification", {}).items():
            classifications.setdefault(src_type, []).extend(domains)

    # ── Curation: normalize entities from ProjectSpace aliases format
    entities_normalized = []
    for comp in domain_cfg.get("companies", []):
        aliases = comp.get("aliases", {})
        alias_values = _unique_values([comp.get("id"), *aliases.values()])
        entity = {
            "id": comp["id"],
            "type": comp.get("type", "COMPANY"),
            "name_en": aliases.get("en", comp["id"]),
            "name_zh": aliases.get("zh-CN", comp["id"]),
            "aliases": alias_values,
        }
        entities_normalized.append(entity)

    terms_normalized = []
    for t in domain_cfg.get("terms", []):
        t_aliases = t.get("aliases", {})
        alias_values = _unique_values([t.get("id"), *t_aliases.values()])
        terms_normalized.append({
            "id": t["id"],
            "type": t.get("type", "TECHNOLOGY"),
            "name_en": t_aliases.get("en", t["id"]),
            "aliases": alias_values,
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
        "min_per_source_type": curation.get("min_per_source_type", {}),
        "max_per_entity": curation.get("max_per_entity", 0),
        "classifications": classifications,
        "entities": entities_normalized,
        "terms": terms_normalized,
    }
