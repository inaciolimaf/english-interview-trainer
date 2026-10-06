# Spec 02 — Loop de voz em tempo real com barge-in

**Status:** 🟨 Em andamento — implementado e coberto por testes automáticos; faltam as verificações manuais com voz real no navegador e com o LLM real (OpenRouter)  <!-- implementador: atualize para 🟨 Em andamento / ✅ Concluído -->

**Depende de:** 01-foundation

> **Para o agente implementador:** leia antes o [`00-overview.md`](00-overview.md) (decisões fixas, arquitetura, modelo de dados, requisitos não funcionais).
> Marque os checkboxes `[x]` conforme concluir e atualize o **Status** acima e a tabela de progresso no overview.
> A numeração das seções é **global** entre os arquivos (ex.: "seção 5.4" está no overview).
> Onde aparecer **VERIFICAR**, confira na documentação/código da biblioteca antes de implementar.

O requisito mais crítico do sistema. Ao final desta spec existe uma conversa por voz fluida com um entrevistador genérico (um prompt simples; o motor de entrevista completo vem na spec 03), com:
- interrupção (barge-in), com a IA sabendo até onde falou;
- detecção de fim de turno, sem cortar o candidato enquanto ele pensa;
- modo push-to-talk.

Inclui criar o **model server** (seção 3.1) com os endpoints `/transcribe`, `/tts` (streaming), `/end_of_turn` e `/health`, e a fila de prioridade da GPU (seção 3.2). O endpoint `/phonemes` fica para a spec 04.

---

## 7. Loop de voz em tempo real (o requisito mais crítico)

### 7.1 Máquina de estados (servidor é a fonte da verdade; cliente espelha)

```
IDLE → LISTENING ──(fim de turno detectado)──▶ THINKING ──(1ª frase de TTS pronta)──▶ SPEAKING
          ▲                                                                              │
          │◀──────────── barge-in confirmado (para áudio + TTS + LLM) ──────────────────┤
          │◀──────────── fim da fala do entrevistador ─────────────────────────────────┘
SPEAKING ──(VAD: fala do usuário)──▶ DUCKING ──(backchannel)──▶ SPEAKING
                                        └──(fala real)──▶ LISTENING (interrompido)
```

Toda resposta do entrevistador tem um **`turn_id`** monotônico. Qualquer mensagem (texto, áudio, timing) com `turn_id` antigo é **descartada** no cliente e no servidor. Isso evita o bug de um áudio velho tocar depois de uma interrupção.

### 7.2 Captura de áudio (cliente)

- `getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })`.
- `AudioWorklet` converte para **PCM16 mono 16 kHz** e envia frames de ~20–40 ms pelo WebSocket como **binário**.
- O microfone fica **sempre aberto** durante a entrevista, inclusive enquanto o entrevistador fala (necessário para o barge-in).
- Silero VAD no cliente (`@ricky0123/vad-web`) emite `speech_start` / `speech_end` para o servidor.
- **Recomendar fone de ouvido** na UI (um aviso na primeira entrevista). Sem fone, depende do cancelamento de eco do Chrome — testar.

### 7.3 Geração e reprodução da fala do entrevistador

1. DeepSeek em **streaming**. Um divisor de frases acumula tokens e solta frases completas (cuidado com abreviações, números e "e.g.").
2. Cada frase vai ao Kokoro (model server) → retorna o áudio + **timing por palavra**.
   - **VERIFICAR** se o pipeline do Kokoro expõe timestamps por token/palavra (há indícios de `start_ts`/`end_ts` nos tokens do resultado). Se não, estimar distribuindo a duração da frase pelas palavras, proporcional ao número de caracteres/fonemas.
3. O servidor envia ao cliente, por frase: `{turn_id, sentence_idx, text, words:[{w, start_ms, end_ms, char_start, char_end}]}` + os chunks de áudio (PCM ou Opus).
4. O cliente toca as frases em sequência num `AudioContext` e acompanha a posição atual (`currentTime` relativo ao início de cada frase).
5. Pipeline em paralelo: enquanto a frase N toca, a N+1 já está sendo gerada.

**Meta de latência** (fim da fala do usuário → início da fala da IA): **≤ 2 s** (STT ~0,3–0,8 s + primeiro token ~0,5–1 s + primeira frase de TTS ~0,1–0,3 s). Medir e logar cada etapa.

### 7.4 Detecção de fim de turno (não cortar o candidato)

Combinar sinais:

1. **Silêncio** ≥ `end_of_turn_silence_ms` (padrão 1500 ms, configurável). Pausas de raciocínio são comuns em entrevista.
2. **Modelo de fim de turno**:
   - Candidatos: **Pipecat Smart Turn** (analisa o áudio, ONNX, CPU) ou **LiveKit turn-detector** (analisa o texto transcrito).
   - **VERIFICAR** disponibilidade, licença, tamanho e suporte a inglês antes de escolher.
   - Preferência: modelo de áudio (capta entonação), com o de texto como alternativa.
3. **Regra**: depois de um silêncio curto (~600 ms), consultar o modelo.
   - Probabilidade de "turno acabou" alta → responder.
   - Baixa → esperar até o limite máximo de silêncio (ex.: 4 s) antes de responder.
   - Frases claramente incompletas ("...and then", "so I would use") nunca encerram o turno antes do limite máximo.
4. **Modo push-to-talk**: segurar **Espaço** para falar. Nesse modo o fim do turno é soltar a tecla.

