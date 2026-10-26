import ast
from pathlib import PurePosixPath

# Regras simplificadas de dependência entre camadas.
REGRAS = {
    "multicamadas": [
        {
            "origem": "controllers/",
            "proibidos": ["repositories", "sqlite3", "psycopg2"],
            "motivo": "Controllers devem acessar serviços, não o banco diretamente.",
        },
        {
            "origem": "services/",
            "proibidos": ["controllers", "flask", "fastapi"],
            "motivo": "Serviços não devem depender da camada HTTP.",
        },
    ],
    "clean": [
        {
            "origem": "domain/",
            "proibidos": [
                "flask", "fastapi", "django",
                "requests", "sqlite3", "infrastructure",
            ],
            "motivo": "O domínio deve ser independente de infraestrutura.",
        },
        {
            "origem": "use_cases/",
            "proibidos": ["controllers", "flask", "fastapi"],
            "motivo": "Casos de uso não devem depender da apresentação.",
        },
    ],
}


def analisar(arquivos, arquitetura):
    achados = []

    def adicionar(arquivo, linha, categoria, gravidade, titulo, sugestao):
        achados.append({
            "arquivo": arquivo,
            "linha": linha,
            "categoria": categoria,
            "gravidade": gravidade,
            "titulo": titulo,
            "sugestao": sugestao,
        })

    testes = []

    for arquivo in arquivos:
        caminho = arquivo["caminho"]
        codigo = arquivo["conteudo"]
        nome = PurePosixPath(caminho).name

        if (
            nome.startswith("test_")
            or nome.endswith("_test.py")
            or "tests" in PurePosixPath(caminho).parts
        ):
            testes.append(caminho)

        try:
            arvore = ast.parse(codigo)
        except (SyntaxError, RecursionError, ValueError) as erro:
            adicionar(
                caminho,
                getattr(erro, "lineno", None),
                "Qualidade",
                "Alta",
                "Código não pôde ser interpretado como Python",
                "Confira a sintaxe antes de continuar a revisão.",
            )
            continue

        for no in ast.walk(arvore):
            linha = getattr(no, "lineno", None)

            # Procura chamadas como eval(), exec() e print().
            if isinstance(no, ast.Call):
                funcao = no.func

                if isinstance(funcao, ast.Name):
                    if funcao.id in {"eval", "exec"}:
                        adicionar(
                            caminho, linha, "Segurança", "Alta",
                            "Execução dinâmica de código",
                            "Evite eval/exec com entrada do usuário. "
                            "Use operações permitidas e validação.",
                        )

                    if funcao.id == "print":
                        adicionar(
                            caminho, linha, "Code smell", "Baixa",
                            "Saída de diagnóstico com print",
                            "Verifique se essa saída é necessária. "
                            "Considere logging com níveis.",
                        )

                for argumento in no.keywords:
                    if (
                        argumento.arg == "shell"
                        and isinstance(argumento.value, ast.Constant)
                        and argumento.value.value is True
                    ):
                        adicionar(
                            caminho, linha, "Segurança", "Alta",
                            "Uso de shell=True",
                            "Prefira argumentos separados e shell=False.",
                        )

            # Procura possíveis credenciais escritas diretamente.
            if isinstance(no, ast.Assign):
                valor = no.value

                if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
                    for destino in no.targets:
                        if isinstance(destino, ast.Name):
                            nome_variavel = destino.id.lower()

                            if (
                                any(
                                    palavra in nome_variavel
                                    for palavra in [
                                        "password", "senha", "secret",
                                        "token", "api_key",
                                    ]
                                )
                                and len(valor.value) >= 8
                            ):
                                adicionar(
                                    caminho, linha, "Segurança", "Alta",
                                    "Possível credencial no código",
                                    "Use variável de ambiente. Se a credencial "
                                    "for real, revogue-a. O valor foi omitido.",
                                )

            # Procura except sem especificar a exceção.
            if isinstance(no, ast.ExceptHandler) and no.type is None:
                adicionar(
                    caminho, linha, "Code smell", "Média",
                    "Tratamento de exceção amplo",
                    "Capture exceções específicas para facilitar o diagnóstico.",
                )

            # Procura funções muito extensas.
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tamanho = (no.end_lineno or no.lineno) - no.lineno + 1

                if tamanho > 50:
                    adicionar(
                        caminho, linha, "Code smell", "Média",
                        "Função com mais de 50 linhas",
                        "Verifique se a função pode ser dividida "
                        "em responsabilidades menores.",
                    )

            # Verifica imports contra as regras da arquitetura.
            modulos = []

            if isinstance(no, ast.Import):
                modulos = [item.name for item in no.names]

            elif isinstance(no, ast.ImportFrom):
                modulos = [no.module or ""]

            for regra in REGRAS[arquitetura]:
                if not caminho.startswith(regra["origem"]):
                    continue

                for modulo in modulos:
                    if any(
                        modulo == proibido
                        or modulo.startswith(proibido + ".")
                        for proibido in regra["proibidos"]
                    ):
                        adicionar(
                            caminho, linha, "Arquitetura", "Alta",
                            "Dependência fora da arquitetura planejada",
                            regra["motivo"],
                        )

        # Verificações simples por linha.
        for numero, texto in enumerate(codigo.splitlines(), start=1):
            if len(texto) > 120:
                adicionar(
                    caminho, numero, "Code smell", "Baixa",
                    "Linha com mais de 120 caracteres",
                    "Divida a expressão para melhorar a leitura.",
                )

            if "TODO" in texto or "FIXME" in texto:
                adicionar(
                    caminho, numero, "Code smell", "Baixa",
                    "Pendência registrada no código",
                    "Vincule a pendência a uma tarefa do backlog.",
                )

    if not testes:
        adicionar(
            "Conjunto analisado", None, "Testes", "Média",
            "Nenhum arquivo de teste identificado",
            "Inclua arquivos de teste na revisão. Isso não comprova "
            "que o repositório inteiro está sem testes.",
        )

    pesos = {"Alta": 12, "Média": 5, "Baixa": 2}
    achados.sort(key=lambda item: pesos[item["gravidade"]], reverse=True)

    return {
        "achados": achados,
        "arquivos": len(arquivos),
        "testes": testes,
        "testes_executados": False,
    }