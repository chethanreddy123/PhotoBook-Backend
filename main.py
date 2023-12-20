from fastapi import FastAPI, HTTPException, Form, UploadFile, File
import os
from PIL import Image
from fpdf import FPDF
import shutil
from  loguru import logger
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def resize_and_stretch_image(image_file, book_height_cm, num_pages, strip_width_cm):
    image = Image.open(image_file)
    aspect_ratio = image.width / image.height
    new_height_px = int(book_height_cm * 37.795275591)  # Convert cm to pixels
    total_width_cm = num_pages * strip_width_cm
    new_width_px = int(total_width_cm * 37.795275591)  # Convert total width from cm to pixels
    resized_image = image.resize((new_width_px, new_height_px), Image.LANCZOS)
    return resized_image

def create_pdf(resized_image, strip_width_cm, num_pages, output_folder):
    # Ensure the output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Constants for A4 size and margins
    A4_WIDTH_CM = 21
    MARGIN_CM = 1

    # Calculate the width of each strip in pixels
    strip_width_px = resized_image.width // num_pages

    pdf = FPDF(orientation='P', unit='cm', format='A4')
    pdf.add_page()  # Start by adding a new page
    x_position = MARGIN_CM
    y_position = MARGIN_CM

    # Iterate over each strip and add it to the PDF
    for strip in range(num_pages):
        if x_position + strip_width_cm > A4_WIDTH_CM - MARGIN_CM:
            pdf.add_page()
            x_position = MARGIN_CM

        # Calculate the bounding box for the strip
        left = strip * strip_width_px
        right = left + strip_width_px
        box = (left, 0, right, resized_image.height)

        # Cut the strip from the image and save
        strip_image = resized_image.crop(box)
        strip_path = os.path.join(output_folder, f'strip_{strip}.jpg')
        strip_image.save(strip_path)

        # Add the strip to the PDF
        pdf.image(strip_path, x=x_position, y=y_position, w=strip_width_cm)

        # Update the x_position for the next strip
        x_position += strip_width_cm + MARGIN_CM

    # Save the PDF
    pdf_path =  'output.pdf'
    pdf.output(pdf_path)
    return pdf_path



@app.post("/generate-pdf/")
async def generate_pdf(
    image: UploadFile = File(...),
    book_height_cm: float = Form(...),
    num_pages: int = Form(...),
    strip_width_cm: float = Form(...)
):
    
    output_folder = 'strips_output'
    temp_image_path = None  # Initialize temp_image_path

    logger.info(f"book_height_cm: {book_height_cm}")

    try:
        # Save the uploaded image to a temporary file
        temp_image_path = f"temp_{image.filename}"
        print(temp_image_path)
        with open(temp_image_path, "wb") as temp_file:
            content = await image.read()  # Read the content of the uploaded file
            temp_file.write(content)

        # Resize and stretch the image
        resized_image = resize_and_stretch_image(temp_image_path, book_height_cm, num_pages, strip_width_cm)

        # Create the PDF with the strips
        pdf_path = create_pdf(resized_image, strip_width_cm, num_pages, output_folder)

        logger.info(f"pdf_path: {pdf_path}")

        if temp_image_path:
            os.remove(temp_image_path)

        logger.info(f"output_folder: {output_folder}")

        response = FileResponse("output.pdf")

        return response

    except Exception as e:
        # Clean up in case of error
        if temp_image_path and os.path.exists(temp_image_path):
            os.remove(temp_image_path)
        if os.path.exists(output_folder):
            shutil.rmtree(output_folder)
        raise HTTPException(status_code=500, detail=str(e))
