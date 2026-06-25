# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install Tesseract OCR and FFmpeg (This works perfectly inside Docker)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY app.py .

# Run the bot
CMD ["python", "app.py"]
