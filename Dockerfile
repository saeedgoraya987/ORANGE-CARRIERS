FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Extract if needed
RUN if [ -f "ivasms_auto_Script.zip" ]; then unzip -o ivasms_auto_Script.zip; fi

RUN pip install -r requirements.txt

CMD ["python", "ivasms_auto.py"]
