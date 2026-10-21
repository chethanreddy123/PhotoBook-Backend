"""Turn an uploaded image into numbered strips arranged on A4 PDF sheets."""

import logging
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fpdf import FPDF
from PIL import Image, UnidentifiedImageError
from starlette.background import BackgroundTask


app = FastAPI(title="PhotoBook Image-to-PDF API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["*"],
)
logger = logging.getLogger(__name__)

PIXELS_PER_CM = 96 / 2.54
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


def resize_and_stretch_image(image_file, book_height_cm, num_pages, strip_width_cm):
    """Stretch to the requested physical dimensions at a working 96 DPI."""
    width = max(num_pages, round(num_pages * strip_width_cm * PIXELS_PER_CM))
    height = max(1, round(book_height_cm * PIXELS_PER_CM))
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(422, "Requested layout exceeds the 20-megapixel limit.")

    with Image.open(image_file) as original:
        if original.format not in {"JPEG", "PNG"}:
            raise HTTPException(422, "Upload a JPEG or PNG image.")
        if original.width * original.height > MAX_IMAGE_PIXELS:
            raise HTTPException(413, "Input image exceeds the 20-megapixel limit.")
        original.load()  # Detect truncated files before creating the PDF.
        rgba = original.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        return rgb.resize((width, height), Image.Resampling.LANCZOS)


def create_pdf(resized_image, book_height_cm, strip_width_cm, num_pages, output_folder):
    """Arrange strips left to right, continuing onto additional A4 sheets."""
    pdf = FPDF(orientation="P", unit="cm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    x_position = 1.0
    y_position = 3.0

    for strip in range(num_pages):
        if x_position + strip_width_cm > 20.0 + 1e-9:
            pdf.add_page()
            x_position = 1.0

        # Proportional boundaries include every column, including the final one.
        left = round(strip * resized_image.width / num_pages)
        right = round((strip + 1) * resized_image.width / num_pages)
        with resized_image.crop((left, 0, right, resized_image.height)) as strip_image:
            strip_path = Path(output_folder) / f"strip_{strip}.jpg"
            strip_image.save(strip_path)

        pdf.set_xy(x_position, y_position - 1.5)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(strip_width_cm, 1, f"Strip {strip + 1}", align="C")
        pdf.image(str(strip_path), x=x_position, y=y_position,
                  w=strip_width_cm, h=book_height_cm)
        x_position += strip_width_cm + 1.0

    pdf_path = Path(output_folder) / "output.pdf"
    pdf.output(str(pdf_path))
    return pdf_path


@app.post("/generate-pdf/", response_class=FileResponse)
def generate_pdf(
    image: UploadFile = File(...),
    book_height_cm: float = Form(..., ge=0.1, le=25.7),
    num_pages: int = Form(..., ge=1, le=500),
    strip_width_cm: float = Form(..., ge=0.1, le=19.0),
):
    """Return numbered image strips as a PDF; num_pages is the strip count."""
    workspace = TemporaryDirectory(prefix="photobook-")
    try:
        content = image.file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Upload exceeds the 10 MiB limit.")
        try:
            resized = resize_and_stretch_image(
                BytesIO(content), book_height_cm, num_pages, strip_width_cm
            )
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, "Upload a complete, readable JPEG or PNG image.") from exc

        with resized:
            pdf_path = create_pdf(
                resized, book_height_cm, strip_width_cm, num_pages, workspace.name
            )
        # Keep files alive until the response finishes, then remove every artifact.
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename="photobook.pdf",
            background=BackgroundTask(workspace.cleanup),
        )
    except HTTPException:
        workspace.cleanup()
        raise
    except Exception as exc:
        workspace.cleanup()
        logger.exception("PDF generation failed")
        raise HTTPException(500, "PDF generation failed.") from exc
    finally:
        image.file.close()
