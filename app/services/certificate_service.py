import base64
import logging
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)


def _fit_font_size(text: str, font_name: str, max_width: float, preferred: int = 34) -> int:
    size = preferred
    while size > 16 and stringWidth(text, font_name, size) > max_width:
        size -= 1
    return size


def _parse_image_bytes(image_data: str | bytes | Path) -> bytes | None:
    if isinstance(image_data, bytes):
        return image_data
    if isinstance(image_data, Path):
        return image_data.read_bytes() if image_data.is_file() else None
    if isinstance(image_data, str):
        data = image_data.strip()
        if not data:
            return None
        if data.startswith("data:") and "," in data:
            data = data.split(",", 1)[1]
        try:
            return base64.b64decode(data)
        except Exception:
            path = Path(data)
            if path.is_file():
                return path.read_bytes()
    return None


def _draw_signature(pdf: canvas.Canvas, signature_image: str | bytes | Path, page_width: float) -> None:
    raw_bytes = _parse_image_bytes(signature_image)
    if not raw_bytes:
        return
    try:
        reader = ImageReader(BytesIO(raw_bytes))
        center = page_width / 2
        box_width = 140
        box_height = 44
        sig_x = (center - 170) - (box_width / 2)
        sig_y = 100
        pdf.drawImage(
            reader,
            sig_x,
            sig_y,
            width=box_width,
            height=box_height,
            mask="auto",
            preserveAspectRatio=True,
            anchor="s",
        )
    except Exception as exc:
        logger.warning("Could not draw signature image: %s", exc)


def generate_certificate_pdf(
    *,
    template_path: Path,
    output_path: Path,
    recipient_name: str,
    certificate_title: str,
    certificate_date: date,
    certificate_number: str,
    organization_name: str,
    signature_image: str | bytes | Path | None = None,
) -> None:
    """Overlay recipient details on the shared, recipient-independent PDF template."""
    if not template_path.is_file():
        raise FileNotFoundError("Certificate template is missing")

    page_width, page_height = landscape(A4)
    overlay_buffer = BytesIO()
    pdf = canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
    center = page_width / 2

    pdf.setFillColorRGB(0.11, 0.20, 0.31)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(center, 510, organization_name[:80])

    pdf.setFillColorRGB(0.11, 0.20, 0.31)
    pdf.setFont("Helvetica-Bold", _fit_font_size(recipient_name, "Helvetica-Bold", page_width - 130, 31))
    pdf.drawCentredString(center, 398, recipient_name)

    pdf.setFillColorRGB(0.25, 0.32, 0.39)
    title_size = _fit_font_size(certificate_title, "Helvetica-Bold", page_width - 180, 19)
    pdf.setFont("Helvetica-Bold", title_size)
    pdf.drawCentredString(center, 321, certificate_title)

    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(center, 245, certificate_date.strftime("%d %B %Y"))

    pdf.setFillColorRGB(0.31, 0.37, 0.42)
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(center, 115, f"Certificate ID: {certificate_number}")

    if signature_image:
        _draw_signature(pdf, signature_image, page_width)

    pdf.save()
    overlay_buffer.seek(0)

    background = PdfReader(str(template_path))
    overlay = PdfReader(overlay_buffer)
    if len(background.pages) != 1:
        raise ValueError("Certificate template must contain exactly one page")

    writer = PdfWriter(clone_from=str(template_path))
    page = writer.pages[0]
    page.merge_page(overlay.pages[0])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f"{output_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("wb") as pdf_file:
            writer.write(pdf_file)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
