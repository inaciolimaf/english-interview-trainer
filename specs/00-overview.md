# English Interview Trainer — Overview

Documento-base compartilhado por todas as specs. Contém as decisões fixas, a arquitetura, a estrutura do repositório, o modelo de dados completo, os requisitos não funcionais e o perfil do usuário.

## Progresso

| # | Spec | Escopo | Status |
|---|---|---|---|
| 1 | [01-foundation.md](01-foundation.md) | Esqueleto, Postgres, migrations, seed, teste dos modelos na GPU | ✅ |
| 2 | [02-voice-loop.md](02-voice-loop.md) | Loop de voz em tempo real, fim de turno, barge-in | 🟨 |
| 3 | [03-interview-engine.md](03-interview-engine.md) | Currículo, vagas, prompts, roteiros, estilos, tempo | 🟨 |
| 4 | [04-analysis-feedback.md](04-analysis-feedback.md) | Pronúncia por fonema, calibração, gramática/técnico, feedback, clipes | 🟨 |
| 5 | [05-reports-drills.md](05-reports-drills.md) | Relatório da sessão, painel de evolução, explorador de erros, drills (SRS) | 🟨 |
| 6 | [06-frontend-redesign.md](06-frontend-redesign.md) | Redesenho e conclusão do frontend (identidade visual, histórico, biblioteca de drills) | 🟨 |

Legenda: ⬜ não iniciado · 🟨 em andamento · ✅ concluído. **Implemente na ordem**: cada spec depende das anteriores.

> **Ponto de parada:** se o teste dos modelos (spec 01, parte B) falhar nas metas de VRAM/latência, **pare e reporte ao usuário** antes de seguir.

## Mapa de seções (numeração global)

| Seções | Arquivo |
|---|---|
| 1–5, 13, 15 | este overview |
| 7 | 02-voice-loop |
| 6, 9 | 03-interview-engine |
| 8, 10.1–10.3 | 04-analysis-feedback |
| 10.4, 11, 12 | 05-reports-drills |
| 16 | 06-frontend-redesign |

---

## 1. Visão geral

Aplicação web **local, para uso pessoal**, que simula entrevistas de emprego em inglês por voz para um desenvolvedor backend brasileiro (nível de inglês intermediário) que busca vagas fora do Brasil.

O sistema:

1. Conduz **entrevistas por voz em fala livre** (system design, técnica, comportamental), com um entrevistador de IA que fala com voz natural.
2. Permite **interromper o entrevistador** a qualquer momento (barge-in); a IA sabe que foi interrompida e **até que palavra falou**.
3. **Não interrompe o candidato enquanto ele pensa** (detecção de fim de turno).
4. Analisa cada resposta e aponta:
   - **Pronúncia em nível de fonema** ("in *throughput* you said /t/ instead of /θ/");
   - **Gramática**;
   - **Conteúdo técnico** (erros conceituais, pontos omitidos);
   - **Fluência** (WPM, pausas, muletas como "uh", "like").
5. Dá feedback **na hora**, **no final** ou **híbrido** (configurável).
6. Guarda **somente os trechos de áudio com erro**, categoriza todos os erros e mostra **evolução** ao longo do tempo.
7. Gera **sessões de drill** separadas, com repetição espaçada, a partir dos erros recorrentes.
8. Personaliza as entrevistas a partir do **currículo (PDF)** e da **descrição da vaga** colada pelo usuário.

**Idioma:** toda a interface e todas as explicações de correção são em **inglês** (decisão do usuário, para imersão).
**Sotaque de referência:** **inglês americano** (pronúncia e voz do entrevistador).

---

## 2. Decisões fixas (não alterar sem perguntar ao usuário)

