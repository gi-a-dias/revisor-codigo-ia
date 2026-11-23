// Gráficos do módulo 4 para embutir no dashboard do Módulo 6.
// Uso: graficos.html?project_id=<uuid>&dias=14&tema=dark
// Lê /api/dashboard/metricas (só contagens, sem senha).
(function () {
  const consulta = new URLSearchParams(location.search);
  const tema = consulta.get("tema");
  if (tema === "dark" || tema === "light") document.documentElement.dataset.theme = tema;

  const PRIORIDADES = [
    ["critical", "Crítica", "var(--color-priority-critical)"],
    ["high", "Alta", "var(--color-priority-high)"],
    ["medium", "Média", "var(--color-priority-medium)"],
    ["low", "Baixa", "var(--color-priority-low)"],
  ];
  const CORES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
  const ESTILOS = {
    multicamadas: "Multicamadas", clean: "Clean", mvc: "MVC",
    hexagonal: "Hexagonal", onion: "Onion",
  };

  const $ = (id) => document.getElementById(id);
  const el = (tag, classe, texto) => {
    const n = document.createElement(tag);
    if (classe) n.className = classe;
    if (texto !== undefined) n.textContent = texto;
    return n;
  };

  function barras(alvo, linhas) {
    alvo.replaceChildren();
    const maior = Math.max(1, ...linhas.map((l) => l.valor));
    if (!linhas.some((l) => l.valor > 0)) {
      alvo.append(el("p", "vazio", "Ainda não há dados."));
      return;
    }
    const grade = el("div", "barras");
    for (const l of linhas) {
      const linha = el("div", "barra");
      const rot = el("span", "rot", l.rotulo);
      rot.title = l.rotulo;
      const trilho = el("div", "trilho");
      const p = el("div", "preench");
      p.style.width = `${(l.valor / maior) * 100}%`;
      p.style.background = l.cor;
      if (l.valor === 0) p.style.minWidth = "0";
      trilho.append(p);
      linha.append(rot, trilho, el("span", "num", String(l.valor)));
      grade.append(linha);
    }
    alvo.append(grade);
  }

  function colunas(alvo, dias) {
    alvo.replaceChildren();
    if (!dias.some((d) => d.revisoes > 0)) {
      alvo.append(el("p", "vazio", "Nenhuma revisão no período."));
      return;
    }
    const maior = Math.max(1, ...dias.map((d) => d.revisoes));
    const topo = el("div", "colunas");
    const eixo = el("div", "eixo");
    const passo = Math.ceil(dias.length / (innerWidth < 520 ? 5 : 10));
    dias.forEach((d, i) => {
      const c = el("div", d.revisoes ? "coluna" : "coluna zero");
      c.title = `${d.data}: ${d.revisoes} revisão(ões), ${d.achados} achado(s)`;
      if (d.revisoes) c.append(el("b", "", String(d.revisoes)));
      const barra = el("i");
      barra.style.height = `${Math.max(2, (d.revisoes / maior) * 100)}%`;
      if (d.revisoes) c.style.height = "100%";
      c.append(barra);
      topo.append(c);
      eixo.append(el("span", "", (dias.length - 1 - i) % passo === 0 ? d.data.slice(8) + "/" + d.data.slice(5, 7) : ""));
    });
    alvo.append(topo, eixo);
  }

  function pintar(d) {
    $("k-rev").textContent = d.total_revisoes;
    $("k-ach").textContent = d.total_achados;
    $("k-crit").textContent = (d.por_prioridade.critical || 0) + (d.por_prioridade.high || 0);

    const escopo = d.project_id ? "deste projeto" : "de todos os projetos";
    $("g-sub").textContent =
      `Dados ${escopo}, últimos ${d.revisoes_por_dia.length} dias. Atualizado em ${new Date(d.gerado_em).toLocaleString("pt-BR")}.`;

    barras($("c-prio"), PRIORIDADES.map(([k, rotulo, cor]) => ({
      rotulo, valor: d.por_prioridade[k] || 0, cor,
    })));

    colunas($("c-dia"), d.revisoes_por_dia);

    barras($("c-cat"), Object.entries(d.por_categoria)
      .sort((a, b) => b[1] - a[1])
      .map(([rotulo, valor], i) => ({ rotulo, valor, cor: CORES[i % CORES.length] })));

    barras($("c-arq"), Object.entries(d.por_arquitetura || {})
      .sort((a, b) => b[1] - a[1])
      .map(([k, valor], i) => ({ rotulo: ESTILOS[k] || k, valor, cor: CORES[i % CORES.length] })));
  }

  async function carregar() {
    const erro = $("g-erro");
    const q = new URLSearchParams();
    if (consulta.get("project_id")) q.set("project_id", consulta.get("project_id"));
    if (consulta.get("dias")) q.set("dias", consulta.get("dias"));
    try {
      const r = await fetch(`${window.API_URL || ""}/api/dashboard/metricas?${q}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      pintar(await r.json());
      erro.hidden = true;
    } catch (e) {
      erro.textContent = `Não foi possível carregar os gráficos (${e.message}).`;
      erro.hidden = false;
      $("g-sub").textContent = "";
    }
  }

  carregar();
  setInterval(carregar, 60000);
})();
