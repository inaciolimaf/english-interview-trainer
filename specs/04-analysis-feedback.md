# Spec 04 — Análise: pronúncia, gramática, técnico e feedback

**Status:** 🟨 Em andamento — implementado e coberto por testes (LLM falso + model server real); falta validar com voz real e com o LLM real (OpenRouter)  <!-- implementador: atualize para 🟨 Em andamento / ✅ Concluído -->

**Depende de:** 03-interview-engine

> **Para o agente implementador:** leia antes o [`00-overview.md`](00-overview.md) (decisões fixas, arquitetura, modelo de dados, requisitos não funcionais).
> Marque os checkboxes `[x]` conforme concluir e atualize o **Status** acima e a tabela de progresso no overview.
> A numeração das seções é **global** entre os arquivos (ex.: "seção 5.4" está no overview).
> Onde aparecer **VERIFICAR**, confira na documentação/código da biblioteca antes de implementar.

Analisa cada resposta do candidato em segundo plano, persiste erros categorizados com clipes de áudio (só dos erros) e entrega o feedback no modo escolhido.

Inclui:
- o endpoint `/phonemes` no model server;
- o script de calibração `scripts/calibrate_phonemes.py`;
- o seed de variantes aceitas (seção 8.5), se ainda não estiver completo.

---

## 8. Análise de pronúncia (fala livre)

### 8.1 Pipeline por turno do candidato (em segundo plano)

1. **Entrada**: o áudio do turno (16 kHz) + `asr_words` do Whisper (palavras com início, fim e probabilidade).
2. **Fonemas esperados**: converter cada palavra transcrita para fonemas IPA en-us com `phonemizer` + `espeak-ng` (o mesmo conjunto de fonemas do modelo wav2vec2 espeak). Cachear por palavra.
3. **Posteriors**: rodar o wav2vec2 na frase (segmentar por frase/pausa; janelas ≤ 15 s).
4. **Alinhamento forçado (CTC)** dos fonemas esperados contra os posteriors (`torchaudio.functional.forced_align` ou equivalente — **VERIFICAR** a disponibilidade na versão do torchaudio instalada; alternativa: implementar o Viterbi CTC, que é curto).
5. **Score por fonema** (GOP baseado em posterior): média do log-posterior do fonema esperado nos frames alinhados, comparada ao melhor fonema competidor nesses frames.
6. **Fonema ouvido**: decodificação livre (greedy CTC) no trecho da palavra, alinhada por Levenshtein com o esperado. Isso gera substituições, inserções (vogal epentética: "es-tack") e omissões.
7. **Decisão de erro** por fonema com a calibração (8.4), descontando as variantes aceitas (8.5).

### 8.2 O problema da fala livre

O Whisper tende a "corrigir" palavras mal pronunciadas para a palavra provável. Mitigações obrigatórias:

- Palavras com **probabilidade baixa no Whisper** viram **suspeitas** (mesmo sem erro de fonema detectado) e alimentam os drills.
- Termos de `tech_vocabulary` ditos na resposta recebem análise prioritária e limiar mais rígido.
- Drills de leitura (modo roteiro, seção 11) confirmam os suspeitos com o texto esperado conhecido.

### 8.3 Erros típicos de brasileiros a priorizar

- /θ/ e /ð/ virando t, f, d ou s;
- vogal epentética (inicial "es-", final "-i": "Goo-gui-li");
- -ed final pronunciado como sílaba;
- /ɪ/ vs /iː/ (ship/sheep);
- /æ/ vs /ɛ/;
- h inicial;
- r final e r retroflexo;
- -tion;
- tonicidade errada em palavras cognatas (deVElopment, comPUter).

Essa lista entra no prompt do filtro LLM (8.6) e na taxonomia.

### 8.4 Calibração (`scripts/calibrate_phonemes.py`)

1. Baixar o **LibriSpeech test-clean** (~350 MB) para `data/calibration/`.
2. Rodar o pipeline 8.1 usando o texto de referência do corpus.
3. Para cada fonema, calcular `native_mean`, `native_std`, `p05` dos scores → `phoneme_calibration`.
4. Regra de erro: `score < native_mean - k * native_std` (com `k = phoneme_threshold_k`, padrão 2.0), ajustada por `user_phoneme_adjustments.offset`.
5. Script idempotente, roda uma vez; depois o corpus pode ser apagado.

### 8.5 Variantes aceitas (seed)

Exemplos:
- flap t americano ("water", "better", "data");
- "data" como /deɪtə/ e /dætə/;
- "either", "route", "schedule";
- reduções em fala conectada ("want to" → "wanna", "going to" → "gonna", "kind of" → "kinda");
- schwa em sílabas átonas;
- "the" como /ðə/ e /ði/.

Quando um par (esperado, ouvido) bate com uma variante, não conta como erro.

### 8.6 Feedback do usuário e filtro LLM