| Tema | Decisão |
|---|---|
| Frontend | React + Vite + TypeScript, roda no navegador (Chrome) em `localhost`. **Não** usar Electron/Tauri. |
| Backend | Python + FastAPI, em **venv local** (não Docker). |
| Banco | **PostgreSQL em Docker** (docker compose). É o **único** serviço em Docker. |
| Modelos de IA | Rodam **localmente no venv**, na GPU do usuário (NVIDIA RTX 2050, **4 GB VRAM**), CPU de 12 núcleos, 14 GB RAM, Linux. |
| LLM | **DeepSeek V4.1 Flash** (`deepseek/deepseek-v4.1-flash`) via **OpenRouter** (API compatível com OpenAI SDK). Não usar a API própria da DeepSeek nem Claude/OpenAI/Azure. |
| Transcrição (STT) | `faster-whisper` com **large-v3-turbo**, int8, GPU, word timestamps. |
| Pronúncia | Modelo **wav2vec2 de reconhecimento de fonemas** (ex.: `facebook/wav2vec2-xlsr-53-espeak-cv-ft`), fp16, GPU. Sem Azure. |
| TTS | **Kokoro-82M**, local, **GPU** (decidido após o spike da spec 01: na CPU o primeiro áudio levava ~1,3 s; na GPU, ~0,2 s). Voz americana. |
| VAD | **Silero VAD** (no navegador via `@ricky0123/vad-web`, que usa Silero em ONNX). |
| Detector de fim de turno | Modelo dedicado (**incluído**, não opcional) — ver seção 7.4. |
| Usuários | Uso por **uma pessoa**, **sem login**, mas o banco é **modelado para múltiplos usuários** desde já (toda tabela de dados pessoais tem `user_id`). Um usuário padrão é criado no seed. |
| Áudio | Guardar **somente clipes dos erros** (não a sessão inteira). |
| Quadro de desenho (system design) | **Fora do escopo agora** (futuro). Entrevistas só por voz. |

---

## 3. Arquitetura

```
┌───────────────────────── Navegador (React + Vite) ─────────────────────────┐
│  Mic → AudioWorklet (PCM16 16kHz) ──┐        ┌── AudioContext player       │
│  Silero VAD (vad-web) → eventos     │        │   (rastreia palavra tocada) │
│  UI: entrevista, relatórios, painel │        │                             │
└─────────────────────────────────────┼────────┼─────────────────────────────┘
                                       │ WebSocket (binário + JSON)
┌──────────────────────────────────────▼────────┴─────────────────────────────┐
│  API — FastAPI (porta 8000, `uvicorn --reload`)                             │
│  • orquestra o turno (máquina de estados, seção 7)                          │
│  • chama o LLM (streaming), divide em frases, pede TTS                      │
│  • REST: perfis, vagas, sessões, erros, drills, painel                      │
│  • SQLAlchemy 2 async + asyncpg + Alembic                                   │
└──────────────┬───────────────────────────────────────────┬──────────────────┘
               │ HTTP/WebSocket interno                    │ HTTPS
┌──────────────▼──────────────────────────┐        ┌───────▼────────┐
│  Model Server (porta 8001, SEM reload)  │        │  OpenRouter    │
│  • faster-whisper (GPU)                 │        └────────────────┘
│  • wav2vec2 fonemas (GPU)               │
│  • Kokoro TTS (GPU)                     │        ┌────────────────┐
│  • detector de fim de turno (CPU)       │        │ Postgres       │
│  • fila de prioridade para a GPU        │        │ (Docker)       │
└─────────────────────────────────────────┘        └────────────────┘
```

(OpenRouter → DeepSeek V4.1 Flash.)

### 3.1 Por que dois processos Python

Carregar os modelos leva 10–30 s. Com `uvicorn --reload`, cada alteração de código recarregaria tudo. Por isso:

- **`model_server`**: processo persistente, carrega os modelos **uma vez**, roda **sem** `--reload`. Expõe endpoints internos (`/transcribe`, `/phonemes`, `/tts` em streaming, `/end_of_turn`).
- **`api`**: lógica de negócio, roda **com** `--reload`. Conversa com o model server por HTTP/WebSocket local.

### 3.2 Prioridade da GPU

O model server serializa o acesso à GPU com uma **fila de prioridade**:

1. **Alta**: transcrição de turno e TTS do entrevistador (bloqueiam a conversa).
2. **Baixa**: análise de pronúncia (roda em segundo plano, entre turnos).

