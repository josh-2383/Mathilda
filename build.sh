#!/usr/bin/env bash
# exit on error
set -o errexit

echo "--- Installing Python Dependencies ---"
pip install -r requirements.txt

echo "--- Installing Tesseract OCR ---"
apt-get update # Update package list
# Install tesseract and the English language pack (-y accepts prompts automatically)
apt-get install -y tesseract-ocr tesseract-ocr-eng
# Add other language packs if needed, e.g., tesseract-ocr-spa for Spanish:
# apt-get install -y tesseract-ocr-spa tesseract-ocr-fra ...

# Optional: Clean up apt cache to reduce slug size
apt-get clean && rm -rf /var/lib/apt/lists/*

echo "--- Build Complete ---"
