const apiBaseUrl = window.__CONFIG__?.VITE_API_BASE_URL || "/api/v1";

fetch(`${apiBaseUrl}/products`)
  .then((response) => response.json())
  .then((products) => {
    document.querySelector("#app").textContent = `${products.length} products`;
  });
