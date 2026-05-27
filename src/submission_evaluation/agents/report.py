from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from collections.abc import Mapping
import re
from typing import Any

from ..config import AppConfig
from ..models import LocationManifest
from .base import AgentResult, NoOpAgent

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _REPORTLAB_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised via fallback tests
    _REPORTLAB_AVAILABLE = False


def _slug(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return token or "submission"


def _risk_level(score: Any) -> tuple[str, str]:
    if not isinstance(score, (int, float)):
        return "Unknown", "gray"
    if score >= 8:
        return "Severe", "red"
    if score >= 6:
        return "High", "orange"
    if score >= 4:
        return "Moderate", "yellow"
    return "Low", "green"


def _format_score(score: Any) -> str:
    if isinstance(score, (int, float)):
        return f"{float(score):.1f}"
    return "N/A"


def _risk_color_hex(color_name: str) -> str:
    mapping = {
        "red": "#C0392B",
        "orange": "#D35400",
        "yellow": "#B7950B",
        "green": "#1E8449",
        "gray": "#5D6D7E",
    }
    return mapping.get(color_name, "#5D6D7E")


def _risk_color_cell(color_name: str):
    mapping = {
        "red": colors.HexColor("#F5B7B1") if _REPORTLAB_AVAILABLE else None,
        "orange": colors.HexColor("#FAD7A0") if _REPORTLAB_AVAILABLE else None,
        "yellow": colors.HexColor("#FCF3CF") if _REPORTLAB_AVAILABLE else None,
        "green": colors.HexColor("#D5F5E3") if _REPORTLAB_AVAILABLE else None,
        "gray": colors.HexColor("#D6DBDF") if _REPORTLAB_AVAILABLE else None,
    }
    return mapping.get(color_name, colors.HexColor("#D6DBDF") if _REPORTLAB_AVAILABLE else None)


_REPORT_TEMPLATES: dict[str, dict[str, Any]] = {
    "standard": {
        "title": "Submission Risk Report",
        "include_category_table": True,
        "include_key_factors": True,
    },
    "compact": {
        "title": "Submission Risk Report (Compact)",
        "include_category_table": False,
        "include_key_factors": False,
    },
}


class ReportAgent(NoOpAgent):
    def __init__(self, *, config: AppConfig | None = None) -> None:
        super().__init__("report")
        self._config = config or AppConfig.from_env()

    def invoke(self, payload: dict[str, Any]) -> AgentResult:
        manifest = self._extract_manifest(payload)
        if manifest is None:
            return super().invoke(payload)
        draft_only = bool(payload.get("draft_only", False))
        report_template = self._extract_template(payload)

        manifest_location_ids = [location.id for location in manifest.locations if location.id]
        report_locations = self._build_report_locations(payload=payload, manifest=manifest)
        report_location_ids = [section["location_id"] for section in report_locations]

        if report_location_ids != manifest_location_ids:
            return AgentResult(
                agent=self.name,
                status="failed",
                payload={
                    "received": dict(payload),
                    "message": "report location mismatch",
                    "manifest_location_ids": manifest_location_ids,
                    "report_location_ids": report_location_ids,
                    "location_count": manifest.count,
                },
            )

        report_data = self._build_report_data(
            payload=payload,
            manifest=manifest,
            report_locations=report_locations,
            report_template=report_template,
        )

        if draft_only:
            return AgentResult(
                agent=self.name,
                status="ok",
                payload={
                    "received": dict(payload),
                    "message": "report draft generated",
                    "format": "draft",
                    "report_path": "",
                    "pdf_path": "",
                    "markdown_fallback_path": "",
                    "fallback_used": False,
                    "render_error": "",
                    "table_of_contents": report_data["table_of_contents"],
                    "report_location_ids": report_location_ids,
                    "location_ids": report_location_ids,
                    "report_locations": report_locations,
                    "location_count": manifest.count,
                    "report_template": report_template,
                },
            )

        output_dir = self._config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        base_name = self._deterministic_base_name(manifest=manifest)
        pdf_path = output_dir / f"{base_name}.pdf"
        markdown_path = output_dir / f"{base_name}.md"

        render_format = "pdf"
        fallback_used = False
        render_error = ""
        try:
            self._render_pdf(pdf_path=pdf_path, report_data=report_data)
        except (RuntimeError, OSError, ValueError) as exc:
            fallback_used = True
            render_format = "markdown"
            render_error = str(exc)
            markdown_path.write_text(
                self._render_markdown(report_data=report_data),
                encoding="utf-8",
            )

        return AgentResult(
            agent=self.name,
            status="ok",
            payload={
                "received": dict(payload),
                "message": "report generated",
                "format": render_format,
                "report_path": str(markdown_path if fallback_used else pdf_path),
                "pdf_path": str(pdf_path),
                "markdown_fallback_path": str(markdown_path),
                "fallback_used": fallback_used,
                "render_error": render_error,
                "table_of_contents": report_data["table_of_contents"],
                "report_location_ids": report_location_ids,
                "location_ids": report_location_ids,
                "report_locations": report_locations,
                "location_count": manifest.count,
                "report_template": report_template,
            },
        )

    def _deterministic_base_name(self, *, manifest: LocationManifest) -> str:
        submission = manifest.submission_id or "submission"
        digest = sha256(f"{submission}:{manifest.manifest_hash}".encode("utf-8")).hexdigest()[:12]
        return f"report-{_slug(submission)}-{digest}"

    def _extract_scores(self, payload: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
        direct = payload.get("risk_scores_by_location")
        if isinstance(direct, Mapping):
            return {str(k): v for k, v in direct.items() if isinstance(v, Mapping)}
        return {}

    def _extract_research(self, payload: Mapping[str, Any]) -> Mapping[str, list[Mapping[str, Any]]]:
        direct = payload.get("research_results")
        if not isinstance(direct, Mapping):
            return {}
        return {
            str(k): [entry for entry in v if isinstance(entry, Mapping)]
            for k, v in direct.items()
            if isinstance(v, list)
        }

    def _extract_company_research(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        direct = payload.get("company_research")
        if isinstance(direct, Mapping):
            return direct
        return {}

    def _extract_audit_entries(self, payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        entries = payload.get("audit_entries")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, Mapping)]
        return []

    def _extract_template(self, payload: Mapping[str, Any]) -> str:
        raw_template = payload.get("report_template")
        if isinstance(raw_template, str):
            selected = raw_template.strip().lower()
            if selected in _REPORT_TEMPLATES:
                return selected
        return "standard"

    def _build_report_locations(
        self,
        *,
        payload: Mapping[str, Any],
        manifest: LocationManifest,
    ) -> list[dict[str, Any]]:
        scores_by_location = self._extract_scores(payload)
        research_by_location = self._extract_research(payload)
        report_locations: list[dict[str, Any]] = []

        for location in manifest.locations:
            location_id = location.id or ""
            score_details = scores_by_location.get(location_id, {})
            overall_score = score_details.get("overall_score", "N/A")
            level, color = _risk_level(overall_score)

            categories = score_details.get("category_scores")
            category_scores = categories if isinstance(categories, Mapping) else {}
            key_factors = [
                f"{name.replace('_', ' ').title()}: {details.get('rationale', 'no rationale')}"
                for name, details in category_scores.items()
                if isinstance(details, Mapping)
            ][:5]
            if not key_factors:
                key_factors = ["Risk factors unavailable; insufficient scoring inputs."]

            research_entries = research_by_location.get(location_id, [])
            citations: list[str] = []
            climate_outlook = "10-year climate outlook unavailable from sources."
            for entry in research_entries:
                urls = entry.get("source_urls")
                if isinstance(urls, list):
                    citations.extend(str(url) for url in urls if str(url).strip())
                if entry.get("risk_category") == "climate_projection_10y" and entry.get("findings"):
                    climate_outlook = str(entry["findings"])

            citations = sorted({url.strip() for url in citations if url.strip()})
            if not citations:
                citations = ["No public source available"]
            narrative = str(score_details.get("overall_rationale", "Analysis narrative unavailable."))
            if narrative.strip() == "":
                narrative = "Analysis narrative unavailable."

            report_locations.append(
                {
                    "location_id": location_id,
                    "location_name": location.location_name or location.address_line_1 or location_id,
                    "overall_score": overall_score,
                    "risk_level": level,
                    "risk_color": color,
                    "category_scores": dict(category_scores),
                    "analysis_narrative": narrative,
                    "key_factors": key_factors,
                    "citations": citations,
                    "climate_outlook_10y": climate_outlook,
                }
            )

        return report_locations

    def _build_report_data(
        self,
        *,
        payload: Mapping[str, Any],
        manifest: LocationManifest,
        report_locations: list[dict[str, Any]],
        report_template: str,
    ) -> dict[str, Any]:
        company_research = self._extract_company_research(payload)
        company_name = str(company_research.get("company_name", "Unknown Company"))

        high_risk_count = sum(1 for loc in report_locations if loc.get("risk_level") in {"High", "Severe"})
        executive_summary = (
            f"Analyzed {manifest.count} locations for {company_name}. "
            f"High/Severe indicators were detected at {high_risk_count} locations."
        )

        overview = company_research.get("overview", {})
        if not isinstance(overview, Mapping):
            overview = {}
        company_overview = {
            "industry": str(overview.get("industry") or "Not available"),
            "operations_summary": str(overview.get("operations_summary") or "Not available"),
            "size_or_revenue": str(overview.get("size_or_revenue") or "Not available"),
            "citations": [str(url) for url in company_research.get("citations", []) if str(url).strip()],
        }

        unique_sources = sorted(
            {
                source
                for location in report_locations
                for source in location.get("citations", [])
                if isinstance(source, str) and source.strip()
            }
        )
        audit_entries = self._extract_audit_entries(payload)
        audit_appendix = {
            "input_files": [
                str(item)
                for item in payload.get("input_files", [])
                if isinstance(item, str)
            ],
            "location_count_expected": manifest.count,
            "location_count_reported": len(report_locations),
            "validation_status": "PASS" if len(report_locations) == manifest.count else "FAIL",
            "sources": unique_sources,
            "audit_entries": [dict(entry) for entry in audit_entries],
        }

        toc = self._build_toc(manifest=manifest, report_locations=report_locations)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "submission_id": manifest.submission_id or "submission",
            "manifest_hash": manifest.manifest_hash,
            "executive_summary": executive_summary,
            "company_overview": company_overview,
            "report_locations": report_locations,
            "audit_appendix": audit_appendix,
            "table_of_contents": toc,
            "report_template": report_template,
        }

    def _build_toc(self, *, manifest: LocationManifest, report_locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entries = [
            {"section": "Cover", "page": 1},
            {"section": "Table of Contents", "page": 2},
            {"section": "Executive Summary", "page": 3},
            {"section": "Company Overview", "page": 4},
        ]
        page_cursor = 5
        for location in report_locations:
            entries.append(
                {
                    "section": f"Location {location.get('location_id', '')}",
                    "page": page_cursor,
                }
            )
            page_cursor += 1
        entries.append({"section": "Audit Appendix", "page": page_cursor})
        if len(report_locations) != manifest.count:
            raise ValueError("table of contents generation failed: location count mismatch")
        return entries

    def _render_pdf(self, *, pdf_path: Path, report_data: Mapping[str, Any]) -> None:
        if not _REPORTLAB_AVAILABLE:
            raise RuntimeError("PDF rendering dependency unavailable: install 'reportlab'")

        styles = getSampleStyleSheet()
        story: list[Any] = []
        template_settings = _REPORT_TEMPLATES.get(
            str(report_data.get("report_template", "standard")),
            _REPORT_TEMPLATES["standard"],
        )

        story.append(Paragraph(str(template_settings["title"]), styles["Title"]))
        story.append(Paragraph(f"Submission ID: {report_data['submission_id']}", styles["Normal"]))
        story.append(Paragraph(f"Generated: {report_data['generated_at']}", styles["Normal"]))
        story.append(Spacer(1, 16))

        story.append(Paragraph("Table of Contents", styles["Heading2"]))
        for entry in report_data["table_of_contents"]:
            story.append(Paragraph(f"{entry['section']} .... {entry['page']}", styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Executive Summary", styles["Heading2"]))
        story.append(Paragraph(str(report_data["executive_summary"]), styles["Normal"]))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Company Overview", styles["Heading2"]))
        company = report_data["company_overview"]
        story.append(Paragraph(f"Industry: {company['industry']}", styles["Normal"]))
        story.append(Paragraph(f"Operations: {company['operations_summary']}", styles["Normal"]))
        story.append(Paragraph(f"Size/Revenue: {company['size_or_revenue']}", styles["Normal"]))
        if company["citations"]:
            story.append(Paragraph("Company Sources:", styles["Normal"]))
            for source in company["citations"]:
                story.append(Paragraph(f"- {source}", styles["Normal"]))
        story.append(Spacer(1, 12))

        report_locations = report_data["report_locations"]
        for section in report_locations:
            story.append(Paragraph(f"Location {section['location_id']}: {section['location_name']}", styles["Heading3"]))
            risk_hex = _risk_color_hex(str(section["risk_color"]))
            risk_badge = Table(
                [[f"Risk Indicator: {section['risk_level']} | Overall Score: {_format_score(section['overall_score'])}"]],
                hAlign="LEFT",
            )
            risk_badge.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), _risk_color_cell(str(section["risk_color"]))),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(risk_hex)),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(risk_badge)

            if bool(template_settings["include_category_table"]):
                category_rows = [["Category", "Score"]]
                for category, details in section["category_scores"].items():
                    score = details.get("score") if isinstance(details, Mapping) else "N/A"
                    category_rows.append([category.replace("_", " ").title(), _format_score(score)])
                table = Table(category_rows, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ]
                    )
                )
                story.append(table)
            story.append(Paragraph(f"Analysis: {section['analysis_narrative']}", styles["Normal"]))
            if bool(template_settings["include_key_factors"]):
                story.append(Paragraph("Key Factors:", styles["Normal"]))
                for factor in section["key_factors"]:
                    story.append(Paragraph(f"- {factor}", styles["Normal"]))
            story.append(Paragraph(f"10-Year Climate Outlook: {section['climate_outlook_10y']}", styles["Normal"]))
            story.append(Paragraph("Sources:", styles["Normal"]))
            citations = section["citations"] or ["None available"]
            for source in citations:
                story.append(Paragraph(f"- {source}", styles["Normal"]))
            story.append(Spacer(1, 12))

        audit = report_data["audit_appendix"]
        story.append(Paragraph("Audit Appendix", styles["Heading2"]))
        audit_is_pass = str(audit["validation_status"]).upper() == "PASS"
        audit_text_color = "#1E8449" if audit_is_pass else "#C0392B"
        audit_bg = colors.HexColor("#D5F5E3") if audit_is_pass else colors.HexColor("#F5B7B1")
        status_badge = Table([[f"Validation Status: {audit['validation_status']}"]], hAlign="LEFT")
        status_badge.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), audit_bg),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(audit_text_color)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(status_badge)
        story.append(
            Paragraph(
                (
                    f"Location Counts: expected={audit['location_count_expected']} "
                    f"reported={audit['location_count_reported']}"
                ),
                styles["Normal"],
            )
        )
        story.append(Paragraph("Input Files:", styles["Normal"]))
        for file_name in audit["input_files"] or ["Not provided"]:
            story.append(Paragraph(f"- {file_name}", styles["Normal"]))
        story.append(Paragraph("Sources Consulted:", styles["Normal"]))
        for source in audit["sources"] or ["None"]:
            story.append(Paragraph(f"- {source}", styles["Normal"]))

        document = SimpleDocTemplate(str(pdf_path), pagesize=LETTER)
        document.build(story)

    def _render_markdown(self, *, report_data: Mapping[str, Any]) -> str:
        lines: list[str] = []
        template_settings = _REPORT_TEMPLATES.get(
            str(report_data.get("report_template", "standard")),
            _REPORT_TEMPLATES["standard"],
        )
        lines.append(f"# {template_settings['title']}")
        lines.append("")
        lines.append(f"- Submission ID: {report_data['submission_id']}")
        lines.append(f"- Generated: {report_data['generated_at']}")
        lines.append("")
        lines.append("## Table of Contents")
        for entry in report_data["table_of_contents"]:
            lines.append(f"- {entry['section']} (page {entry['page']})")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append(str(report_data["executive_summary"]))
        lines.append("")
        lines.append("## Company Overview")
        company = report_data["company_overview"]
        lines.append(f"- Industry: {company['industry']}")
        lines.append(f"- Operations: {company['operations_summary']}")
        lines.append(f"- Size/Revenue: {company['size_or_revenue']}")
        lines.append("- Sources:")
        for source in company["citations"] or ["None"]:
            lines.append(f"  - {source}")
        lines.append("")

        for section in report_data["report_locations"]:
            lines.append(f"## Location {section['location_id']}: {section['location_name']}")
            lines.append(
                f"- Risk Indicator: {section['risk_level']} ({section['risk_color']}) | "
                f"Overall Score: {_format_score(section['overall_score'])}"
            )
            lines.append(f"- Analysis: {section['analysis_narrative']}")
            if bool(template_settings["include_key_factors"]):
                lines.append("- Key Factors:")
                for factor in section["key_factors"]:
                    lines.append(f"  - {factor}")
            lines.append(f"- 10-Year Climate Outlook: {section['climate_outlook_10y']}")
            lines.append("- Sources:")
            for source in section["citations"] or ["None"]:
                lines.append(f"  - {source}")
            lines.append("")

        audit = report_data["audit_appendix"]
        lines.append("## Audit Appendix")
        lines.append(f"- Validation Status: {audit['validation_status']}")
        lines.append(
            f"- Location Counts: expected={audit['location_count_expected']} "
            f"reported={audit['location_count_reported']}"
        )
        lines.append("- Input Files:")
        for file_name in audit["input_files"] or ["Not provided"]:
            lines.append(f"  - {file_name}")
        lines.append("- Sources Consulted:")
        for source in audit["sources"] or ["None"]:
            lines.append(f"  - {source}")
        lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _extract_manifest(self, payload: Mapping[str, Any]) -> LocationManifest | None:
        cursor: Mapping[str, Any] | None = payload
        for _ in range(6):
            if cursor is None:
                return None
            manifest_payload = cursor.get("manifest")
            if isinstance(manifest_payload, Mapping):
                return LocationManifest.from_dict(manifest_payload)
            previous = cursor.get("previous")
            if isinstance(previous, Mapping):
                cursor = previous
                continue
            return None
        return None
