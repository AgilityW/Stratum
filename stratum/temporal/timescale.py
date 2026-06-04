"""DB-native temporal runner for weekly/monthly/quarterly/yearly reports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import yaml

from stratum.contracts.report_window import resolve_report_window
from stratum.temporal.exploring import run_exploring
from stratum.temporal.integration import Integration
from stratum.temporal.profiles import get_timescale_profile


WriteManifest = Callable[[str, str, str, str, list[dict], dict, dict | None, dict | None], dict]


class RunStage(Protocol):
    def __call__(
        self,
        stage_name: str,
        stage_args: list[str],
        step_label: str,
        timeout: int = 120,
    ) -> bool:
        ...


@dataclass(frozen=True)
class TemporalServices:
    """External services injected by the CLI orchestration layer."""

    run_stage: RunStage
    write_manifest: WriteManifest
    domains_dir: str


def run_higher_scale_output(
    domain_id: str,
    timescale: str,
    period: str,
    paths: dict[str, str],
    runtime: dict[str, Any],
    pipeline_status: list[dict],
    record: Callable[[str, str, str | None, str | None], None],
    fail: Callable[[str, str | None, str | None], None],
    services: TemporalServices,
    *,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Generate a higher-scale report from DB cascade state and render it."""
    from stratum.db.service import get_report_context
    from stratum.db.synthesis import synthesize_cascade_report

    profile = get_timescale_profile(timescale)
    report_window = resolve_report_window(
        timescale,
        period,
        start_date=window_start,
        end_date=window_end,
    )
    period = report_window.period

    exploring = run_exploring(
        domain_id,
        timescale,
        period,
        report_window,
        paths,
        paths["config"],
        paths.get("db_dir", ""),
        services,
        record,
    )

    try:
        integration = Integration()
        include_same_scale_fresh = integration.include_same_scale_fresh(
            timescale,
            exploring,
        )
        synthesis = synthesize_cascade_report(
            domain_id,
            timescale,
            period,
            window_start=window_start,
            window_end=window_end,
            include_same_scale_fresh=include_same_scale_fresh,
        )
        integration_decision = integration.decide(
            timescale,
            exploring,
            db_memory={
                "source_reports": synthesis.get("source_reports", 0),
                "source_events": synthesis.get("source_events", 0),
            },
        ).to_dict()
    except Exception as exc:
        fail("db_synthesis", paths.get("briefing_md"), str(exc))
    record("db_synthesis", "success", paths.get("briefing_md"), f"report_id={synthesis['report_id']}")

    context = get_report_context(
        domain_id,
        timescale,
        period,
        window_start=window_start,
        window_end=window_end,
    )
    title = briefing_title(domain_id, timescale, paths["domain_config"])
    period_label = report_period_label(report_window)
    markdown = render_db_report_markdown(domain_id, title, period_label, context)
    os.makedirs(paths["data_dir"], exist_ok=True)
    with open(paths["briefing_md"], "w") as f:
        f.write(markdown)
    record("markdown", "success", paths["briefing_md"], "db_native_synthesis")

    artifact_name = os.path.splitext(os.path.basename(paths["briefing_html"]))[0]
    if services.run_stage(
        "render",
        [
            "--input",
            paths["briefing_md"],
            "--output-dir",
            paths["data_dir"],
            "--title",
            title,
            "--domain",
            paths["domain_config"],
            "--domain-id",
            domain_id,
            "--briefing-type",
            timescale,
            "--artifact-name",
            artifact_name,
            "--date",
            period_label,
            "--footer",
            briefing_footer(timescale),
            "--template",
            briefing_template_path(services.domains_dir, domain_id, profile.template_name),
        ],
        f"Render {timescale} HTML + PDF",
    ):
        record("render", "success", paths["briefing_html"], None)
    else:
        record("render", "failed_nonblocking", paths["briefing_html"], None)

    summary = {
        "timescale": timescale,
        "period": period,
        "window": report_window.to_dict(),
        "profile": {
            "stage_order": list(profile.stage_order),
            "consumes_lower_scales": profile.consumes_lower_scales,
            "consumes_same_scale_fresh_evidence": profile.consumes_same_scale_fresh_evidence,
            "synthesis_policy_profile": profile.synthesis_policy_profile,
        },
        "report_id": synthesis["report_id"],
        "source_scale": synthesis["source_scale"],
        "source_scales": synthesis.get("source_scales", [synthesis["source_scale"]]),
        "source_reports": synthesis["source_reports"],
        "source_events": synthesis["source_events"],
        "fresh_evidence": synthesis.get("fresh_evidence", 0),
        "exploring": exploring,
        "integration": integration_decision,
        "synthesized_events": synthesis["synthesized_events"],
        "items": len(context.get("items", [])),
    }
    services.write_manifest(
        paths["run_manifest"],
        domain_id,
        period,
        "ok",
        pipeline_status,
        paths,
        summary,
        runtime,
    )
    return {
        "status": "ok",
        "domain": domain_id,
        "timescale": timescale,
        "period": period,
        "summary": summary,
        "runtime": runtime,
        "paths": {k: v for k, v in paths.items()},
    }