Uma análise de pronúncia em andamento não deve atrasar a próxima transcrição: processe a pronúncia em pedaços (por frase) e cheque a fila entre eles.

### 3.3 Orçamento de memória (meta)

| Modelo | Dispositivo | Memória aproximada |
|---|---|---|
| faster-whisper large-v3-turbo int8 | GPU | ~1–1,5 GB VRAM |
| wav2vec2 fonemas fp16 | GPU | ~0,8–1,2 GB VRAM |
| Kokoro-82M | GPU | ~0,6 GB VRAM |
| Detector de fim de turno | CPU | ~0,1–0,5 GB RAM |

Meta: **≤ 3 GB de VRAM** com todos carregados ao mesmo tempo (medido no spike: 2,5–2,8 GB; a parte alta vem do cache do alocador do PyTorch depois de sintetizar 60 s de áudio de uma vez — no model server, sintetizar **por frase** e usar `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`) (a GPU tem 4 GB e a tela usa a GPU integrada). Se estourar, fallback configurável do Whisper para `distil-large-v3` ou `small.en`.

---

## 4. Estrutura do repositório

```
english-interview-trainer/
├── specs/                      # 00-overview + specs 01–05 (esta pasta)
├── README.md                    # como rodar (gerar na spec 01)
├── docker-compose.yml           # só postgres
├── .env.example
├── Makefile                     # atalhos: db-up, dev, migrate, calibrate...
├── frontend/
│   ├── package.json
│   ├── vite.config.ts           # proxy /api e /ws → localhost:8000
│   └── src/
│       ├── audio/               # captureWorklet.ts, player.ts, vad.ts
│       ├── realtime/            # cliente WebSocket + máquina de estados do cliente
│       ├── pages/               # Dashboard, NewInterview, InterviewRoom, Report,
│       │                        # Errors, Drills, Profile, Jobs, Settings
│       ├── components/
│       └── api/                 # cliente REST tipado
├── backend/
│   ├── pyproject.toml           # (uv recomendado) Python 3.11 ou 3.12
│   ├── alembic/ , alembic.ini
│   ├── api/
│   │   ├── main.py
│   │   ├── routes/              # REST
│   │   ├── realtime/            # WebSocket, orquestrador de turno, barge-in
│   │   ├── interview/           # engine, prompts, rubricas, gestão de tempo
│   │   ├── analysis/            # gramática/técnico (LLM), fluência, filtro final
│   │   ├── pronunciation/       # pipeline de fonemas, calibração, variantes
│   │   ├── drills/              # geração + SRS
│   │   ├── llm/                 # cliente LLM (OpenRouter)
│   │   ├── db/                  # models SQLAlchemy, sessão, repositórios
│   │   └── storage/             # clipes de áudio em disco
│   ├── model_server/
│   │   ├── main.py
│   │   ├── stt.py , phonemes.py , tts.py , turn_detector.py
│   │   └── gpu_queue.py
│   ├── scripts/
│   │   ├── spike_models.py      # spec 01 parte B: valida modelos na GPU + latência
│   │   ├── calibrate_phonemes.py
│   │   └── seed.py
│   └── tests/
└── data/                        # .gitignore — clipes, uploads, cache de modelos
    ├── audio_clips/
    ├── uploads/
    └── calibration/
```

### 4.1 Comandos de desenvolvimento

- `make db-up` → `docker compose up -d db`
- `make migrate` → `alembic upgrade head`
- `make models` → sobe o model server (`uvicorn model_server.main:app --port 8001`, sem reload)
- `make api` → `uvicorn api.main:app --port 8000 --reload`
- `make web` → `npm run dev` (Vite HMR)
- `make dev` → sobe db + models + api + web juntos (ex.: `honcho`/`concurrently`); o model server sobe primeiro e a API espera o `/health` dele.

### 4.2 Variáveis de ambiente (`.env.example`)

```
DATABASE_URL=postgresql+asyncpg://trainer:trainer@localhost:5432/trainer
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=deepseek/deepseek-v4.1-flash
MODEL_SERVER_URL=http://localhost:8001
WHISPER_MODEL=large-v3-turbo
WHISPER_COMPUTE_TYPE=int8
PHONEME_MODEL=facebook/wav2vec2-xlsr-53-espeak-cv-ft
TTS_VOICE=                 # uma voz americana do Kokoro (ex.: af_*/am_*) — VERIFICAR nomes
DATA_DIR=./data
```

