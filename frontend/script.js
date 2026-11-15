const elemento = (id) => document.getElementById(id);

let revisaoAtual = null;
const revisoesPublicadas = new Set();

const exemplo = `from repositories.usuario_repository import salvar

def cadastrar(dados):
    senha = "senha_ficticia_123"
    resultado = eval(dados)

    try:
        salvar(resultado)
    except:
        print("Erro ao salvar")

    return resultado
`;

// Evita interpretar texto do código como HTML.
function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = String(texto ?? "");
  return div.innerHTML;
}

const API_URL = (window.API_URL || "").replace(/\/+$/, "");

// Credenciais ficam só na sessão da aba (some ao fechar o navegador).
let credenciais = sessionStorage.getItem("credenciais");

function codificarCredenciais(usuario, senha) {
  const bytes = new TextEncoder().encode(`${usuario}:${senha}`);
  return btoa(String.fromCharCode(...bytes));
}

// Abre a tela de login e devolve uma promessa com as credenciais digitadas.
function pedirLogin(mensagem = "") {
  return new Promise((resolver, rejeitar) => {
    const dialogo = elemento("login");
    const entrar = elemento("login-entrar");
    const cancelar = elemento("login-cancelar");
    const senha = elemento("login-senha");

    elemento("login-status").textContent = mensagem;
    senha.value = "";

    const limpar = () => {
      entrar.removeEventListener("click", aoEntrar);
      cancelar.removeEventListener("click", aoCancelar);
      dialogo.removeEventListener("cancel", aoCancelar);
      dialogo.close();
    };

    const aoEntrar = () => {
      if (!senha.value) {
        elemento("login-status").textContent = "Informe a senha.";
        return;
      }
      const valor = codificarCredenciais(elemento("login-usuario").value.trim(), senha.value);
      limpar();
      resolver(valor);
    };

    const aoCancelar = () => {
      limpar();
      rejeitar(new Error("Login necessário para usar o serviço."));
    };

    entrar.addEventListener("click", aoEntrar);
    cancelar.addEventListener("click", aoCancelar);
    dialogo.addEventListener("cancel", aoCancelar);
    dialogo.showModal();
    senha.focus();
  });
}

async function requisitar(url, dados) {
  const headers = { "Content-Type": "application/json" };
  if (credenciais) headers.Authorization = `Basic ${credenciais}`;

  try {
    return await fetch(API_URL + url, {
      method: dados ? "POST" : "GET",
      headers,
      ...(dados ? { body: JSON.stringify(dados) } : {}),
    });
  } catch {
    throw new Error(
      "Não foi possível conectar ao serviço de revisão. " +
      "Confira se o back-end está no ar e o endereço em config.js."
    );
  }
}

async function api(url, dados) {
  let resposta = await requisitar(url, dados);

  // 401: pede usuário e senha (de novo, se a senha anterior falhou) e repete.
  while (resposta.status === 401) {
    const falhou = Boolean(credenciais);
    credenciais = null;
    sessionStorage.removeItem("credenciais");

    credenciais = await pedirLogin(falhou ? "Usuário ou senha incorretos." : "");
    sessionStorage.setItem("credenciais", credenciais);
    resposta = await requisitar(url, dados);
  }

  const resultado = await resposta.json().catch(() => null);

  if (!resposta.ok) {
    throw new Error(resultado?.erro || `Não foi possível concluir (HTTP ${resposta.status}).`);
  }

  if (resultado === null) {
    throw new Error("O servidor retornou uma resposta inválida.");
  }

  return resultado;
}

elemento("origem").addEventListener("change", () => {
  const github = elemento("origem").value === "github";
  elemento("entrada-codigo").hidden = github;
  elemento("entrada-github").hidden = !github;
});

elemento("exemplo").addEventListener("click", () => {
  elemento("codigo").value = exemplo;
  elemento("arquivos").value = "";
});

// Guia do Módulo 6: a cor indica a prioridade; o ícone e o rótulo indicam a origem.
// Falha de segurança grave é "Crítica"; as demais seguem a gravidade da análise.
const ORIGENS = {
  "Segurança": { icone: "⚠" },
  "Code smell": { icone: "☰" },
  "Arquitetura": { icone: "◫" },
  "Testes": { icone: "✓" },
  "Qualidade": { icone: "◆" },
};

