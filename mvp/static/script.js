const elemento = (id) => document.getElementById(id);

let revisaoAtual = null;

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

async function api(url, dados) {
  const resposta = await fetch(url, {
    method: dados ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    ...(dados ? { body: JSON.stringify(dados) } : {}),
  });

  const resultado = await resposta.json();

  if (!resposta.ok) {
    throw new Error(resultado.erro || "Não foi possível concluir.");
  }

  return resultado;
}

elemento("origem").addEventListener("change", () => {
  const github = elemento("origem").value === "github";
  elemento("entrada-codigo").hidden = github;
  elemento("entrada-github").hidden = !github;
});

elemento("exemplo").addEventListener("click", () => {
  elemento("caminho").value = "controllers/exemplo.py";
  elemento("codigo").value = exemplo;
  elemento("arquivos").value = "";
});

function mostrarAchados() {
  if (!revisaoAtual) return;

  const filtro = elemento("filtro").value;

  const achados = revisaoAtual.achados.filter(
    (item) => filtro === "Todos" || item.categoria === filtro
  );

  elemento("achados").className = "";

  if (!achados.length) {
    elemento("achados").innerHTML =
      '<p class="vazio">Nenhum achado nesta seleção. ' +
      "Isso não garante ausência de problemas.</p>";
    return;
  }

  const classes = { Alta: "alta", Média: "media", Baixa: "baixa" };

  elemento("achados").innerHTML = achados.map((item) => `
    <article class="achado">
      <span class="gravidade ${classes[item.gravidade]}">
        ${escapar(item.gravidade)} · ${escapar(item.categoria)}
      </span>
      <h3>${escapar(item.titulo)}</h3>
      <div class="local">
        ${escapar(item.arquivo)}
        ${item.linha ? ":" + escapar(item.linha) : ""}
      </div>
      <p class="sugestao">${escapar(item.sugestao)}</p>
    </article>
  `).join("");
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
        dados.arquivos = [];

        for (const arquivo of selecionados) {
          if (arquivo.size > 100000) {
            throw new Error("Um arquivo excede o limite de 100 KB.");
          }

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
          caminho: elemento("caminho").value.trim(),
          conteudo: elemento("codigo").value,
        }];
      }
    }

    const revisao = await api("/api/analisar", dados);

    elemento("filtro").value = "Todos";
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
        elemento("filtro").value = "Todos";
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
  elemento("modal").showModal();
});

elemento("fechar").addEventListener("click", () => {
  elemento("modal").close();
});

elemento("publicar").addEventListener("click", async () => {
  if (!revisaoAtual?.pr) return;

  const botao = elemento("publicar");
  botao.disabled = true;
  elemento("status-comentario").textContent = "Publicando…";

  try {
    await api(`/api/revisoes/${revisaoAtual.id}/comentar`, {});
    elemento("status-comentario").textContent =
      "Comentário publicado no Pull Request.";
  } catch (erro) {
    elemento("status-comentario").textContent = erro.message;
  } finally {
    botao.disabled = false;
  }
});

carregarHistorico();