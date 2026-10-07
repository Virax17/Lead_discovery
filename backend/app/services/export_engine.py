from typing import Literal, Optional

from bson import ObjectId
import pandas as pd

from app.db.connection import get_db
from app.services.error_logger import log_error
from app.services.storage import local_path, upload_if_needed

EXPORT_SOURCE_VALUE = "LeadDiscovery"

# Same labels as the UI's customerTypeLabel(): one customer-type vocabulary
# derived from the crawler's business_role for both Lead Discovery and Enrichment.
CUSTOMER_TYPE_LABELS = {
    "end_user_operator": "End User",
    "industrial_service_contractor": "Service Contractor",
    "epc_contractor": "EPC Contractor",
    "supplier_distributor": "Distributor",
    "competitor_manufacturer": "Competitor",
    "generic_local_service": "Not Relevant",
    "unknown": "Unknown",
}


def customer_type_label(role: Optional[str]) -> str:
    return CUSTOMER_TYPE_LABELS.get(role or "unknown", "Unknown")


def _join_list(value) -> str:
    return "; ".join(value) if isinstance(value, list) else (value or "")


async def _enrichment_cells(db, websites: list) -> dict:
    """domain -> enrichment summary for the exported businesses (one query)."""
    from app.services.enrichment_store import enrichment_summaries

    return await enrichment_summaries(db, [{"website": w} for w in websites])


def _enrichment_row(enrichments: dict, website: Optional[str], role: Optional[str]) -> dict:
    from app.services.company_cache import normalize_domain

    e = enrichments.get(normalize_domain(website or "")) or {}
    own = "tritorc" in (website or "").lower()
    is_competitor = not own and (role == "competitor_manufacturer" or bool(e.get("is_competitor")))
    return {
        "Recent Projects": _join_list(e.get("projects_or_recent_activity")),
        "Tritorc Relevance": _join_list(e.get("tritorc_relevance")),
        "Is Competitor": "Yes" if is_competitor else "No",
    }


EXPORT_COLUMNS = [
    "Source",
    "Company Name",
    "Website",
    "Address",
    "Phone Number",
    "Crawl Tier",
    "LLM Decision",
    "Industry Type",
    "Customer Type",
    "Recent Projects",
    "Tritorc Relevance",
    "Is Competitor",
    "Google Maps URL",
    "Industry Sector",
    "Website Signal",
    "Crawl Score",
    "Crawl Status",
    "Crawl Reason",
    "Crawl Evidence",
    "Original Evidence",
    "Translated Evidence",
    "Evidence URLs",
    "Detected Language",
    "Language Confidence",
    "Scoring Language",
    "Positive Concepts",
    "Negative Concepts",
    "Business Role",
    "Business Role Score",
    "Business Role Signals",
    "Business Role Negative Signals",
    "Business Role Reason",
    "Translation Status",
    "LLM Fallback Status",
    "LLM Fallback Confidence",
    "LLM Fallback Reason",
    "Source Keyword",
    "Source Query",
    "Source Query Language",
    "Google Primary Type",
    "First Found",
    "Last Seen",
]


def _apply_selected_columns(df: pd.DataFrame, selected_columns: Optional[list[str]]) -> pd.DataFrame:
    if not selected_columns:
        return df
    available_columns = [column for column in selected_columns if column in df.columns]
    return df[available_columns] if available_columns else df


async def export_search(
    search_id_str: str,
    fmt: Literal["xlsx", "csv"],
    selected_columns: Optional[list[str]] = None,
    selected_tiers: Optional[list[str]] = None,
    selected_roles: Optional[list[str]] = None,
) -> str | None:
    try:
        search_id = ObjectId(search_id_str)
        db = get_db()

        search = await db.searches.find_one({"_id": search_id})
        if not search:
            return None

        filename = f"{search_id_str}.{fmt}"
        path = local_path(filename)

        pipeline = [
            {"$match": {"search_id": search_id}},
            {
                "$lookup": {
                    "from": "master_businesses",
                    "localField": "master_business_id",
                    "foreignField": "_id",
                    "as": "business",
                }
            },
            {"$unwind": "$business"},
        ]
        if selected_tiers:
            pipeline.append({"$match": {"business.crawl_tier": {"$in": selected_tiers}}})
        if selected_roles:
            pipeline.append({"$match": {"business.business_role": {"$in": selected_roles}}})
        pipeline.append(
            {
                "$project": {
                    "Source": {"$literal": EXPORT_SOURCE_VALUE},
                    "Company Name": "$business.name",
                    "Address": "$business.address",
                    "Website": "$business.website",
                    "Phone Number": "$business.phone_number",
                    "Google Maps URL": "$business.maps_url",
                    "Industry Type": "$business.industry_type",
                    "Industry Sector": "$business.industry_sector",
                    "_role": "$business.business_role",
                    "Website Signal": "$business.website_signal",
                    "Crawl Tier": "$business.crawl_tier",
                    "Crawl Score": "$business.crawl_score",
                    "Crawl Status": "$business.crawl_status",
                    "Crawl Reason": "$business.crawl_reason",
                    "Crawl Evidence": "$business.crawl_evidence",
                    "Original Evidence": "$business.crawl_evidence_original",
                    "Translated Evidence": "$business.crawl_evidence_translated",
                    "Evidence URLs": "$business.crawl_evidence_urls",
                    "Detected Language": "$business.detected_language",
                    "Language Confidence": "$business.language_confidence",
                    "Scoring Language": "$business.scoring_language",
                    "Positive Concepts": "$business.positive_concepts",
                    "Negative Concepts": "$business.negative_concepts",
                    "Business Role": "$business.business_role",
                    "Business Role Score": "$business.business_role_score",
                    "Business Role Signals": "$business.business_role_signals",
                    "Business Role Negative Signals": "$business.business_role_negative_signals",
                    "Business Role Reason": "$business.business_role_reason",
                    "Translation Status": "$business.translation_status",
                    "LLM Fallback Status": "$business.llm_fallback_status",
                    "LLM Decision": "$business.llm_fallback_decision",
                    "LLM Fallback Confidence": "$business.llm_fallback_confidence",
                    "LLM Fallback Reason": "$business.llm_fallback_reason",
                    "Source Keyword": "$business.source_keyword",
                    "Source Query": "$business.source_query",
                    "Source Query Language": "$business.source_query_language",
                    "Google Primary Type": "$business.google_primary_type_display_name",
                    "First Found": "$business.first_found_at",
                    "Last Seen": "$business.last_seen_at",
                }
            }
        )

        docs = await db.search_results.aggregate(pipeline).to_list(length=None)
        enrichments = await _enrichment_cells(db, [d.get("Website") for d in docs])
        for d in docs:
            d["Customer Type"] = customer_type_label(d.get("_role"))
            d.update(_enrichment_row(enrichments, d.get("Website"), d.get("_role")))
        df = pd.DataFrame(docs, columns=EXPORT_COLUMNS)
        if "_id" in df.columns:
            df = df.drop(columns=["_id"])
        if "Crawl Evidence" in df.columns:
            df["Crawl Evidence"] = df["Crawl Evidence"].apply(lambda value: "; ".join(value) if isinstance(value, list) else value)
        for column in ("Original Evidence", "Translated Evidence", "Evidence URLs", "Positive Concepts", "Negative Concepts", "Business Role Signals", "Business Role Negative Signals"):
            if column in df.columns:
                df[column] = df[column].apply(lambda value: "; ".join(value) if isinstance(value, list) else value)
        df = _apply_selected_columns(df, selected_columns)

        if fmt == "xlsx":
            df.to_excel(path, index=False)
        else:
            df.to_csv(path, index=False)

        await upload_if_needed(filename)
        return filename

    except Exception as e:
        await log_error(
            search_id=ObjectId(search_id_str) if ObjectId.is_valid(search_id_str) else None,
            stage="export",
            place_id=None,
            error_message=str(e),
        )
        return None


