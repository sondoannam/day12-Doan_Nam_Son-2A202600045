FROM python:3.11-slim
WORKDIR /app

COPY 05-scaling-reliability/develop/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install redis

COPY 05-scaling-reliability/production/app.py .

RUN mkdir -p utils
COPY utils/mock_llm.py ./utils/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]