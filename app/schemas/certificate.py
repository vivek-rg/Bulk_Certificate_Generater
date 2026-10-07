from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models import CertificateStatus, JobStatus


class RecipientInput(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Rahul Sharma"])
    email: EmailStr = Field(examples=["rahul@example.com"])

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be blank")
        return value


class CreateCertificateJobRequest(BaseModel):
    certificate_title: str = Field(min_length=1, max_length=200, examples=["Python Programming Certification"])
    certificate_date: date = Field(examples=["2026-10-07"])
    recipients: list[RecipientInput] = Field(min_length=1, max_length=10000)
    signature_image: str | None = Field(default=None, max_length=5_000_000, description="Optional base64 signature image")

    @field_validator("certificate_title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Certificate title must not be blank")
        return value


class CreateCertificateJobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    total_count: int
    message: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    total_count: int
    completed_count: int
    successful_count: int
    failed_count: int
    progress_percentage: float
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CertificateListItem(BaseModel):
    certificate_id: UUID
    certificate_number: str
    recipient_name: str
    recipient_email: EmailStr
    certificate_title: str
    certificate_date: date
    status: CertificateStatus
    download_url: str | None
    error_message: str | None


class CertificateListResponse(BaseModel):
    job_id: UUID
    total_count: int
    page: int
    page_size: int
    certificates: list[CertificateListItem]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
