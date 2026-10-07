# Spec 06 — Redesenho e conclusão do frontend

**Status:** 🟨 Em andamento — implementado e revisado no navegador (Today, New interview, History, Report, Errors, Drills, Jobs, Settings, anel de voz); falta usar a sala ao vivo e uma sessão de drill de verdade, e conferir o layout em tela de celular  <!-- implementador: atualize para 🟨 Em andamento / ✅ Concluído -->

**Depende de:** 01–05 (consome só a API que já existe; uma única adição opcional no backend, seção 16.6)

> Leia antes o [`00-overview.md`](00-overview.md). A interface continua **em inglês** (decisão fixa). Esta spec trata só do frontend (`frontend/src`).

---

## 16.1 Diagnóstico (estado antes desta spec)

O frontend funciona, mas parece um protótipo:

- **Visual genérico:** fonte do sistema, azul padrão, tudo dentro de cartões cinza iguais, `<select>` e `<fieldset>` nativos em todo lugar, emojis como ícones (✅ ❌ 🎤 🔊 ✨).
- **Sem identidade:** nada lembra que o produto é sobre **voz** e **pronúncia**. Os fonemas IPA aparecem em texto pequeno e na fonte do sistema (que nem sempre tem os glifos certos).
- **A sala de entrevista** — a tela mais importante — é uma lista de balões com um "pill" de estado. Não há retorno visual de que o microfone está captando, nem de quem está falando, nem do plano da entrevista, e o tempo restante é só texto.
- **Fluxos incompletos:**
  - não existe **histórico de entrevistas** (a API `GET /sessions` não é usada; o painel mostra só as recentes);
  - a **biblioteca de drills** (`GET /drills/items`) não aparece em lugar nenhum;
  - "End interview" encerra sem confirmação; não há **teste de microfone** antes de entrar;
  - o **nome do usuário** (`GET /users/me`) não é usado;
  - o **status do sistema** ocupa um cartão inteiro no painel;
  - não dá para **ouvir a voz** escolhida nas configurações antes de salvar;
  - upload de currículo sem arrastar-e-soltar; vagas sem busca/expansão.
- **CSS** num arquivo de 1.100 linhas, com classes que se sobrepõem (`.button`, `button`, `a.button`, `.pill`, `.chip-button`...).

## 16.2 Direção visual

**Conceito: "laboratório de fonética".** O produto é sobre ouvir a própria voz e transcrevê-la com precisão. A interface pega emprestado o vocabulário de um caderno de transcrição fonética: falas tipografadas como roteiro, fonemas IPA como glifos grandes, e duas vozes com cores próprias.

### Cores (tokens em `:root`, com variante escura)

| Token | Claro | Escuro | Papel |
|---|---|---|---|
| `--paper` | `#F2F3F7` | `#131220` | fundo (porcelana fria, não creme) |
| `--sheet` | `#FFFFFF` | `#1C1A2B` | superfícies |
| `--ink` | `#1B1A2A` | `#EDEBF5` | texto |
| `--ink-soft` | `#5D5B72` | `#A19EB8` | texto secundário |
| `--rule` | `#DCDCE6` | `#2E2B42` | linhas e bordas |
| `--plum` | `#5A2D82` | `#B48CF0` | **voz do entrevistador**, ação primária |
| `--amber` | `#C77D0E` | `#F0B44C` | **a sua voz** (candidato), microfone, destaque |
| `--rose` | `#C8423B` | `#F07468` | erro |
| `--sage` | `#2F8F68` | `#5FC79A` | acerto / melhora |

A cor **codifica quem fala**: roxo = entrevistador, âmbar = você. Isso vale na sala, nas transcrições, no coach e no anel de voz. Vermelho/verde só para erro/acerto.

### Tipografia (empacotada via `@fontsource`, funciona offline)

- **Bricolage Grotesque** (variável) — toda a UI, títulos com peso e largura ajustados (títulos grandes em 600, corpo em 400).
- **Charis SIL** — fonte de linguistas, com cobertura completa de IPA. Usada para **o que foi falado** (transcrições, frases dos drills, "você disse" / "melhor versão") e para **todos os fonemas** (`/θ/`, `/ɪ/`).
- Escala: 0,8125 · 0,9375 · 1 · 1,25 · 1,625 · 2,25 · 3,5 rem. Linhas de leitura ≤ 72 caracteres.
- Sem rótulos em CAIXA ALTA, sem "eyebrows" decorativos acima dos títulos.

