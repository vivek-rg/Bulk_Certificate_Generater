import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import (
    Certificate,
    CertificateStatus,
    GenerationJob,
    JobStatus,
)
from app.schemas.certificate import CreateCertificateJobRequest
from app.services.certificate_service import generate_certificate_pdf

logger = logging.getLogger(__name__)
SessionFactory = sessionmaker
PdfGenerator = Callable[..., None]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_job(session: Session, payload: CreateCertificateJobRequest) -> GenerationJob:
    job = GenerationJob(
        total_count=len(payload.recipients),
        signature_image=payload.signature_image,
    )
    session.add(job)
    session.flush()
    year = payload.certificate_date.year
    for index, recipient in enumerate(payload.recipients):
        certificate = Certificate(
            job_id=job.id,
            sequence=index,
            certificate_number=f"CERT-{year}-{uuid.uuid4().hex[:12].upper()}",
            recipient_name=recipient.name,
            recipient_email=str(recipient.email),
            certificate_title=payload.certificate_title,
            certificate_date=payload.certificate_date,
        )
        session.add(certificate)
    session.commit()
    session.refresh(job)
    logger.info("Created certificate generation job %s with %d recipients", job.id, job.total_count)
    return job


def recover_interrupted_jobs(session_factory: SessionFactory) -> int:
    """Recover any jobs left in PROCESSING or PENDING state across server restarts."""
    recovered_count = 0
    with session_factory() as session:
        stale_jobs = list(
            session.scalars(
                select(GenerationJob).where(
                    GenerationJob.status.in_([JobStatus.PROCESSING, JobStatus.PENDING])
                )
            )
        )
        for job in stale_jobs:
            recovered_count += 1
            session.execute(
                update(Certificate)
                .where(
                    Certificate.job_id == job.id,
                    Certificate.status.in_([CertificateStatus.PROCESSING, CertificateStatus.PENDING]),
                )
                .values(
                    status=CertificateStatus.FAILED,
                    error_message="Interrupted by server restart",
                    completed_at=utc_now(),
                )
            )
            successful = session.scalar(
                select(func.count())
                .select_from(Certificate)
                .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.COMPLETED)
            ) or 0
            failed = session.scalar(
                select(func.count())
                .select_from(Certificate)
                .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.FAILED)
            ) or 0
            job.successful_count = successful
            job.failed_count = failed
            job.completed_count = successful + failed
            job.completed_at = utc_now()
            if successful > 0 and failed > 0:
                job.status = JobStatus.COMPLETED_WITH_ERRORS
            elif successful > 0 and failed == 0:
                job.status = JobStatus.COMPLETED
            else:
                job.status = JobStatus.FAILED
            logger.warning("Recovered interrupted job %s: status set to %s", job.id, job.status)
        session.commit()
    return recovered_count


def process_generation_job(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
    pdf_generator: PdfGenerator | None = None,
) -> None:
    """Claim and process a job, committing each recipient's outcome independently."""
    pdf_generator = pdf_generator or generate_certificate_pdf
    try:
        _process_generation_job(job_id, session_factory, settings, pdf_generator)
    except Exception as exc:
        logger.error("Job processing failed: %s (%s)", job_id, type(exc).__name__)
        try:
            with session_factory() as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    job.status = JobStatus.FAILED
                    job.completed_at = utc_now()
                    session.commit()
        except Exception as persist_error:
            logger.error("Could not persist failed state for job %s (%s)", job_id, type(persist_error).__name__)


def _process_generation_job(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
    pdf_generator: PdfGenerator,
) -> None:
    with session_factory() as session:
        claim = session.execute(
            update(GenerationJob)
            .where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.PENDING)
            .values(status=JobStatus.PROCESSING, started_at=utc_now())
        )
        session.commit()
        if claim.rowcount != 1:
            logger.info("Skipped job %s because it was missing or already claimed", job_id)
            return

        if not settings.template_path.is_file():
            logger.error("Job %s failed: template file is missing at %s", job_id, settings.template_path)
            job = session.get(GenerationJob, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
            session.execute(
                update(Certificate)
                .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING)
                .values(
                    status=CertificateStatus.FAILED,
                    error_message="Certificate template is missing",
                    completed_at=utc_now(),
                )
            )
            total = session.scalar(
                select(func.count()).select_from(Certificate).where(Certificate.job_id == job_id)
            ) or 0
            if job:
                job.completed_count = total
                job.failed_count = total
            session.commit()
            return

        job_record = session.get(GenerationJob, job_id)
        signature_image = job_record.signature_image if job_record else None

        certificate_ids = list(
            session.scalars(
                select(Certificate.id)
                .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING)
                .order_by(Certificate.sequence)
            )
        )
    logger.info("Job %s started with %d certificates", job_id, len(certificate_ids))

    for certificate_id in certificate_ids:
        # Load certificate metadata for rendering and mark PROCESSING
        with session_factory() as session:
            certificate = session.get(Certificate, certificate_id)
            if certificate is None or certificate.status != CertificateStatus.PENDING:
                continue
            certificate.status = CertificateStatus.PROCESSING
            session.commit()
            recipient_name = certificate.recipient_name
            certificate_title = certificate.certificate_title
            certificate_date = certificate.certificate_date
            certificate_number = certificate.certificate_number

        logger.info("Certificate generation started: %s", certificate_id)
        output_path = _certificate_output_path(settings.generated_files_dir, job_id, certificate_id)
        generation_error = None

        try:
            pdf_generator(
                template_path=settings.template_path,
                output_path=output_path,
                recipient_name=recipient_name,
                certificate_title=certificate_title,
                certificate_date=certificate_date,
                certificate_number=certificate_number,
                organization_name=settings.organization_name,
                signature_image=signature_image,
            )
        except Exception as exc:
            logger.error("Certificate generation failed: %s (%s)", certificate_id, type(exc).__name__)
            generation_error = f"Certificate generation failed ({type(exc).__name__})"[:500]

        # Update certificate outcome and job aggregate counters in a single atomic transaction
        with session_factory() as session:
            certificate = session.get(Certificate, certificate_id)
            job = session.get(GenerationJob, job_id)
            if certificate is not None:
                certificate.completed_at = utc_now()
                if generation_error is None:
                    certificate.status = CertificateStatus.COMPLETED
                    certificate.file_path = str(output_path.resolve())
                    certificate.error_message = None
                    if job:
                        job.successful_count += 1
                else:
                    certificate.status = CertificateStatus.FAILED
                    certificate.error_message = generation_error
                    if job:
                        job.failed_count += 1
                if job:
                    job.completed_count += 1
                session.commit()

        if generation_error is None:
            logger.info("Certificate generated successfully: %s", certificate_id)

    with session_factory() as session:
        job = session.get(GenerationJob, job_id)
        if job is None:
            return
        job.completed_at = utc_now()
        if job.completed_count < job.total_count:
            job.status = JobStatus.COMPLETED_WITH_ERRORS if job.successful_count > 0 else JobStatus.FAILED
        elif job.failed_count > 0:
            job.status = JobStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = JobStatus.COMPLETED
        session.commit()
        logger.info(
            "Job %s completed: %d successful, %d failed",
            job_id,
            job.successful_count,
            job.failed_count,
        )


def _certificate_output_path(root: Path, job_id: str, certificate_id: str) -> Path:
    """Build paths only from canonical UUIDs stored by the application."""
    safe_job_id = str(uuid.UUID(job_id))
    safe_certificate_id = str(uuid.UUID(certificate_id))
    return root / safe_job_id / f"{safe_certificate_id}.pdf"