### 7.5 Barge-in (interromper o entrevistador)

Quando o VAD detecta fala do usuário durante `SPEAKING`:

1. **Duck**: o cliente baixa o volume da reprodução para ~20% imediatamente.
2. Se a fala dura **< 400 ms** → ignorar e restaurar o volume (tosse, ruído).
3. Se dura **≥ 400 ms** → transcrever o trecho rapidamente.
   - Se for **backchannel** ("yeah", "right", "uh-huh", "okay", "mm-hmm", "got it" — lista configurável, só quando é a fala inteira) → restaurar o volume e continuar.
   - Caso contrário → **interrupção confirmada**.
4. Na interrupção confirmada, de forma atômica:
   - o cliente para a reprodução e descarta o buffer, e envia `{type:"interrupted", turn_id, sentence_idx, char_offset}` com a **posição exata** calculada pelo timing das palavras;
   - o servidor cancela a geração de TTS pendente e o streaming do DeepSeek (abortar a requisição);
   - o servidor incrementa o `turn_id`;
   - o servidor grava no turno: `spoken_text` = texto até `char_offset`, `interrupted=true`, `interrupted_at_char`;
   - o estado vai para `LISTENING`, e o áudio do usuário desde o `speech_start` (manter um buffer de ~1 s antes) entra no turno do candidato.

### 7.6 Como a IA entende a interrupção

Ao montar o histórico para o LLM, o turno interrompido vira:

```
assistant: "<spoken_text>—"
system:    "[The candidate interrupted you at this point. They did NOT hear the rest of
            what you planned to say: '<texto não falado>'. Respond naturally to what they said.]"
user:      "<transcrição do candidato>"
```

O prompt do entrevistador (seção 9) define o comportamento por tipo de interrupção:

| Tipo | Comportamento |
|---|---|
| Pergunta de esclarecimento | Responder; retomar o conteúdo não dito se ainda for relevante |
| Correção do candidato | Aceitar e seguir |
| "Can you repeat?" | Repetir só a parte relevante |
| Candidato começou a responder antes do fim da pergunta | Não repetir a pergunta; ouvir |
| "Let me think" / "give me a second" | Responder no máximo "Sure, take your time." e esperar |

Para o relatório, a análise final avalia também **como** o candidato interrompeu (ex.: sugerir "Sorry to cut in, but..." em vez de simplesmente começar a falar).

### 7.7 Protocolo WebSocket (`/ws/interview/{session_id}`)

Cliente → servidor:
- binário: frames PCM16;
- `{type:"vad", event:"speech_start"|"speech_end", t}`;
- `{type:"ptt", event:"down"|"up"}`;
- `{type:"interrupted", turn_id, sentence_idx, char_offset}`;
- `{type:"playback_done", turn_id}`;
- `{type:"end_session"}`.

Servidor → cliente:
- `{type:"state", state}`;
- `{type:"transcript_partial"|"transcript_final", text}`;
- `{type:"tts_sentence", turn_id, sentence_idx, text, words, sample_rate}` + binário de áudio, com um cabeçalho curto contendo `turn_id` e `sentence_idx` (definir um envelope simples);
- `{type:"duck"|"unduck"}`;
- `{type:"live_feedback", turn_idx, items:[...]}` (seção 10.1);
- `{type:"time", remaining_s}`;
- `{type:"session_ended", session_id}`.

Documentar o protocolo em `backend/api/realtime/PROTOCOL.md`.

---

---

## Checklist de aceite

- [x] Model server sobe sem reload, carrega os modelos uma vez, e a API espera o `/health` dele
- [x] Fila de prioridade da GPU implementada (a transcrição tem prioridade)
- [x] Protocolo documentado em `backend/api/realtime/PROTOCOL.md`
- [ ] Conversa por voz fluida, com **latência ≤ 2 s** do fim da fala até a IA falar; latência de cada etapa logada  <!-- 1,0 s medido no teste de integração com LLM falso; falta medir com o OpenRouter real -->
- [x] Fala da IA em streaming frase a frase (a frase N+1 é gerada enquanto a N toca)
- [ ] Interromper no meio de uma frase: a IA **para em até ~300 ms**  <!-- o volume cai na hora; a parada total vem ~0,4–0,7 s depois do início da fala (checagem dos 400 ms + transcrição); falta medir no navegador -->
- [x] `spoken_text` termina na palavra certa (±1 palavra) e fica salvo no turno
- [x] A resposta seguinte mostra que a IA **sabe onde parou** (histórico da seção 7.6)
- [ ] Os cinco tipos de interrupção da tabela 7.6 se comportam como descrito  <!-- comportamento definido no prompt; depende do LLM real -->
- [ ] "uh-huh", "yeah", tosse **não** interrompem (o volume abaixa e volta)  <!-- ruído < 400 ms, "yeah, right" e "got it" testados; o Kokoro não consegue dizer "uh-huh"/"mm-hmm", então esses precisam de teste manual -->
- [x] Pausas de 1–2 s numa frase incompleta **não** fazem a IA responder
- [x] **Nenhum áudio antigo** toca depois de uma interrupção (`turn_id`)
- [x] O streaming do DeepSeek e o TTS pendente são cancelados na interrupção
- [x] Modo push-to-talk (Espaço) funcionando
- [x] Aviso para usar fone de ouvido na primeira entrevista
- [x] Testes unitários: divisor de frases, cálculo de `char_offset`, montagem do histórico com interrupção
- [x] Teste de integração do WebSocket com áudio sintético

