FROM python:3.12-slim

# Tools a general-purpose agent can use to read the documents: pdfplumber (PDF text layer)
# and RapidOCR (scanned images). Headless OpenCV, so no system libraries are needed.
RUN pip install --no-cache-dir pdfplumber==0.11.7 opencv-python-headless==4.11.0.86 \
        onnxruntime==1.22.1 pyclipper==1.3.0.post6 shapely==2.1.1 six PyYAML Pillow numpy \
    && pip install --no-cache-dir --no-deps rapidocr_onnxruntime==1.4.4

WORKDIR /app
COPY documents/ /app/documents/
COPY questions.json /app/questions.json