async def export_country(
    country: str,
    fmt: Literal["xlsx", "csv"],
    selected_columns: Optional[list[str]] = None,
    selected_tiers: Optional[list[str]] = None,
    selected_roles: Optional[list[str]] = None,
) -> str | None:
    try:
        db = get_db()
        safe_country = "".join(c if c.isalnum() else "_" for c in country)
        filename = f"country_{safe_country}.{fmt}"
        path = local_path(filename)

        query = {"country": country}
        if selected_tiers:
            query["crawl_tier"] = {"$in": selected_tiers}
        if selected_roles:
            query["business_role"] = {"$in": selected_roles}
        docs = await db.master_businesses.find(query).to_list(length=None)
        enrichments = await _enrichment_cells(db, [d.get("website") for d in docs])

        rows = [
            {
                "Source": EXPORT_SOURCE_VALUE,
                "Company Name": d.get("name"),
                "Address": d.get("address"),
                "Website": d.get("website"),
                "Phone Number": d.get("phone_number"),
                "Google Maps URL": d.get("maps_url"),
                "Industry Type": d.get("industry_type"),
                "Industry Sector": d.get("industry_sector"),
                "Customer Type": customer_type_label(d.get("business_role")),
                **_enrichment_row(enrichments, d.get("website"), d.get("business_role")),
                "Website Signal": d.get("website_signal"),
                "Crawl Tier": d.get("crawl_tier"),
                "Crawl Score": d.get("crawl_score"),
                "Crawl Status": d.get("crawl_status"),
                "Crawl Reason": d.get("crawl_reason"),
                "Crawl Evidence": "; ".join(d.get("crawl_evidence", [])),
                "Original Evidence": "; ".join(d.get("crawl_evidence_original", [])),
                "Translated Evidence": "; ".join(d.get("crawl_evidence_translated", [])),
                "Evidence URLs": "; ".join(d.get("crawl_evidence_urls", [])),
                "Detected Language": d.get("detected_language"),
                "Language Confidence": d.get("language_confidence"),
                "Scoring Language": d.get("scoring_language"),
                "Positive Concepts": "; ".join(d.get("positive_concepts", [])),
                "Negative Concepts": "; ".join(d.get("negative_concepts", [])),
                "Business Role": d.get("business_role"),
                "Business Role Score": d.get("business_role_score"),
                "Business Role Signals": "; ".join(d.get("business_role_signals", [])),
                "Business Role Negative Signals": "; ".join(d.get("business_role_negative_signals", [])),
                "Business Role Reason": d.get("business_role_reason"),
                "Translation Status": d.get("translation_status"),
                "LLM Fallback Status": d.get("llm_fallback_status"),
                "LLM Decision": d.get("llm_fallback_decision"),
                "LLM Fallback Confidence": d.get("llm_fallback_confidence"),
                "LLM Fallback Reason": d.get("llm_fallback_reason"),
                "Source Keyword": d.get("source_keyword"),
                "Source Query": d.get("source_query"),
                "Source Query Language": d.get("source_query_language"),
                "Google Primary Type": d.get("google_primary_type_display_name"),
                "First Found": d.get("first_found_at"),
                "Last Seen": d.get("last_seen_at"),
            }
            for d in docs
        ]
        df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
        df = _apply_selected_columns(df, selected_columns)

        if fmt == "xlsx":
            df.to_excel(path, index=False)
        else:
            df.to_csv(path, index=False)

        await upload_if_needed(filename)
        return filename

    except Exception as e:
        await log_error(search_id=None, stage="export_country", place_id=None, error_message=str(e))
        return None
