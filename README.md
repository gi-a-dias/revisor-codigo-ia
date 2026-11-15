# Revisor de Código com IA — Módulo 4

Microsserviço responsável pela análise automatizada de código enviado por meio de Pull Requests.

## Integrantes

- Sophia Betoni
- Gi A. Dias

## Objetivos

- identificar problemas de qualidade;
- detectar possíveis vulnerabilidades;
- verificar a existência de testes;
- identificar code smells;
- avaliar a conformidade arquitetural;
- gerar sugestões de correção com Inteligência Artificial.

## Estrutura

```
backend/    API FastAPI (análise, integração com GitHub e Gemini, histórico)
frontend/   Interface web estática (HTML, CSS e JS), que consome a API
tests/      Testes automatizados do back-end
```

O visual segue o **Guia de Identidade Visual do Módulo 6** (tokens em
`frontend/tokens.css`, fontes Inter e JetBrains Mono, prioridade por cor) e
tem modo claro e escuro. O claro é o padrão; a escolha fica salva no navegador.

O front-end e o back-end são independentes: o front só conversa com a API REST
(`/api/*`), e o endereço da API é definido em `frontend/config.js`.

## Executar no Windows

No PowerShell do VS Code, a partir da raiz do repositório:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item backend/.env.example backend/.env
```

**Terminal 1: back-end** (http://127.0.0.1:5000, documentação em `/docs`):

```powershell
.\.venv\Scripts\python.exe backend/app.py
```

**Terminal 2: front-end** (http://127.0.0.1:3000):

```powershell
.\.venv\Scripts\python.exe -m http.server 3000 --directory frontend
```

Abra http://127.0.0.1:3000. Se já tiver um `backend/.env`, preserve seus valores
e adicione apenas as variáveis que faltam.

## Configuração (`backend/.env`)

- Para análise estática de arquivos Python e PRs públicos, as chaves são opcionais.
- Para habilitar o Especialista Virtual, configure `GEMINI_API_KEY` e `GEMINI_MODEL`.
- Para publicar revisões, configure `GITHUB_TOKEN` com permissão de escrita em
  Pull requests e de leitura em Contents nos repositórios analisados.
  Configure também `REVIEW_ACCESS_KEY` com uma senha forte. A tela do front
  pede o usuário `revisor` e essa senha. Com token GitHub, a senha é obrigatória.
- `SERVIR_FRONTEND=1` faz a API entregar também a interface (veja Publicação).
- `CORS_ORIGINS` lista os endereços do front-end autorizados a chamar a API
  (separados por vírgula). Em produção, use a URL onde o front estiver hospedado.

## Publicação (Azure)

**Back-end (App Service).** Configure as variáveis acima nas configurações do
App Service e use HTTPS. O comando de inicialização, a partir da raiz, é:

```
python -m uvicorn --app-dir backend app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
```

Use `DATABASE_PATH` em um diretório persistente se precisar preservar o
histórico entre implantações.

**Front-end.** Há duas opções:

1. **Um deploy só (recomendado):** nas configurações do App Service, crie a
   variável `SERVIR_FRONTEND` com o valor `1`. A própria API passa a entregar a
   pasta `frontend/`, e o endereço do App Service abre a interface. A página
   abre sem senha (para mostrar a tela de login) e a API continua protegida.
   Nesse caso o `config.js` não precisa de ajuste.
2. **Front hospedado à parte:** publique `frontend/` em um serviço de arquivos
   estáticos (Azure Static Web Apps, GitHub Pages etc.), troque `API_URL` em
   `frontend/config.js` pela URL pública da API e inclua a URL do front em
   `CORS_ORIGINS`.

Para testar a opção 1 localmente, sem o segundo terminal:

```powershell
$env:SERVIR_FRONTEND = "1"
.\.venv\Scripts\python.exe backend/app.py
```

Abra http://127.0.0.1:5000.

## Limites e regras

O serviço analisa até 20 arquivos Python e 100 KB de código por revisão. As
regras arquiteturais são heurísticas para Multicamadas, Clean Architecture, MVC,
Hexagonal e Onion. A identificação de arquivos de teste usa o nome e o caminho.

## Executar os testes

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes usam banco temporário e simulam as APIs externas.