def briefing_title(domain_id: str, timescale: str, domain_config_path: str | None = None) -> str:
    profile = get_timescale_profile(timescale)
    base = domain_channel_title(domain_config_path) if domain_config_path else domain_id
    if timescale == "daily":
        return base
    for suffix in ("早报", "日报", "简报"):
        if base.endswith(suffix):
            return base[: -len(suffix)] + profile.label_zh
    return f"{base} {profile.label_zh}"


def domain_channel_title(domain_config_path: str) -> str:
    try:
        with open(domain_config_path) as f:
            domain_cfg = yaml.safe_load(f) or {}
        return domain_cfg.get("domain", {}).get("title", "Briefing")
    except Exception:
        return "Briefing"


def briefing_template_path(domains_dir: str, domain_id: str, template_name: str) -> str:
    template = os.path.join(domains_dir, domain_id, "templates", template_name)
    if os.path.exists(template):
        return template
    return os.path.join(domains_dir, domain_id, "templates", "daily.html")


def report_period_label(report_window) -> str:
    """Return a user-facing period label for a report window."""
    if report_window.period_kind == "custom_range":
        return report_window.label
    if report_window.scale in {"weekly", "monthly", "quarterly", "yearly"}:
        return f"{report_window.period}（{report_window.start_date} 至 {report_window.end_date}）"
    return report_window.label


def briefing_footer(timescale: str) -> str:
    profile = get_timescale_profile(timescale)
    return f"由 AI Agent 自动生成 · {profile.cadence_zh}更新"


def render_db_report_markdown(domain_id: str, title: str, period: str, context: dict[str, Any]) -> str:
    from stratum.db.service import get_report_item_evidence

    sections = context.get("sections", [])
    items = context.get("items", [])
    section_by_id = {section.get("id"): section for section in sections}
    lines = [f"# {title}", "", f"## {period}", ""]
    if not context.get("report"):
        lines.extend(["暂无结构化报告。", ""])
        return "\n".join(lines).strip() + "\n"

    current_section_id = None
    for item in items:
        section = section_by_id.get(item.get("section_id"), {})
        section_id = item.get("section_id")
        if section_id != current_section_id:
            current_section_id = section_id
            section_title = section.get("title") or item.get("section_key") or "综合"
            lines.extend([f"## {section_title}", ""])
        lines.extend([f"### {item.get('title', '').strip()}", ""])
        body = str(item.get("body") or "").strip()
        if body:
            lines.extend([body, ""])
        source_line = report_item_source_line(domain_id, item.get("id"), get_report_item_evidence)
        if source_line:
            lines.extend([source_line, ""])
    return "\n".join(lines).strip() + "\n"


def report_item_source_line(
    domain_id: str,
    item_id: str | None,
    evidence_loader: Callable[[str, str], dict[str, Any]],
) -> str:
    """Render a concise citation line for one DB-native report item."""
    if not item_id:
        return ""
    evidence = evidence_loader(domain_id, item_id)
    articles = evidence.get("articles", [])
    if not articles:
        return ""
    sources = []
    dates = []
    for article in articles[:4]:
        source = article.get("source") or article.get("source_domain") or "source"
        date = article.get("published_at") or article.get("run_date") or ""
        if source not in sources:
            sources.append(source)
        if date and date not in dates:
            dates.append(date)
    source_text = ", ".join(sources)
    date_text = ", ".join(dates)
    if date_text:
        return f"*{source_text} · {date_text}*"
    return f"*{source_text}*"
