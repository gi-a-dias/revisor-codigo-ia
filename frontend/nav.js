/* Barra de navegação comum a todos os módulos (front-ends da plataforma).
 *
 * Como usar em qualquer módulo:
 *   1. copie este arquivo para a pasta do front-end;
 *   2. no <head>, antes do seu script:  <script>window.MODULO_ATUAL = 4;</script>
 *                                        <script defer src="nav.js"></script>
 *
 * Ela cria a barra sozinha (HTML + CSS) e segue o guia do Módulo 6: fundo
 * --color-primary, item ativo --color-primary-hover, uma só cor para todos os
 * módulos (o módulo é identificado por ícone + rótulo), claro e escuro. Para trocar um endereço, edite só MODULOS.
 * Módulos com endereço null aparecem desativados, sem link quebrado.
 */
(function () {
  const MODULOS = [
    { n: 1, icone: "▣", nome: "Projetos", url: "https://green-river-02e44e810.2.azurestaticapps.net/" },
    { n: 2, icone: "☍", nome: "GitHub Sync", url: "https://ai-platform-github-service-eduardo-frapb8fbbcd0bfdm.brazilsouth-01.azurewebsites.net/" },
    { n: 3, icone: "▤", nome: "Artefatos", url: "https://modulo3-fhgjdpa6d5bbfvff.canadacentral-01.azurewebsites.net/app/" },
    { n: 4, icone: "⚙", nome: "Code Review", url: "https://revisor-codigo-ia-gio-ach9dbg3g9ekazf3.chilecentral-01.azurewebsites.net/" },
    { n: 5, icone: "★", nome: "Curadoria", url: "https://frontmodulo5-ecaqg8fghzhyeuh2.brazilsouth-01.azurewebsites.net/" },
    { n: 6, icone: "✉", nome: "Notificações", url: null },
    { n: 7, icone: "✦", nome: "MackAI", url: "https://mackai-conversas.calmfield-d7c6c49f.brazilsouth.azurecontainerapps.io/" },
  ];

  const CSS = `
  .barra-modulos {
    position: sticky; top: 0; z-index: 50;
    display: flex; align-items: center; gap: 4px;
    padding: 0 16px; min-height: 48px; overflow-x: auto;
    background: var(--color-primary, #1E2A5A);
    border-bottom: 1px solid var(--color-primary-hover, #2F3F7F);
    font-family: var(--font-sans, system-ui, sans-serif);
    font-size: 14px; line-height: 1.2;
  }
  .barra-modulos .bm-marca {
    margin-right: 12px; padding-right: 16px; white-space: nowrap;
    color: var(--color-on-primary, #FFFFFF); font-weight: 600;
    border-right: 1px solid var(--color-primary-hover, #2F3F7F);
  }
  .barra-modulos .bm-marca span { color: var(--color-brand-accent, #C8102E); }
  .barra-modulos a, .barra-modulos .bm-off {
    display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
    padding: 8px 12px; border-radius: 8px; color: var(--color-on-primary, #FFFFFF); text-decoration: none;
  }
  .barra-modulos a:hover { background: var(--color-primary-hover, #2F3F7F); }
  .barra-modulos a[aria-current="page"] {
    background: var(--color-primary-hover, #2F3F7F); font-weight: 600;
  }
  .barra-modulos .bm-off { opacity: .55; cursor: not-allowed; }
  .barra-modulos .bm-i { opacity: .9; }
  .barra-modulos a:focus-visible { outline: 2px solid var(--color-on-primary, #FFFFFF); outline-offset: 2px; }
  `;

  function montar() {
    if (document.querySelector(".barra-modulos")) return;

    const atual = Number(window.MODULO_ATUAL);

    const estilo = document.createElement("style");
    estilo.textContent = CSS;
    document.head.appendChild(estilo);

    const nav = document.createElement("nav");
    nav.className = "barra-modulos";
    nav.setAttribute("aria-label", "Módulos da plataforma");

    const marca = document.createElement("span");
    marca.className = "bm-marca";
    marca.innerHTML = "Engenharia de Software<span>.</span>";
    nav.appendChild(marca);

    MODULOS.forEach((m) => {
      const rotulo = `<span class="bm-i" aria-hidden="true">${m.icone}</span> ${m.nome}`;
      let item;

      if (m.url) {
        item = document.createElement("a");
        item.href = m.url;
        if (m.n === atual) item.setAttribute("aria-current", "page");
      } else {
        item = document.createElement("span");
        item.className = "bm-off";
        item.title = "Endereço ainda não informado";
      }

      item.innerHTML = rotulo;
      nav.appendChild(item);
    });

    document.body.insertBefore(nav, document.body.firstChild);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", montar);
  } else {
    montar();
  }
})();