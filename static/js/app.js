// Alexandria Web — comportamentos do lado do cliente (JavaScript puro)
document.addEventListener("DOMContentLoaded", () => {
  // Pede confirmação antes de ações que não podem ser desfeitas
  document.querySelectorAll("form[data-confirmar]").forEach((form) => {
    form.addEventListener("submit", (ev) => {
      if (!window.confirm(form.dataset.confirmar)) ev.preventDefault();
    });
  });

  // Empréstimo: calcula a devolução prevista pelo prazo do tipo de leitor (14 ou 21 dias)
  const pessoa = document.getElementById("sel-pessoa");
  const retirada = document.getElementById("retirada");
  const previsto = document.getElementById("previsto");
  if (pessoa && retirada && previsto) {
    const atualizar = () => {
      const opcao = pessoa.selectedOptions[0];
      const dias = Number(opcao && opcao.dataset.prazo) || 14;
      const d = new Date(retirada.value + "T12:00:00");
      if (isNaN(d)) return;
      d.setDate(d.getDate() + dias);
      previsto.value = d.toISOString().slice(0, 10);
    };
    pessoa.addEventListener("change", atualizar);
    retirada.addEventListener("change", atualizar);
    atualizar();
  }

  // Cadastro de obra: pré-visualização da capa em tempo real
  const capa = document.querySelector(".previa .capa");
  if (capa) {
    const titulo = capa.querySelector(".capa-titulo");
    const autor = capa.querySelector(".capa-autor");
    document.querySelectorAll("[data-previa]").forEach((campo) => {
      campo.addEventListener("input", () => {
        const alvo = campo.dataset.previa === "titulo" ? titulo : autor;
        alvo.textContent = campo.value || (campo.dataset.previa === "titulo" ? "Título da obra" : "Autor");
      });
    });
    document.querySelectorAll("input[name=tom]").forEach((r) => {
      r.addEventListener("change", () => {
        capa.className = capa.className.replace(/tom-\w+/, "tom-" + r.value.toLowerCase());
      });
    });
  }
});
