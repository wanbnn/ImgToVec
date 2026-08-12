"""Interface declarativa construída com PyReact, UIKitPR e 6cons."""

from pyreact import h
from sixcons import icon
from uikitpr import Card, CardBody, Heading, Stack, UIProvider


def Icon(name, size=20, class_name="icon"):
    return icon(name, size=size, stroke_width=1.8, class_name=class_name)


def App(_props):
    content = h(
        "main",
        {"className": "shell"},
        h(
            "header",
            {"className": "topbar"},
            h("a", {"href": "/", "className": "brand"}, h("span", {"className": "brand-mark"}, Icon("scan-search", 21)), "research"),
            h("div", {"className": "status-pill"}, h("span", {"className": "status-dot"}), "pgvector conectado"),
        ),
        h(
            "section",
            {"className": "hero"},
            h("span", {"className": "eyebrow"}, "Visual similarity engine"),
            Heading("Encontre um frame a partir de qualquer imagem.", level=1, class_name="hero-title"),
            h("p", {"className": "hero-copy"}, "Envie uma referência. O Nomic Vision transforma os pixels em um vetor e pesquisa os frames mais próximos no PostgreSQL."),
        ),
        h(
            "section",
            {"className": "workspace"},
            Card(
                CardBody(
                    Stack(
                        h(
                            "div",
                            {"className": "search-modes", "role": "tablist", "aria-label": "Tipo de busca"},
                            h("button", {"className": "mode-button is-active", "data-mode": "image", "role": "tab", "aria-selected": "true"}, Icon("image", 17), "Imagem"),
                            h("button", {"className": "mode-button", "data-mode": "text", "role": "tab", "aria-selected": "false"}, Icon("text-search", 17), "Texto"),
                        ),
                        h(
                            "div",
                            {"className": "panel-heading"},
                            h("span", {"className": "step"}, "01"),
                            h("div", None, h("strong", {"id": "input-title"}, "Imagem de referência"), h("small", {"id": "input-help"}, "PNG, JPG ou WebP · até 15 MB")),
                        ),
                        h(
                            "label",
                            {"className": "dropzone", "id": "dropzone", "for": "image-input"},
                            h("input", {"id": "image-input", "type": "file", "accept": "image/png,image/jpeg,image/webp", "hidden": True}),
                            h("img", {"id": "query-preview", "className": "query-preview", "alt": "Prévia da imagem enviada", "hidden": True}),
                            h("div", {"id": "drop-copy", "className": "drop-copy"}, h("span", {"className": "upload-icon"}, Icon("image-up", 30)), h("strong", None, "Arraste uma imagem aqui"), h("span", None, "ou clique para selecionar")),
                        ),
                        h(
                            "div",
                            {"className": "query-panel", "id": "query-panel", "hidden": True},
                            h("span", {"className": "query-icon"}, Icon("scan-search", 28)),
                            h("textarea", {"id": "text-query", "maxlength": "1000", "rows": "5", "placeholder": "Ex.: um homem de terno olhando para um espelho", "aria-label": "Descrição da imagem procurada"}),
                            h("div", {"className": "query-suggestions"},
                              h("span", None, "Sugestões:"),
                              h("button", {"data-query": "uma pessoa usando terno escuro"}, "pessoa de terno"),
                              h("button", {"data-query": "duas pessoas conversando em frente a um espelho"}, "conversa no espelho"),
                              h("button", {"data-query": "uma cena interna com iluminação escura"}, "cena interna"),
                            ),
                        ),
                        h(
                            "div",
                            {"className": "controls"},
                            h("label", None, h("span", None, "Resultados"), h("select", {"id": "result-limit"}, h("option", {"value": "6"}, "6"), h("option", {"value": "12", "selected": True}, "12"), h("option", {"value": "24"}, "24"))),
                            h("button", {"id": "search-button", "className": "search-button", "disabled": True}, Icon("search", 19), h("span", None, "Buscar similares")),
                        ),
                    ),
                    class_name="upload-body",
                    gap=5,
                ),
                class_name="upload-card",
            ),
            h(
                "aside",
                {"className": "about-panel"},
                h("span", {"className": "step"}, "02"),
                h("h2", None, "Como a busca funciona"),
                h("div", {"className": "flow-item"}, h("span", None, Icon("scan-line", 18)), h("p", None, h("strong", None, "Encode"), "A imagem vira um vetor normalizado de 768 dimensões.")),
                h("div", {"className": "flow-line"}),
                h("div", {"className": "flow-item"}, h("span", None, Icon("database", 18)), h("p", None, h("strong", None, "Compare"), "O índice HNSW mede distância cosseno contra os frames.")),
                h("div", {"className": "flow-line"}),
                h("div", {"className": "flow-item"}, h("span", None, Icon("images", 18)), h("p", None, h("strong", None, "Retrieve"), "Os vizinhos visuais mais próximos voltam em milissegundos.")),
            ),
        ),
        h(
            "section",
            {"className": "results-section", "id": "results-section", "hidden": True},
            h("div", {"className": "results-heading"}, h("div", None, h("span", {"className": "eyebrow"}, "Nearest neighbours"), h("h2", None, "Frames encontrados")), h("span", {"id": "search-meta", "className": "search-meta"})),
            h("div", {"id": "results-grid", "className": "results-grid", "aria-live": "polite"}),
        ),
        h("div", {"id": "toast", "className": "toast", "role": "status", "aria-live": "polite"}),
    )
    return UIProvider(content, theme="dark", full_height=True)