function nivelDeprioridade(item) {
  if (item.categoria === "Segurança" && item.gravidade === "Alta") {
    return { classe: "critical", rotulo: "Crítica" };
  }
  if (item.gravidade === "Alta") return { classe: "high", rotulo: "Alta" };
  if (item.gravidade === "Média") return { classe: "medium", rotulo: "Média" };
  return { classe: "low", rotulo: "Baixa" };
}

// Minúsculas e sem acento, para "excecao" achar "exceção".
function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function filtrosAtivos() {
  return (
    elemento("busca").value.trim() !== "" ||
    elemento("filtro").value !== "Todos" ||
    elemento("filtro-prioridade").value !== "Todas"
  );
}

function limparFiltros() {
  elemento("busca").value = "";
  elemento("filtro").value = "Todos";
  elemento("filtro-prioridade").value = "Todas";
}

// Todas as palavras digitadas precisam aparecer em algum campo do achado.
function combinaComBusca(item, termos) {
  if (!termos.length) return true;

  const nivel = nivelDeprioridade(item);
  const palheiro = normalizar([
    item.titulo,
    item.sugestao,
    item.categoria,
    item.arquivo,
    item.linha ? `${item.arquivo}:${item.linha}` : "",
    nivel.rotulo,
    item.gravidade,
  ].join(" "));

  return termos.every((termo) => palheiro.includes(termo));
}

function mostrarAchados() {
  if (!revisaoAtual) return;

  const categoria = elemento("filtro").value;
  const prioridade = elemento("filtro-prioridade").value;
  const termos = normalizar(elemento("busca").value).split(/\s+/).filter(Boolean);

  const total = revisaoAtual.achados.length;
  const achados = revisaoAtual.achados.filter((item) =>
    (categoria === "Todos" || item.categoria === categoria) &&
    (prioridade === "Todas" || nivelDeprioridade(item).rotulo === prioridade) &&
    combinaComBusca(item, termos)
  );

  const ativos = filtrosAtivos();
  elemento("limpar-filtros").hidden = !ativos;
  elemento("contagem").textContent = ativos
    ? `Mostrando ${achados.length} de ${total} ${total === 1 ? "achado" : "achados"}.`
    : "";

  elemento("achados").className = "";

  if (!achados.length) {
    elemento("achados").innerHTML = ativos
      ? '<p class="vazio">Nenhum achado corresponde aos filtros.</p>'
      : '<p class="vazio">Nenhum achado nesta revisão. ' +
        "Isso não garante ausência de problemas.</p>";
    return;
  }

  elemento("achados").innerHTML = achados.map((item) => {
    const nivel = nivelDeprioridade(item);
    const origem = ORIGENS[item.categoria] || { icone: "•" };

    return `
    <article class="achado ${nivel.classe}">
      <div class="achado-topo">
        <span class="selo">${nivel.rotulo}</span>
        <span class="origem"><span aria-hidden="true">${origem.icone}</span> ${escapar(item.categoria)}</span>
      </div>
      <h3>${escapar(item.titulo)}</h3>
      <div class="local">
        ${escapar(item.arquivo)}${item.linha ? ":" + escapar(item.linha) : ""}
      </div>
      <p class="sugestao">${escapar(item.sugestao)}</p>
    </article>
  `;
  }).join("");
}

function mostrarRevisao(revisao) {
  revisaoAtual = revisao;

  elemento("total-arquivos").textContent = revisao.arquivos;
  elemento("total-achados").textContent = revisao.achados.length;
  elemento("total-testes").textContent = revisao.testes.length;

  const origem = revisao.pr
    ? `PR #${revisao.pr.numero} · ${revisao.pr.titulo}`
    : "Revisão de arquivos";

  elemento("contexto").textContent =
    `${origem} · ${revisao.arquitetura} · ` +
    new Date(revisao.criado_em).toLocaleString("pt-BR");

  elemento("painel-ia").hidden = false;
  elemento("ia-status").textContent = revisao.ia.status;
  elemento("ia-texto").textContent = revisao.ia.texto;
  elemento("acoes").hidden = false;
  elemento("previa").hidden = !revisao.pr;

  mostrarAchados();
}

elemento("filtro").addEventListener("change", mostrarAchados);
elemento("filtro-prioridade").addEventListener("change", mostrarAchados);
elemento("busca").addEventListener("input", mostrarAchados);
elemento("busca").addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && elemento("busca").value) {
    elemento("busca").value = "";
    mostrarAchados();
  }
});
elemento("limpar-filtros").addEventListener("click", () => {
  limparFiltros();
  mostrarAchados();
  elemento("busca").focus();
});

