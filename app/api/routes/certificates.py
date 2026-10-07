import io
import logging
from pathlib import Path
from uuid import UUID
import zipfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Certificate, CertificateStatus, GenerationJob
from app.schemas.certificate import (
    CertificateListItem,
    CertificateListResponse,
    CreateCertificateJobRequest,
    CreateCertificateJobResponse,
    HealthResponse,
    JobStatusResponse,
)
from app.services.job_service import create_job, process_generation_job

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """Return a simple liveness response."""
    return HealthResponse(status="ok", service="bulk-certificate-generator")


@router.post(
    "/certificate-jobs",
    response_model=CreateCertificateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a bulk certificate generation job",
    description="Validates recipients, stores the job, and schedules PDF generation in the background.",
    responses={202: {"description": "Job accepted for processing"}, 422: {"description": "Invalid request"}},
)
def create_certificate_job(
    payload: CreateCertificateJobRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_db),
) -> CreateCertificateJobResponse:
    job = create_job(session, payload)
    background_tasks.add_task(
        process_generation_job,
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
    )
    return CreateCertificateJobResponse(
        job_id=job.id,
        status=job.status,
        total_count=job.total_count,
        message="Certificate generation job accepted",
    )


@router.get(
    "/certificate-jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status and progress",
    responses={404: {"description": "Job not found"}},
)
def get_certificate_job(job_id: UUID, session: Session = Depends(get_db)) -> JobStatusResponse:
    job = session.get(GenerationJob, str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    progress = round((job.completed_count / job.total_count) * 100, 1) if job.total_count else 0.0
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        total_count=job.total_count,
        completed_count=job.completed_count,
        successful_count=job.successful_count,
        failed_count=job.failed_count,
        progress_percentage=progress,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get(
    "/certificate-jobs/{job_id}/certificates",
    response_model=CertificateListResponse,
    summary="List certificates for a job",
    responses={404: {"description": "Job not found"}},
)
def list_job_certificates(
    job_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> CertificateListResponse:
    job_key = str(job_id)
    job = session.get(GenerationJob, job_key)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    total = job.total_count
    certificates = session.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_key)
        .order_by(Certificate.sequence)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        CertificateListItem(
            certificate_id=certificate.id,
            certificate_number=certificate.certificate_number,
            recipient_name=certificate.recipient_name,
            recipient_email=certificate.recipient_email,
            certificate_title=certificate.certificate_title,
            certificate_date=certificate.certificate_date,
            status=certificate.status,
            download_url=(
                f"/api/v1/certificates/{certificate.id}"
                if certificate.status == CertificateStatus.COMPLETED
                else None
            ),
            error_message=certificate.error_message,
        )
        for certificate in certificates
    ]
    return CertificateListResponse(
        job_id=job_key,
        total_count=total,
        page=page,
        page_size=page_size,
        certificates=items,
    )


@router.get(
    "/certificate-jobs/{job_id}/zip",
    summary="Download all completed certificates as a ZIP archive",
    responses={
        200: {"description": "ZIP archive of all completed certificates"},
        404: {"description": "Job not found"},
        409: {"description": "No certificates are ready for download"},
    },
)
@router.get(
    "/certificate-jobs/{job_id}/download",
    include_in_schema=False,
)
def download_all_certificates(job_id: UUID, session: Session = Depends(get_db)) -> StreamingResponse:
    job_key = str(job_id)
    job = session.get(GenerationJob, job_key)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    root_str = session.info.get("generated_files_dir", "")
    if not root_str:
        logger.error("Storage directory configuration is missing")
        raise HTTPException(status_code=500, detail="Storage configuration error")
    root = Path(root_str).resolve()

    completed_certs = session.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_key, Certificate.status == CertificateStatus.COMPLETED)
        .order_by(Certificate.sequence)
    ).all()

    if not completed_certs:
        raise HTTPException(status_code=409, detail="No certificates are ready for download")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for cert in completed_certs:
            if not cert.file_path:
                continue
            path = Path(cert.file_path).resolve()
            if _is_within(path, root) and path.is_file():
                safe_name = "".join(c for c in cert.recipient_name if c.isalnum() or c in " -_").strip()
                filename = f"{cert.certificate_number}_{safe_name}.pdf" if safe_name else f"{cert.certificate_number}.pdf"
                archive.write(path, arcname=filename)

    zip_buffer.seek(0)
    title_raw = completed_certs[0].certificate_title or "certificates"
    safe_title = "".join(c for c in title_raw if c.isalnum() or c in " -_").strip() or "certificates"
    zip_filename = f"{safe_title}_{str(job_id)[:8]}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.get(
    "/certificates/{certificate_id}",
    summary="Download a generated certificate PDF",
    responses={404: {"description": "Certificate or file not found"}, 409: {"description": "Certificate is not ready"}},
)
def download_certificate(certificate_id: UUID, session: Session = Depends(get_db)) -> FileResponse:
    certificate = session.get(Certificate, str(certificate_id))
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if certificate.status != CertificateStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Certificate is not ready for download")
    if not certificate.file_path:
        logger.error("Completed certificate %s is missing its file path", certificate.id)
        raise HTTPException(status_code=404, detail="Certificate file not found")

    root_str = session.info.get("generated_files_dir", "")
    if not root_str:
        logger.error("Storage directory configuration is missing")
        raise HTTPException(status_code=500, detail="Storage configuration error")
    root = Path(root_str).resolve()
    path = Path(certificate.file_path).resolve()
    if not _is_within(path, root):
        logger.error("Certificate file path failed storage validation: %s", certificate.id)
        raise HTTPException(status_code=404, detail="Certificate file not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Certificate file not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{certificate.certificate_number}.pdf",
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
