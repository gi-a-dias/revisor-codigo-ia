# 1\. Imagem base oficial do Python

FROM python:3.12-slim

# 2\. Pasta de trabalho dentro do contêiner

WORKDIR /app

# 3\. Copiar os arquivos do projeto para o contêiner
COPY requirements.txt .

# 4\. Instalar as dependências
RUN pip install --no-cache-dir -r requirements.txt

# 5\. Copiar o restante do código e a pasta static
COPY . .

# 6\. Expor a porta em que a aplicação vai rodar
EXPOSE 8000

# 7\. Comando para iniciar o servidor Uvicorn/FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]