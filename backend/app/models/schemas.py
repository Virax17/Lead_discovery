from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
from bson import ObjectId

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, *args, **kwargs):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        return {"type": "string"}

class MasterBusiness(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    place_id: str
    name: str
    address: str
    website: Optional[str] = None
    phone_number: Optional[str] = None
    maps_url: Optional[str] = None
    data_source: str = "google_places"
    country: Optional[str] = None
    country_code: Optional[str] = None
    industry_sector: Optional[str] = None
    industry_type: Optional[str] = None
    customer_type: Optional[str] = None
    website_signal: Optional[str] = None
    source_query: Optional[str] = None
    source_query_language: Optional[str] = None
    source_keyword: Optional[str] = None
    google_types: List[str] = Field(default_factory=list)
    google_primary_type: Optional[str] = None
    google_primary_type_display_name: Optional[str] = None
    google_business_status: Optional[str] = None
    crawl_status: Optional[str] = None
    crawl_score: Optional[int] = None
    crawl_tier: Optional[str] = None
    crawl_pages_checked: int = 0
    crawl_positive_signals: List[str] = Field(default_factory=list)
    crawl_negative_signals: List[str] = Field(default_factory=list)
    crawl_evidence: List[str] = Field(default_factory=list)
    crawl_evidence_original: List[str] = Field(default_factory=list)
    crawl_evidence_translated: List[str] = Field(default_factory=list)
    crawl_evidence_urls: List[str] = Field(default_factory=list)
    crawl_reason: Optional[str] = None
    crawl_checked_at: Optional[datetime] = None
    crawl_version: Optional[str] = None
    detected_language: Optional[str] = None
    language_confidence: Optional[float] = None
    scoring_language: Optional[str] = None
    matched_concepts: List[str] = Field(default_factory=list)
    positive_concepts: List[str] = Field(default_factory=list)
    negative_concepts: List[str] = Field(default_factory=list)
    business_role: Optional[str] = None
    business_role_score: Optional[int] = None
    business_role_signals: List[str] = Field(default_factory=list)
    business_role_negative_signals: List[str] = Field(default_factory=list)
    business_role_reason: Optional[str] = None
    scoring_version: Optional[str] = None
    translation_status: Optional[str] = None
    translation_provider: Optional[str] = None
    translation_checked_at: Optional[datetime] = None
    llm_fallback_status: Optional[str] = None
    llm_fallback_provider: Optional[str] = None
    llm_fallback_model: Optional[str] = None
    llm_fallback_decision: Optional[str] = None
    llm_fallback_confidence: Optional[float] = None
    llm_fallback_reason: Optional[str] = None
    llm_fallback_checked_at: Optional[datetime] = None
    first_found_at: datetime
    last_seen_at: datetime

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class RejectedBusiness(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    place_id: str
    name: str
    website: Optional[str] = None
    reason: str
    rejected_at: datetime

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class Search(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    created_by: Optional[str] = None
    country: str
    country_code: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_km: Optional[float] = None
    max_results: int
    status: str
    keywords_total: int
    keywords_completed: int = 0
    total_results: int = 0
    place_details_calls_used: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class SearchResult(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    search_id: PyObjectId
    master_business_id: PyObjectId
    matched_keyword: str
    source_query: Optional[str] = None
    source_query_language: Optional[str] = None
    details_status: str # 'ok', 'failed_after_retries'
    customer_type: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class ApiUsageMonthly(BaseModel):
    year_month: str = Field(alias="_id") # "2026-06"
    place_details_calls: int = 0
    updated_at: datetime
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class AppError(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    search_id: Optional[PyObjectId] = None
    stage: str
    place_id: Optional[str] = None
    error_message: str
    occurred_at: datetime
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

# API specific schemas

class SearchCreate(BaseModel):
    country: str
    country_code: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    max_results: int = Field(default=100, ge=1, le=100)
    keywords: List[str]
    industries: List[str]
    website_only: bool = True
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    # Google's locationBias.circle.radius is hard-capped at 50000m (50km) --
    # see LOCATION_BIAS_RADIUS_METERS in search_runner.py.
    radius_km: Optional[float] = Field(default=None, gt=0, le=50)

    @field_validator("country_code")
    @classmethod
    def _normalize_country_code(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v

    @model_validator(mode="after")
    def _validate_custom_area(self):
        provided = [self.center_lat, self.center_lng, self.radius_km]
        if any(v is not None for v in provided) and not all(v is not None for v in provided):
            raise ValueError("center_lat, center_lng, and radius_km must all be provided together.")
        return self

class SearchStatusResponse(BaseModel):
    id: str
    status: str
    keywords_completed: int
    keywords_total: int
    total_results: int
    quota_status: str

class PlaceDetails(BaseModel):
    name: str
    address: str
    website: Optional[str] = None
    phone_number: Optional[str] = None
    country_code: Optional[str] = None
    google_types: List[str] = Field(default_factory=list)
    google_primary_type: Optional[str] = None
    google_primary_type_display_name: Optional[str] = None
    google_business_status: Optional[str] = None
    google_maps_uri: Optional[str] = None
    source_query: Optional[str] = None
    source_query_language: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

class AppSettings(BaseModel):
    id: str = Field(alias="_id", default="singleton")
    active_plan: str = "free" # 'free' or 'paid_overage'
    allow_paid_overage: bool = False
    updated_at: datetime
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


class AppSettingsUpdate(BaseModel):
    active_plan: Optional[str] = None
    allow_paid_overage: Optional[bool] = None


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    credit_limit: int = Field(default=1000, ge=0)


class UserPasswordUpdate(BaseModel):
    password: str = Field(min_length=1)


class UserActiveUpdate(BaseModel):
    active: bool


class UserPublic(BaseModel):
    id: str = Field(alias="_id")
    username: str
    role: str = "user"
    active: bool = True
    credit_limit: int = 1000
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


class UserUsage(UserPublic):
    year_month: str
    credits_used: int = 0
    credits_remaining: Optional[int] = None


class CurrentUser(BaseModel):
    username: str
    role: str
    credit_limit: int = 1000
    active: bool = True
    created_at: datetime
    last_login_at: Optional[datetime] = None