---

## 5. Modelo de dados (PostgreSQL)

Use SQLAlchemy 2.0 (async) + Alembic. UUIDs como PK. `created_at/updated_at` em todas as tabelas. Campos `jsonb` onde indicado. Enums como `TEXT` + `CHECK` ou enum do Postgres.

### 5.1 Usuário e configurações

- **users**: `id`, `display_name`, `email` (nullable), `created_at`. Seed cria um usuário padrão; a API usa esse usuário até existir login (resolver via dependência `get_current_user()` para facilitar trocar depois).
- **user_settings** (1:1 com users):
  - `feedback_mode` (`live` | `end` | `hybrid`, padrão `end`);
  - `default_interviewer_style` (`friendly` | `neutral` | `tough`, padrão `neutral`);
  - `default_seniority` (`mid` | `senior`, padrão `senior`), `default_duration_min` (padrão 30);
  - `turn_taking_mode` (`auto` | `push_to_talk`), `end_of_turn_silence_ms` (padrão 1500);
  - `tts_voice`, `tts_speed`;
  - `phoneme_threshold_k` (padrão 2.0, ver seção 8.4).

### 5.2 Contexto da entrevista

- **resumes**: `id`, `user_id`, `file_path`, `raw_text`, `parsed_profile jsonb` (nome, anos de experiência, stack, cargos, projetos com descrição/impacto, conquistas), `is_active`, `created_at`.
- **job_postings**: `id`, `user_id`, `title`, `company`, `raw_text`, `parsed jsonb` (stack exigida, desejável, senioridade inferida, responsabilidades, domínio), `created_at`.

### 5.3 Sessões e turnos

- **interview_sessions**:
  - `id`, `user_id`, `type` (`system_design` | `technical` | `behavioral`);
  - `job_posting_id` (nullable), `resume_id` (nullable);
  - `seniority`, `interviewer_style`, `duration_min`, `feedback_mode`;
  - `status` (`active` | `completed` | `abandoned`), `started_at`, `ended_at`;
  - `plan jsonb` (o problema de system design escolhido / tópicos planejados);
  - `report jsonb` (seção 10), `scores jsonb`.
- **turns**:
  - `id`, `session_id`, `idx`, `role` (`interviewer` | `candidate`);
  - `full_text` (o que o LLM gerou), `spoken_text` (o que foi efetivamente tocado/ouvido — para o candidato, igual à transcrição);
  - `interrupted bool`, `interrupted_at_char int` (nullable);
  - `started_at`, `ended_at`;
  - Só para turnos do candidato: `audio_ms`, `asr_words jsonb` (palavra, início, fim, probabilidade), `metrics jsonb` (WPM, pausas longas, contagem de muletas), `analysis_status` (`pending` | `done` | `failed`).

### 5.4 Erros (o coração do acompanhamento)

- **errors**:
  - `id`, `user_id`, `session_id`, `turn_id` (nullable para drills), `drill_attempt_id` (nullable);
  - `kind` (`pronunciation` | `grammar` | `technical` | `fluency` | `vocabulary`);
  - `category TEXT`, taxonomia hierárquica estável, ex.:
    - `pron:phoneme:θ`, `pron:epenthesis`, `pron:final_ed`, `pron:vowel:ɪ-iː`, `pron:stress`;
    - `gram:preposition`, `gram:article`, `gram:verb_tense`, `gram:subject_verb_agreement`, `gram:word_order`, `gram:false_friend`;
    - `tech:caching`, `tech:consistency`, `tech:databases`, `tech:messaging`, `tech:concurrency`, `tech:api_design`, `tech:estimation`, `tech:tradeoffs`;
    - `flu:filler`, `flu:long_pause`;
    - `vocab:missing_term`;
  - `severity` (`low` | `medium` | `high`);
  - `original_text`, `corrected_text`, `explanation` (em inglês);
  - Para pronúncia: `word`, `expected_phonemes`, `heard_phonemes`, `phoneme_index`, `score`;
  - `audio_clip_id` (nullable);
  - `dismissed bool` + `dismissed_at` (usuário clicou "not an error");
  - `created_at`.
