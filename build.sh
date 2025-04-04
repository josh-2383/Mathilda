#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Starting build script..."

# Update package list and install Tesseract OCR engine + English language pack
# Add other languages if needed e.g., tesseract-ocr-fra for French
echo "Installing Tesseract OCR..."
apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng

# Install Python dependencies from requirements.txt
echo "Installing Python packages..."
pip install -r requirements.txt

echo "Build script finished successfully!"
