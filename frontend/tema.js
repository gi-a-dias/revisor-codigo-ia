// Tema claro/escuro. O padrão é o claro (base do guia do Módulo 6);
// a escolha fica salva neste navegador. Carregado no <head> para não piscar.
(function () {
  let salvo = null;
  try { salvo = localStorage.getItem("tema"); } catch { /* sem armazenamento */ }

  const aplicar = (tema) => { document.documentElement.dataset.theme = tema; };
  aplicar(salvo === "dark" ? "dark" : "light");

  document.addEventListener("DOMContentLoaded", () => {
    const botao = document.getElementById("tema");
    if (!botao) return;

    const atualizar = () => {
      const escuro = document.documentElement.dataset.theme === "dark";
      botao.textContent = escuro ? "☀ Modo claro" : "☾ Modo escuro";
      botao.setAttribute("aria-pressed", String(escuro));
    };

    botao.addEventListener("click", () => {
      const novo = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      aplicar(novo);
      try { localStorage.setItem("tema", novo); } catch { /* sem armazenamento */ }
      atualizar();
    });

    atualizar();
  });
})();
