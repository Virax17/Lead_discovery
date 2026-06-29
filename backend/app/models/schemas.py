from pydantic import BaseModel, Field, ConfigDict
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
    industry_sector: Optional[str] = None
    industry_type: Optional[str] = None
    customer_type: Optional[str] = None
    first_found_at: datetime
    last_seen_at: datetime
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

class Search(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    country: str
    state: Optional[str] = None
    city: Optional[str] = None
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
    country_code: str
    state: Optional[str] = None
    city: Optional[str] = None
    max_results: int = 100
    keywords: List[str]
    industries: List[str]
    website_only: bool = True

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

class AppSettings(BaseModel):
    id: str = Field(alias="_id", default="singleton")
    active_plan: str = "free" # 'free' or 'paid_overage'
    allow_paid_overage: bool = False
    updated_at: datetime
    
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


class AppSettingsUpdate(BaseModel):
    active_plan: Optional[str] = None
    allow_paid_overage: Optional[bool] = None
