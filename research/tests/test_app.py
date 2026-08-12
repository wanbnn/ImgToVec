from src.app import render_app, render_document


def test_app_uses_research_interface():
    html = render_app()
    assert "Encontre um frame" in html
    assert 'id="image-input"' in html
    assert 'id="results-grid"' in html
    assert "Visual similarity engine" in html
    assert 'data-mode="text"' in html
    assert 'id="text-query"' in html


def test_document_loads_assets():
    html = render_document()
    assert html.startswith("<!doctype html>")
    assert 'src="/app.js"' in html
    assert 'href="/styles.css"' in html
