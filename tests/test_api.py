from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

import main


def image_bytes(fmt="JPEG", color="red"):
    output = BytesIO()
    mode = "RGBA" if fmt == "PNG" else "RGB"
    with Image.new(mode, (60, 40), color) as image:
        image.save(output, format=fmt)
    return output.getvalue()


@pytest.fixture(autouse=True)
def isolated_workspace(monkeypatch, tmp_path):
    folders = []

    def temporary_directory(**kwargs):
        workspace = TemporaryDirectory(dir=tmp_path, **kwargs)
        folders.append(Path(workspace.name))
        return workspace

    monkeypatch.setattr(main, "TemporaryDirectory", temporary_directory)
    yield folders
    assert all(not folder.exists() for folder in folders), "Request artifacts leaked"


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


def request_pdf(client, *, data=None, content=None, filename="image.jpg"):
    fields = {"book_height_cm": "5", "num_pages": "3", "strip_width_cm": "6"}
    fields.update(data or {})
    return client.post("/generate-pdf/", data=fields,
                       files={"image": (filename, image_bytes() if content is None else content)})


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_valid_images_produce_numbered_a4_pdf(client, fmt):
    response = request_pdf(client, content=image_bytes(fmt))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="photobook.pdf"' in response.headers["content-disposition"]
    pdf = PdfReader(BytesIO(response.content))
    assert len(pdf.pages) == 2
    assert "Strip 1" in pdf.pages[0].extract_text()
    assert "Strip 2" in pdf.pages[0].extract_text()
    assert "Strip 3" in pdf.pages[1].extract_text()
    assert float(pdf.pages[0].mediabox.width) == pytest.approx(595.28, abs=0.1)
    assert float(pdf.pages[0].mediabox.height) == pytest.approx(841.89, abs=0.1)
    assert sum(len(page.images) for page in pdf.pages) >= 2


def test_transparent_png_is_composited_on_white(client):
    response = request_pdf(client, content=image_bytes("PNG", (255, 0, 0, 0)))
    assert response.status_code == 200
    image = PdfReader(BytesIO(response.content)).pages[0].images[0].image.convert("RGB")
    assert all(channel >= 250 for channel in image.getpixel((0, 0)))


@pytest.mark.parametrize("field,value", [
    ("book_height_cm", "0"), ("book_height_cm", "25.8"),
    ("book_height_cm", "nan"), ("book_height_cm", "inf"),
    ("num_pages", "0"), ("num_pages", "-1"), ("num_pages", "501"),
    ("num_pages", "1.5"), ("strip_width_cm", "0"),
    ("strip_width_cm", "19.1"), ("strip_width_cm", "not-a-number"),
])
def test_invalid_dimensions_are_validation_errors(client, field, value):
    response = request_pdf(client, data={field: value})
    assert response.status_code == 422


def test_missing_file_is_validation_error(client):
    response = client.post("/generate-pdf/", data={
        "book_height_cm": "5", "num_pages": "3", "strip_width_cm": "1"})
    assert response.status_code == 422


@pytest.mark.parametrize("content", [b"", b"not an image", image_bytes()[:100], image_bytes("GIF")])
def test_invalid_or_unsupported_image(client, content):
    response = request_pdf(client, content=content)
    assert response.status_code == 422


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    assert request_pdf(client).status_code == 413


def test_input_pixel_limit(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_PIXELS", 2000)
    response = request_pdf(client, data={"book_height_cm": "1", "num_pages": "1", "strip_width_cm": "1"})
    assert response.status_code == 413


def test_layout_pixel_limit(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_PIXELS", 1000)
    assert request_pdf(client).status_code == 422


def test_filename_is_not_used_as_a_path(client):
    assert request_pdf(client, filename="../../outside.jpg").status_code == 200


def test_internal_failure_is_sanitized_and_cleans_up(client, monkeypatch):
    def fail(*args):
        raise RuntimeError("private server path")
    monkeypatch.setattr(main, "create_pdf", fail)
    response = request_pdf(client)
    assert response.status_code == 500
    assert response.json() == {"detail": "PDF generation failed."}


def test_overlapping_requests_keep_outputs_separate(monkeypatch, isolated_workspace):
    barrier = Barrier(2)
    original = main.create_pdf

    def overlapping_render(*args):
        barrier.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(main, "create_pdf", overlapping_render)

    def generate(count):
        with TestClient(main.app) as client:
            response = request_pdf(client, data={"num_pages": str(count)})
            assert response.status_code == 200
            pdf = PdfReader(BytesIO(response.content))
            text = " ".join(page.extract_text() for page in pdf.pages)
            assert f"Strip {count}" in text
            assert f"Strip {count + 1}" not in text
            return response.content

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(generate, [1, 4]))
    assert first != second
    assert len(set(isolated_workspace)) == 2
