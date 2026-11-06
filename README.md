Revisor de Código com IA
Microsserviço responsável pela análise automatizada de código enviado por meio de Pull Requests.
Objetivos
- identificar problemas de qualidade;
- detectar possíveis vulnerabilidades;
- verificar a existência de testes;
- identificar code smells;
- avaliar a conformidade arquitetural;
- gerar sugestões de correção com Inteligência Artificial.
Integrantes
- Sophia Betoni
- Gi A. Dias
Executar no Windows
No PowerShell do VS Code, a partir da raiz do repositório:
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item mvp/.env.example mvp/.env
.\.venv\Scripts\python.exe mvp/app.py
Abra http://127.0.0.1:5000. Se já tiver um arquivo
mvp/.env, preserve seus valores e adicione apenas as variáveis que faltam.
- Para análise estática de arquivos Python e PRs públicos, as chaves são opcionais.
- Para habilitar o Especialista Virtual, configure GEMINI_API_KEY e GEMINI_MODEL.
- Para publicar revisões, configure GITHUB_TOKEN com permissão de escrita em
  Pull requests e de leitura em Contents nos repositórios analisados.
  Configure também REVIEW_ACCESS_KEY com uma senha forte. O navegador vai
  pedir o usuário revisor e essa senha. Com token GitHub, a senha é obrigatória.
- No Azure, configure essas variáveis nas configurações do App Service e use HTTPS.
  O comando de inicialização, a partir da raiz, é
  gunicorn --chdir mvp --bind 0.0.0.0:8000 --timeout 120 app:app.
  Use DATABASE_PATH em um diretório persistente se precisar preservar o histórico
  entre implantações.
O serviço analisa até 20 arquivos Python e 100 KB de código por revisão. As
regras arquiteturais são heurísticas para Multicamadas e Clean Architecture.
A identificação de arquivos de teste usa o nome e o caminho.
Executar os testes
$env:PYTHONPATH = "mvp"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Os testes usam banco temporário e simulam as APIs externas.

## Integrantes

- Sophia Betoni
- Gi A. Dias

## Status

Projeto em fase inicial de desenvolvimento.