# Research

Playground de busca reversa visual. Uma imagem enviada é codificada com `nomic-embed-vision-v1.5` e comparada por distância cosseno com os frames armazenados no PostgreSQL/pgvector.

## Stack

- PyReact para SSR e composição da interface;
- PRPM para ambiente, dependências, lockfile e scripts;
- UIKitPR para provider, cards, tipografia e layout;
- 6cons para ícones SVG nativos;
- Nomic Vision + PyTorch ROCm/CUDA/Metal/CPU para embeddings;
- PostgreSQL/pgvector com índice HNSW.

## Executar

O projeto lê o `.env`, `Models/` e `Done/` da pasta pai. No Arch/ROCm, PyTorch e Torchvision devem estar instalados no sistema e a venv precisa acessar os pacotes do sistema.

```bash
cd research
prpm install
prpm run dev -- --no-open
```

Acesse <http://127.0.0.1:3000>.

## Funcionamento

1. O navegador envia PNG, JPG ou WebP diretamente no corpo da requisição.
2. O arquivo permanece em memória e não é persistido.
3. O Nomic Vision gera um embedding L2-normalizado de 768 dimensões.
4. O pgvector ordena os frames com o operador de distância cosseno `<=>`.
5. A API expõe somente arquivos de frames registrados no banco e contidos em `Done/`.

Somente os frames já vetorizados podem aparecer nos resultados. Para completar o acervo, execute na raiz:

```bash
./process_frame_vectors.py
```
