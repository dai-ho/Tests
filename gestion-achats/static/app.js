// Filtre texte et tri par colonne pour toutes les tables marquées data-tableau.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("input[data-filtre]").forEach((champ) => {
    const table = document.getElementById(champ.dataset.filtre);
    const compteur = document.getElementById(champ.dataset.filtre + "-compteur");
    const appliquer = () => {
      const mots = champ.value.toLowerCase().split(/\s+/).filter(Boolean);
      let visibles = 0;
      table.querySelectorAll("tbody tr").forEach((tr) => {
        const texte = tr.textContent.toLowerCase();
        const ok = mots.every((m) => texte.includes(m));
        tr.hidden = !ok;
        if (ok) visibles++;
      });
      if (compteur) compteur.textContent = visibles + " ligne(s)";
    };
    champ.addEventListener("input", appliquer);
    appliquer();
  });

  document.querySelectorAll("th[data-tri]").forEach((th) => {
    th.addEventListener("click", () => {
      const table = th.closest("table");
      const index = Array.from(th.parentNode.children).indexOf(th);
      const sens = th.classList.contains("asc") ? -1 : 1;
      table.querySelectorAll("th[data-tri]").forEach((x) => x.classList.remove("asc", "desc"));
      th.classList.add(sens === 1 ? "asc" : "desc");
      const valeur = (tr) => {
        const td = tr.children[index];
        return td ? (td.dataset.valeur ?? td.textContent.trim()) : "";
      };
      const corps = table.tBodies[0];
      Array.from(corps.rows)
        .sort((a, b) => {
          const va = valeur(a), vb = valeur(b);
          const na = Number(va), nb = Number(vb);
          if (va !== "" && vb !== "" && !isNaN(na) && !isNaN(nb)) return (na - nb) * sens;
          return va.localeCompare(vb, "fr", { numeric: true }) * sens;
        })
        .forEach((tr) => corps.appendChild(tr));
    });
  });

  document.querySelectorAll("form[data-confirmer]").forEach((f) =>
    f.addEventListener("submit", (e) => { if (!confirm(f.dataset.confirmer)) e.preventDefault(); })
  );
});
