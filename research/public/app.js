(() => {
  const input = document.querySelector('#image-input');
  const dropzone = document.querySelector('#dropzone');
  const preview = document.querySelector('#query-preview');
  const copy = document.querySelector('#drop-copy');
  const button = document.querySelector('#search-button');
  const limit = document.querySelector('#result-limit');
  const section = document.querySelector('#results-section');
  const grid = document.querySelector('#results-grid');
  const meta = document.querySelector('#search-meta');
  const toast = document.querySelector('#toast');
  let selected = null;
  let previewUrl = null;
  let toastTimer;

  const showToast = (message, error = false) => {
    toast.textContent = message;
    toast.classList.toggle('is-error', error);
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 3500);
  };

  const choose = (file) => {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return showToast('Use uma imagem PNG, JPG ou WebP.', true);
    if (file.size > 15 * 1024 * 1024) return showToast('A imagem ultrapassa 15 MB.', true);
    selected = file;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    preview.hidden = false;
    copy.hidden = true;
    button.disabled = false;
    dropzone.classList.add('has-image');
  };

  input.addEventListener('change', () => choose(input.files[0]));
  ['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault(); dropzone.classList.add('is-dragging');
  }));
  ['dragleave', 'drop'].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault(); dropzone.classList.remove('is-dragging');
  }));
  dropzone.addEventListener('drop', (event) => choose(event.dataTransfer.files[0]));

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);

  const resultCard = (item, index) => {
    const percent = Math.max(0, Math.min(100, item.similarity * 100));
    const timestamp = item.timestamp == null ? 'tempo indisponível' : `${item.timestamp.toFixed(2)}s`;
    return `<article class="result-card" style="--delay:${index * 45}ms">
      <a class="result-image" href="${item.image_url}" target="_blank" rel="noopener">
        <img src="${item.image_url}" alt="Frame ${item.frame} da pasta ${item.folder}" loading="lazy">
        <span class="rank">#${index + 1}</span>
        <span class="score">${percent.toFixed(1)}%</span>
      </a>
      <div class="result-info">
        <div><strong>Frame ${String(item.frame).padStart(8, '0')}</strong><span>Done/${String(item.folder).padStart(4, '0')}</span></div>
        <span class="timestamp">${timestamp}</span>
      </div>
      <div class="score-track"><span style="width:${percent}%"></span></div>
      <small title="${escapeHtml(item.source)}">${escapeHtml(item.source || 'vídeo sem metadata')}</small>
    </article>`;
  };

  button.addEventListener('click', async () => {
    if (!selected) return;
    button.disabled = true;
    button.classList.add('is-loading');
    button.querySelector('span').textContent = 'Vetorizando…';
    grid.innerHTML = Array.from({ length: Number(limit.value) }, () => '<div class="skeleton"></div>').join('');
    section.hidden = false;
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const response = await fetch(`/api/search?limit=${limit.value}`, {
        method: 'POST', headers: { 'Content-Type': selected.type }, body: selected,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'A busca falhou');
      grid.innerHTML = payload.results.map(resultCard).join('') || '<p class="empty">Nenhum frame vetorizado foi encontrado.</p>';
      meta.textContent = `${payload.results.length} resultados · ${payload.elapsed_ms} ms`;
    } catch (error) {
      grid.innerHTML = '<p class="empty">Não foi possível concluir esta busca.</p>';
      showToast(error.message, true);
    } finally {
      button.disabled = false;
      button.classList.remove('is-loading');
      button.querySelector('span').textContent = 'Buscar similares';
    }
  });
})();
