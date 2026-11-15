// Endereço do back-end (FastAPI).
//  - Front em http://127.0.0.1:3000 (python -m http.server): a API fica em :5000.
//  - Front servido pela própria API (SERVIR_FRONTEND=1, caso do Azure): mesmo
//    endereço, então fica vazio.
//  - Front hospedado em outro lugar: troque pela URL pública da API, por exemplo
//    "https://revisor-codigo-ia-gio.azurewebsites.net".
window.API_URL = location.port === "3000" ? "http://127.0.0.1:5000" : "";