### Layout

```
┌──────────┬───────────────────────────────────────────────┐
│ wordmark │  título da página            ações à direita  │
│ /ˈɪn.../ │  ───────────────────────────────────────────  │
│          │                                               │
│ Practice │  conteúdo (largura máxima por página:         │
│  Today   │   leitura 760px, painéis 1120px)              │
│  New     │                                               │
│  Drills ●│                                               │
│ Review   │                                               │
│  History │                                               │
│  Errors  │                                               │
│ Setup    │                                               │
│  Resume  │                                               │
│  Jobs    │                                               │
│  Settings│                                               │
│          │                                               │
│ ● online │  ← status do sistema compacto (pontos)        │
└──────────┴───────────────────────────────────────────────┘
```

- Trilho lateral de 232 px agrupado em **Practice / Review / Setup**; contador de drills pendentes ao lado de "Drills". Em telas < 760 px vira barra superior com rolagem horizontal.
- Alinhamento à esquerda em tudo; nada centralizado exceto o palco da sala de entrevista.
- Cartões só para **objetos** (um erro, uma vaga, um currículo). Seções de página são separadas por título + espaço, não por caixas.
- Raio de borda por hierarquia: 14 px em painéis, 10 px em controles, 999 px só em chips.

### Onde gastar a ousadia

Um único elemento memorável: o **anel de voz** da sala de entrevista (16.4). O resto fica quieto. Movimento só como resposta a ação ou para indicar estado ao vivo; `prefers-reduced-motion` desliga as animações.

## 16.3 Componentes específicos do produto (`src/components`)

Nada de kit genérico; cada peça existe porque o domínio pede:

| Componente | O que faz |
|---|---|
| `Icon` | conjunto pequeno de ícones SVG em linha (mic, play, stop, speaker, headphones…), substitui os emojis |
| `VoiceRing` | anel da sala: barras radiais que seguem o nível do microfone (âmbar) ou da voz do entrevistador (roxo); arco externo = tempo restante |
| `LevelMeter` | medidor de nível do microfone (teste de mic, drills, coach) |
| `Phoneme` | glifo IPA em Charis SIL, com barras opcionais `/…/` |
| `SpokenText` | trecho falado em Charis SIL, com a cor da voz de quem falou |
| `ScoreDial` | nota geral 1–5 em semicírculo (relatório) |
| `RubricBar` | 5 segmentos por critério |
| `Segmented` | escolha de 2–4 opções com `role="radiogroup"` |
| `ErrorCard` | um erro: original → corrigido, fonemas esperado/ouvido, clipe, "Not an error" |
| `LineChart` / `Sparkline` | evolução; o grande ao clicar numa métrica, o pequeno na leitura |
| `SystemStatus` | pontos de status no rodapé do trilho (API, banco, model server), com detalhe ao abrir |

Áudio: `capture.ts`/`recorder.ts` ganham um callback de **nível** (RMS por quadro de 20 ms); `Player` ganha um `AnalyserNode` com `level()`; `InterviewClient` expõe `levels()` para o anel ler a cada quadro de animação (sem re-render do React).

## 16.4 Páginas

### Today (`/`, antes "Dashboard")
- Saudação com o `display_name` e **o que fazer agora**, como lista de ações: retomar entrevista ativa (se houver), drills pendentes (com botão), nova entrevista.
- **Leituras de evolução**: 5 métricas (pronúncia, gramática/100 palavras, rubrica, WPM, muletas/min), cada uma com último valor, tendência e sparkline. Clicar abre o gráfico grande abaixo; alternância "by interview / by week".
- **Sounds to work on**: grade de fonemas IPA grandes, cor sequencial pela taxa de erro, com contagem.
- **Recurring errors** (30 dias) com barra antes → agora e tendência; **Overcome**.
- Entrevistas recentes (5) com link para o histórico completo.

### New interview (`/interviews/new`)
- Três blocos: **Format** (cartões de tipo com descrição), **Context** (vagas e currículo como opções clicáveis, não `<select>`), **Interviewer** (estilo, senioridade, duração, feedback em controles segmentados).
- Coluna lateral fixa com o **resumo em frase** ("A 30-minute senior system design interview with a tough interviewer, tailored to …") e o botão **Start interview**.

