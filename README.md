# PhotoBook Backend

[![API tests](https://github.com/chethanreddy123/PhotoBook-Backend/actions/workflows/test.yml/badge.svg)](https://github.com/chethanreddy123/PhotoBook-Backend/actions/workflows/test.yml)

A small FastAPI image-processing project: upload a JPEG or PNG, choose physical dimensions, and download a PDF of numbered image strips arranged on A4 sheets. The image is intentionally stretched to the requested book dimensions; it does not preserve the original aspect ratio.

This is an earlier personal project, with reproducibility and API reliability improvements added in October 2026. It is not an AI model, a complete photobook editor, or a hosted production service. The original algorithm notebook remains in the repository as historical exploration; it is not required to run the API.

## Run locally

Python **3.11–3.13**. No account, API key, database or paid service is required.

```sh
git clone https://github.com/chethanreddy123/PhotoBook-Backend.git
cd PhotoBook-Backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

On Windows, activate the environment with `.venv\Scripts\activate` instead. Open [interactive API documentation](http://127.0.0.1:8000/docs); the root URL has no frontend. Keep the server running while trying the example below from a second terminal.

## Generate a PDF

```sh
curl --fail-with-body http://127.0.0.1:8000/generate-pdf/ \
  -F 'image=@SampleDog.jpeg' \
  -F 'book_height_cm=20' \
  -F 'num_pages=12' \
  -F 'strip_width_cm=1' \
  --output photobook.pdf
```

`POST /generate-pdf/` accepts multipart form data:

| Field | Meaning | Accepted values |
| --- | --- | --- |
| `image` | Image upload | JPEG or PNG, up to 10 MiB and 20 megapixels |
| `book_height_cm` | Printed strip height | 0.1–25.7 cm |
| `num_pages` | **Number of image strips**, not output PDF sheets | Integer, 1–500 |
| `strip_width_cm` | Printed width of each strip | 0.1–19 cm |

The combined resized image is limited to 20 megapixels. Strips use a working resolution of 96 DPI, 1 cm side margins, 1 cm horizontal gaps, and a 3 cm top offset for numbering. More A4 sheets are added when a row fills. Transparent PNG pixels are composited onto white. Print at actual size/100% to retain the requested dimensions; 96 DPI is not intended for high-resolution photo printing.

A successful response is `200 application/pdf`, downloaded as `photobook.pdf`. For the example, 12 strips occupy two sheets. Each request uses a separate temporary directory; intermediate images and the PDF are deleted after the response completes. Upload filenames are not used as server paths.

- **422:** missing/invalid fields, unreadable or unsupported image, or oversized requested layout.
- **413:** image upload or decoded dimensions exceed the input limits.
- **500:** unexpected rendering failure, with a generic response rather than internal exception details.

## Verify changes

```sh
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest -q
```

Tests parse generated PDFs to check A4 sheets and numbering, exercise JPEG/PNG inputs, invalid dimensions and files, resource limits, path-like filenames, internal failures, concurrent requests and temporary-file cleanup. GitHub Actions runs the suite on Python 3.11, 3.12 and 3.13. Tests use synthetic images and require no network calls or credentials.

## Scope and deployment limits

The service renders synchronously in FastAPI's worker threads and holds decoded images in memory. It has no authentication, rate limiting, persistent storage or job queue. CORS permits public unauthenticated POST requests. Before exposing it to untrusted traffic, set request-body limits at the proxy/server (multipart parsing happens before the endpoint's upload check), restrict origins as appropriate, and size worker/concurrency limits for image rendering. A process crash can leave operating-system temporary files behind.

## License

No repository-wide license grant is currently specified. The previous README referenced an MIT `LICENSE` file that was absent; that unsupported claim has been removed. This update does not establish licensing terms for the project or bundled historical assets.
