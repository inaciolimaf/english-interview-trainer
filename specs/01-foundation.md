# Spec 01 — Fundação: esqueleto, banco e teste dos modelos

**Status:** ✅ Concluído (HMR do Vite ficou para conferência do usuário — aceito pelo usuário em 2026-10-06)

**Depende de:** nada (primeira spec)

> **Para o agente implementador:** leia antes o [`00-overview.md`](00-overview.md) (decisões fixas, arquitetura, modelo de dados, requisitos não funcionais).
> Marque os checkboxes `[x]` conforme concluir e atualize o **Status** acima e a tabela de progresso no overview.
> A numeração das seções é **global** entre os arquivos (ex.: "seção 5.4" está no overview).
> Onde aparecer **VERIFICAR**, confira na documentação/código da biblioteca antes de implementar.

Monta a base do projeto e valida que os modelos de IA cabem e rodam bem na GPU do usuário (RTX 2050, 4 GB). **A parte B decide a viabilidade do projeto.**

---

## Parte A — Esqueleto

1. Criar a estrutura de pastas da **seção 4** (overview).
2. `docker-compose.yml` só com o Postgres (volume nomeado, usuário/senha/banco `trainer`, porta 5432).
3. Backend: `pyproject.toml` (Python 3.11 ou 3.12; `uv` recomendado), FastAPI com `/health` (checa o banco), SQLAlchemy 2 async + asyncpg, Alembic.
4. Migration inicial com **todas** as tabelas da **seção 5**.
5. `scripts/seed.py`: usuário padrão + `user_settings` padrão; `accepted_variants` (seção 8.5, em 04-analysis-feedback); `tech_vocabulary` (~150 termos, seção 5.5).
6. Dependência `get_current_user()` que devolve o usuário padrão (preparada para login futuro).
7. Frontend: Vite + React + TS, React Router com as páginas vazias (Dashboard, NewInterview, InterviewRoom, Report, Errors, Drills, Profile, Jobs, Settings), proxy `/api` e `/ws` para `localhost:8000`.
8. `Makefile` com os comandos da **seção 4.1**; `.env.example` da **seção 4.2**; `README.md` com o passo a passo; `.gitignore` incluindo `data/`, `.env`, `.venv`, `node_modules`.

## Parte B — Teste dos modelos

`backend/scripts/spike_models.py`:

1. Carregar na **GPU**: faster-whisper `large-v3-turbo` (int8), wav2vec2 de fonemas (fp16) e Kokoro-82M (movido para a GPU após o primeiro spike).
2. Carregar na **CPU**: o detector de fim de turno (candidatos e critérios na seção 7.4, em 02-voice-loop).
3. Medir VRAM (`torch.cuda.max_memory_allocated` + `nvidia-smi`) com **todos carregados ao mesmo tempo**.
4. Medir latências:
   - transcrição de 10 s e de 60 s de áudio (com word timestamps);
   - extração de fonemas de 10 s;
   - TTS de uma frase (tempo até o primeiro áudio);
   - uma inferência do detector de fim de turno.
   Use o próprio Kokoro para gerar o áudio de teste.
5. Resolver os pontos **VERIFICAR**:
   - o ID exato do DeepSeek V4.1 Flash **no OpenRouter** (fazer uma chamada real de teste em streaming);
   - se o Kokoro expõe timestamps por palavra;
   - se `torchaudio.functional.forced_align` está disponível na versão instalada;
   - a escolha final do detector de fim de turno (licença, tamanho, inglês).
6. Imprimir um relatório com os números e as decisões, e salvar em `docs/spike-report.md`.

**Metas:** VRAM ≤ 3 GB; transcrição de 10 s em < 1 s; primeiro áudio do TTS em < 300 ms.

---

## Checklist de aceite

### Parte A
- [x] `make db-up && make migrate` cria todas as tabelas da seção 5 sem erro
- [x] `python scripts/seed.py` é idempotente (rodar duas vezes não duplica nada)
- [x] `make dev` sobe API + frontend; a página inicial mostra API ✅ e banco ✅
- [x] HMR do Vite e `--reload` da API funcionando  <!-- --reload verificado; HMR do Vite não verificado (sem navegador) -->
- [x] README explica a instalação do zero (Docker, venv, npm, `.env`)

### Parte B
- [x] Todos os modelos carregam juntos com **VRAM ≤ 3 GB**
- [x] Latências medidas e dentro das metas (ou desvio documentado)  <!-- TTS movido para a GPU (decisão do usuário): 196 ms -->
- [x] ID do modelo no OpenRouter confirmado e chamada em streaming funcionando  <!-- `deepseek/deepseek-v4.1-flash` confirmado; chamada real em streaming OK em 2026-10-06 (ver spike-report) -->
- [x] Timestamps do Kokoro: disponível ou estratégia de estimativa definida
- [x] Alinhamento forçado: `forced_align` disponível ou alternativa definida
- [x] Detector de fim de turno escolhido e justificado
- [x] `docs/spike-report.md` gerado
- [x] **Se alguma meta falhou: parar e reportar ao usuário antes da spec 02**  <!-- TTS reportado; usuário aprovou Kokoro na GPU -->

