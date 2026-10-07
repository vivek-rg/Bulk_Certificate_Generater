"""Regenerate the shared, recipient-independent certificate background PDF."""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


OUTPUT = Path(__file__).resolve().parents[1] / "templates" / "certificate_template.pdf"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    width, height = landscape(A4)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=(width, height))
    navy = HexColor("#1C344B")
    gold = HexColor("#B78A3B")
    ink = HexColor("#293846")

    pdf.setFillColor(HexColor("#FBFAF6"))
    pdf.rect(0, 0, width, height, fill=1, stroke=0)
    pdf.setStrokeColor(navy)
    pdf.setLineWidth(3)
    pdf.roundRect(28, 25, width - 56, height - 50, 12, fill=0, stroke=1)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.3)
    pdf.roundRect(36, 33, width - 72, height - 66, 9, fill=0, stroke=1)

    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 29)
    pdf.drawCentredString(width / 2, 470, "CERTIFICATE")
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1)
    pdf.line(width / 2 - 95, 455, width / 2 + 95, 455)

    pdf.setFillColor(ink)
    pdf.setFont("Helvetica", 15)
    pdf.drawCentredString(width / 2, 430, "This certificate is proudly presented to")
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(width / 2, 345, "for successfully completing")
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(width / 2, 273, "on")
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(width / 2 - 170, 77, "AUTHORIZED SIGNATORY")
    pdf.setStrokeColor(ink)
    pdf.setLineWidth(0.9)
    pdf.line(width / 2 - 250, 96, width / 2 - 90, 96)
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(HexColor("#5F6B75"))
    pdf.drawRightString(width - 64, 50, "Recognizing dedication, learning, and achievement")
    pdf.showPage()
    pdf.save()
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    main()
