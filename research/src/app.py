"""Documento SSR do playground Research."""

from pyreact import h, render_to_string

from src.components import App


def render_app():
    return render_to_string(h(App, {}))


def render_document(*, live_reload=False):
    reload_script = '<script src="/__prpm_reload.js" defer></script>' if live_reload else ""
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#090b10">
    <meta name="description" content="Busca visual reversa sobre frames vetorizados">
    <title>Research — busca visual</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/styles.css">
    <script src="/app.js" defer></script>
    {reload_script}
  </head>
  <body>{render_app()}</body>
</html>"""