elemento("analisar").addEventListener("click", async () => {
  const botao = elemento("analisar");
  botao.disabled = true;
  elemento("status").textContent =
    "Analisando… As integrações podem levar alguns segundos.";

  try {
    const dados = {
      arquitetura: elemento("arquitetura").value,
      usar_ia: elemento("usar-ia").checked,
    };

    if (elemento("origem").value === "github") {
      dados.pr_url = elemento("pr-url").value.trim();

      if (!dados.pr_url) {
        throw new Error("Informe o link do Pull Request.");
      }
    } else {
      const selecionados = Array.from(elemento("arquivos").files);

      if (selecionados.length) {
        if (selecionados.length > 20) {
          throw new Error("Selecione até 20 arquivos Python.");
        }

        if (selecionados.reduce((total, arquivo) => total + arquivo.size, 0) > 100000) {
          throw new Error("Os arquivos juntos excedem o limite de 100 KB.");
        }

        dados.arquivos = [];

        for (const arquivo of selecionados) {
          dados.arquivos.push({
            caminho: arquivo.name,
            conteudo: await arquivo.text(),
          });
        }
      } else {
        if (!elemento("codigo").value.trim()) {
          throw new Error("Cole um código ou carregue o exemplo.");
        }

        dados.arquivos = [{
          caminho: "trecho.py",
          conteudo: elemento("codigo").value,
        }];
      }
    }

    const revisao = await api("/api/analisar", dados);

    limparFiltros();
    mostrarRevisao(revisao);
    elemento("status").textContent = "Análise concluída.";
    await carregarHistorico();
  } catch (erro) {
    elemento("status").textContent = erro.message;
  } finally {
    botao.disabled = false;
  }
});

async function carregarHistorico() {
  try {
    const revisoes = await api("/api/historico");
    const container = elemento("historico");
    container.replaceChildren();

    if (!revisoes.length) {
      container.textContent = "Nenhuma revisão salva ainda.";
      return;
    }

    for (const revisao of revisoes) {
      const linha = document.createElement("div");
      linha.className = "item-historico";

      const descricao = document.createElement("span");
      descricao.textContent =
        `${new Date(revisao.criado_em).toLocaleString("pt-BR")} · ` +
        `${revisao.achados.length} achados · ${revisao.arquitetura}`;

      const botao = document.createElement("button");
      botao.className = "secundario";
      botao.textContent = "Abrir";

      botao.addEventListener("click", () => {
        limparFiltros();
        mostrarRevisao(revisao);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });

      linha.append(descricao, botao);
      container.append(linha);
    }
  } catch (erro) {
    elemento("historico").textContent = erro.message;
  }
}

elemento("exportar").addEventListener("click", () => {
  if (!revisaoAtual) return;

  const arquivo = new Blob(
    [revisaoAtual.markdown],
    { type: "text/markdown;charset=utf-8" }
  );

  const url = URL.createObjectURL(arquivo);
  const link = document.createElement("a");
  link.href = url;
  link.download = `revisao-${revisaoAtual.id}.md`;
  link.click();

  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

elemento("previa").addEventListener("click", () => {
  if (!revisaoAtual?.pr) return;

  elemento("destino").textContent = revisaoAtual.pr.url;
  elemento("comentario").value = revisaoAtual.markdown;
  elemento("status-comentario").textContent = "";
  elemento("publicar").disabled = revisoesPublicadas.has(revisaoAtual.id);
  elemento("modal").showModal();
});

elemento("modal").addEventListener("cancel", (evento) => {
  if (elemento("fechar").disabled) evento.preventDefault();
});

elemento("fechar").addEventListener("click", () => {
  elemento("modal").close();
});

elemento("publicar").addEventListener("click", async () => {
  if (!revisaoAtual?.pr) return;

  const botao = elemento("publicar");
  botao.disabled = true;
  elemento("fechar").disabled = true;
  elemento("status-comentario").textContent = "Publicando…";

  try {
    const id = revisaoAtual.id;
    await api(`/api/revisoes/${id}/comentar`, {});
    revisoesPublicadas.add(id);
    elemento("status-comentario").textContent =
      "Comentário publicado no Pull Request.";
  } catch (erro) {
    elemento("status-comentario").textContent = erro.message;
    botao.disabled = false;
  } finally {
    elemento("fechar").disabled = false;
  }
});

carregarHistorico();