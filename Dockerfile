# Use an official Python runtime as a parent image
# Choose a version compatible with your code (e.g., 3.11)
FROM python:3.11-slim-bookworm

# Set the working directory in the container
WORKDIR /app

# Install system dependencies including Tesseract OCR
# RUN performs commands during the image build process
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # Tesseract core and English language data
    tesseract-ocr \
    tesseract-ocr-eng \
    # Add other languages if needed, e.g., tesseract-ocr-fra
    # Clean up apt lists to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed Python packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Specify the command to run on container start
# This assumes your bot script is named bot.py
CMD ["python", "bot.py"]