- Botão **"Not an error"** em cada erro de pronúncia: marca `dismissed`, incrementa `dismiss_count` e aumenta o `offset` (fica mais tolerante) para aquele fonema; se a dispensa se repetir na mesma palavra, cria um ajuste específico da palavra.
- **Filtro final (DeepSeek)**:
  - recebe os candidatos a erro (palavra, esperado, ouvido, score, contexto) e devolve JSON com os erros a mostrar, a severidade e a explicação em inglês (ex.: *"You said /tru:put/ — start with /θ/: put your tongue between your teeth."*);
  - prioriza erros típicos de brasileiro, vocabulário técnico e erros que afetam a inteligibilidade;
  - descarta ruído isolado;
  - **regra dura no prompt**: o LLM **não pode inventar** erros de pronúncia que não estejam nos dados recebidos; só filtra, prioriza e explica.

---

## 10. Feedback e relatórios

### 10.1 Análise por turno (sempre roda, independe do modo)

Para cada turno do candidato, em segundo plano:

1. Fluência (local): WPM, pausas > 2 s, muletas.
2. Pronúncia (seção 8).
3. Gramática + técnico + vocabulário (DeepSeek, JSON estruturado):
   - recebe a pergunta (o `spoken_text` do entrevistador), a resposta transcrita, a senioridade e a rubrica;
   - retorna uma lista de erros com `kind`, `category` (da taxonomia), `original_text`, `corrected_text`, `explanation` (em inglês) e `severity`.
4. Persistir os erros, recortar e salvar os clipes (10.3) e marcar `analysis_status=done`.

### 10.2 Modos de feedback

- **live**: depois de cada turno analisado, envia `live_feedback` com **no máximo 3 itens** (os de maior severidade). Aparece como **cartão de texto** na tela, sem voz, e não interrompe a entrevista.
- **end**: nada durante a sessão; tudo aparece no relatório.
- **hybrid**: só itens `high` ao vivo; o resto no relatório.

### 10.3 Clipes de áudio (só os erros)

- O áudio do turno fica em memória ou em arquivo temporário **até a análise terminar**.
- Para cada erro com âncora temporal:
  - pronúncia: a palavra ±300 ms;
  - gramática e vocabulário: a frase que contém o erro;
  - recortar e salvar em **Opus** (`data/audio_clips/{user_id}/{session_id}/{error_id}.opus`) e criar o `audio_clips`.
- Depois, **apagar o áudio completo do turno**. Erros técnicos e de fluência sem âncora não precisam de clipe.

---

## Checklist de aceite

- [x] Endpoint `/phonemes` no model server, com prioridade baixa na fila da GPU
- [x] Pipeline de pronúncia completo (seção 8.1): fonemas esperados → posteriors → alinhamento → score por fonema → fonema ouvido
- [x] Detecta substituições (/θ/→/t/), inserções (vogal epentética) e omissões  <!-- /θ/→/t/ testado com áudio sintético; inserções e omissões cobertas por testes unitários; com voz real, ainda não -->
- [x] `calibrate_phonemes.py` roda no LibriSpeech test-clean e preenche `phoneme_calibration`, de forma idempotente  <!-- 775 frases, 39.597 fonemas, 54 linhas (+ global `*`) -->
- [x] Regra de erro com calibração e `offset` do usuário; variantes aceitas não contam como erro
- [x] Palavras com probabilidade baixa no Whisper e termos técnicos marcados como suspeitos (seção 8.2)
- [x] Filtro LLM: prioriza, explica em inglês e **não inventa** erros de pronúncia  <!-- o código só aceita ids da lista de candidatos; sem LLM, cai num fallback determinístico com explicações prontas -->
- [x] Gramática, técnico e vocabulário via LLM, em JSON estruturado, com categorias da taxonomia (seção 5.4)  <!-- citações de gramática/vocabulário precisam existir na resposta; categoria fora da taxonomia → `*:other` -->
- [x] Métricas de fluência (WPM, pausas > 2 s, muletas) por turno
- [x] Modos live, end e hybrid funcionando; o cartão ao vivo tem no máximo 3 itens e não interrompe a conversa
- [x] Clipes em Opus salvos **só para erros**; o áudio completo do turno é apagado depois da análise
- [x] Botão "Not an error" marca `dismissed` e ajusta `user_phoneme_adjustments`  <!-- nos cartões ao vivo; a página de relatório (spec 05) reaproveita o endpoint -->
- [x] A análise de pronúncia não atrasa o turno seguinte da conversa
- [x] Testes unitários: regra de erro de fonema com calibração e variantes, recorte de clipes

### Notas da implementação

- **Tonicidade (`pron:stress`) não é detectada**: o wav2vec2 de fonemas não modela acento lexical. A categoria continua na taxonomia; detectar exige um modelo de prosódia (futuro).
- O GOP compara só com fonemas do inglês mais substitutos típicos do português; o "fonema ouvido" usa o vocabulário inteiro do modelo, para capturar o "i" epentético.
- A fonetização é feita por janela inteira (mantém as formas fracas da fala conectada), com fallback palavra a palavra. Palavras funcionais (a, the, of…) não são julgadas, nem na calibração.
- Suspeitos (seção 8.2) viram erros `pron:suspect` de severidade baixa, fora do feedback ao vivo; os drills da spec 05 usam essa lista.
- O prompt de transcrição inclui hesitações ("Um, uh…") para o Whisper não apagar as muletas que a fluência precisa contar.