### Interview room (`/interviews/:id`)
- **Lobby:** aviso de fones (uma vez), **teste de microfone** com medidor, modo de turno, **o que a entrevista cobre** (do `plan`: problema de system design, áreas técnicas ou temas comportamentais) e "Join interview".
- **Ao vivo:** palco com o `VoiceRing` no centro e o estado em palavras ("Listening", "Thinking", "Interviewer speaking", "Reconnecting"); tempo restante no arco e em texto. Abaixo, o **roteiro** da conversa em Charis SIL (roxo/âmbar, interrupção marcada). Coluna lateral: plano + feedback ao vivo + latência da última resposta.
- Barra de controles: modo, botão grande de push-to-talk (Space), **End interview** com confirmação em linha (sem `window.confirm`).
- **Encerrada:** painel com links para o relatório e para nova entrevista.

### Report (`/interviews/:id/report`)
- Cabeçalho com `ScoreDial`, tipo, data, contexto; ações **Debrief with coach** e **Regenerate**.
- Faixa de métricas; rubrica com `RubricBar`; pontos fortes × a melhorar; **"You said" × "A stronger answer"** lado a lado; interrupções.
- Transcrição marcada (palavra fraca pontilhada, erro sublinhado e tocável).
- Erros em abas por tipo, agrupados por categoria.
- Estados: gerando (com progresso das análises pendentes), sessão ativa, abandonada (gerar agora).

### Coach (`/interviews/:id/coach`)
- Conversa com a mesma identidade de vozes; streaming; respostas rápidas; perguntar por voz com medidor; ler em voz alta.

### History (`/interviews`) — **nova**
- Todas as entrevistas (`GET /sessions?limit=100`), agrupadas por mês, filtro por tipo e status, nota e link para relatório/retomar.

### Errors (`/errors`)
- Filtros como chips de tipo (com contagens), período segmentado, categorias como lista lateral com contagem, "Show dismissed". Mantém filtros na URL.

### Drills (`/drills`)
- **Início:** número de pendentes, botão de sessão, próxima revisão; **biblioteca** com abas *In practice / Mastered* (`GET /drills/items`), mostrando foco, intervalo, falhas e próxima data.
- **Sessão:** passos numerados (é uma sequência real), cartão de prática com o texto em Charis SIL, gravação com medidor e limite de tempo, resultado com "we heard" e próxima revisão.
- **Fim:** resumo da sessão.

### Resume (`/profile`)
- Área de arrastar-e-soltar para PDF. Currículo ativo como "folha": nome, anos, stack, linha do tempo de cargos, projetos com impacto, conquistas. Outros currículos com "Make active" e "Delete" (confirmação em linha).

### Jobs (`/jobs`)
- Formulário de nova vaga recolhível; lista de vagas com resumo, stack exigida/desejável, responsabilidades e texto original expansível; botão "Practice for this job" que abre New interview já com a vaga.

### Settings (`/settings`)
- Seções com explicação à esquerda e controles à direita. **Preview voice** toca uma frase com a voz/velocidade do rascunho. Barra de salvar fixa quando há alterações.

## 16.5 Qualidade

- Responsivo até 360 px de largura, sem rolagem horizontal da página.
- Foco de teclado visível em tudo (`:focus-visible` com anel âmbar).
- `prefers-reduced-motion` respeitado; tema escuro via `prefers-color-scheme`.
- Contraste AA para texto; cor nunca é o único sinal (ícones/texto acompanham).
- `npm run typecheck`, `npm run build` e `npm test` passam.

## 16.6 Backend (adição mínima)

- `POST /api/speech/tts` aceita `voice` e `speed` **opcionais** (para o preview das configurações); sem eles, usa as configurações salvas como antes.

## Critérios de aceite

- [x] Tokens de cor/tipo da 16.2 aplicados em todas as páginas; fontes empacotadas localmente
- [x] Emojis substituídos por ícones SVG
- [x] Trilho de navegação agrupado, contador de drills, status do sistema compacto
- [x] Sala de entrevista com teste de microfone, plano, anel de voz com nível ao vivo, confirmação ao encerrar
- [x] Página History nova, usando `GET /sessions`
- [x] Biblioteca de drills usando `GET /drills/items`
- [x] New interview sem `<select>` para vaga/estilo/duração; resumo em frase; aceita `?job=<id>`
- [x] Preview da voz nas configurações
- [x] Upload de currículo por arrastar-e-soltar
- [x] Typecheck, build e testes do frontend passando
- [ ] Sala de entrevista ao vivo e sessão de drill usadas de ponta a ponta com voz real
- [ ] Layout conferido em largura de celular (360–390 px)
