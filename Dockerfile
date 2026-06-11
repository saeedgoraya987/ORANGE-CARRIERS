FROM python:3.11-slim
RUN apt-get update && apt-get install -y chromium chromium-driver unzip
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "ivasms_auto.py"]