- **audio_clips**: `id`, `user_id`, `file_path` (Opus em `data/audio_clips/`), `duration_ms`, `source_turn_id`, `start_ms`, `end_ms`.

### 5.5 Pronúncia: calibração e variantes

- **phoneme_calibration**: `phoneme`, `accent` (`en-us`), `native_mean`, `native_std`, `p05`, `n_samples`, `updated_at`. Global (não por usuário).
- **user_phoneme_adjustments**: `user_id`, `phoneme`, `word` (nullable — ajuste específico de palavra), `offset float`, `dismiss_count`, `confirm_count`.
- **accepted_variants**: `id`, `word` (nullable = regra geral), `expected` (sequência de fonemas), `accepted` (sequência alternativa aceita), `note`. Seed com algumas dezenas de regras (seção 8.5).
- **tech_vocabulary**: `term`, `phonemes`, `domain`, `common_mistake_note`. Seed com ~150 termos (cache, queue, schema, throughput, idempotent, Kubernetes, Nginx, PostgreSQL, latency, asynchronous, data, database, API, JSON, GraphQL, Redis, Kafka, sharding, replica, consensus, etc.).

### 5.6 Drills

- **drill_items**:
  - `id`, `user_id`, `source_error_id`, `kind` (`pron_read` | `grammar_rewrite` | `tech_explain`);
  - `prompt_text`, `target_text`, `focus` (ex.: fonema ou regra);
  - campos de SRS (SM-2): `ease`, `interval_days`, `repetitions`, `lapses`, `due_at`;
  - `retired bool` (dominado).
- **drill_sessions**: `id`, `user_id`, `started_at`, `ended_at`, `summary jsonb`.
- **drill_attempts**: `id`, `drill_session_id`, `drill_item_id`, `transcript`, `score`, `passed`, `created_at`.

---

## 13. Requisitos não funcionais

- **Latência** do turno ≤ 2 s (7.3). Logar o tempo de cada etapa (STT, primeiro token, primeira frase de TTS).
- **VRAM** ≤ 3 GB com todos os modelos carregados (3.3).
- **Robustez**:
  - se o model server cair, a API mostra o erro na UI e tenta reconectar;
  - se o LLM (OpenRouter) falhar, tentar de novo com backoff e avisar.
- **Custo**:
  - usar cache de prompt (manter o system prompt estável no início, sem timestamps nele); no OpenRouter o cache só acerta se o pedido cair no mesmo provedor, então o roteamento é fixado (`LLM_PROVIDERS`, padrão Together → DeepInfra, medidos em 2026-10-06: ~0,4 s / ~0,7 s até o 1º token, com cache). O provedor DeepSeek é bloqueado pela regra de privacidade da conta do usuário (não treinar com dados pagos); `data_collection: deny` é enviado em todo pedido. Na conversa o raciocínio do modelo fica desligado (custava 3–6 s antes do 1º token);
  - abortar o streaming do LLM no barge-in.
- **Testes**:
  - testes unitários para o divisor de frases, o cálculo de `char_offset`, a montagem do histórico com interrupção, a regra de erro de fonema com calibração e variantes, e o SM-2;
  - teste de integração do WebSocket com áudio sintético (gerado pelo próprio Kokoro).
- **Privacidade**: tudo local, exceto as chamadas ao LLM via OpenRouter, que enviam só **texto** (nunca áudio).

---

## 15. Perfil do usuário (contexto para os prompts e o seed)

- Desenvolvedor backend brasileiro, buscando vagas de **pleno ou sênior** fora do Brasil.
- Inglês falado **intermediário**.
- Stacks: **Node.js/TypeScript** e **Python**. A stack da entrevista varia conforme a vaga ou o currículo.
- Quer feedback em **inglês**, com sotaque de referência **americano**.
- Muito sensível a custo: tudo que puder rodar local, roda local.
