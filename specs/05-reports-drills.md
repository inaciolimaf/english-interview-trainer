# Spec 05 — Relatórios, painel de evolução e drills

**Status:** 🟨 Em andamento — implementado e coberto por testes (LLM falso + model server real); falta validar com o LLM real (OpenRouter) e com uso real ao longo de várias sessões  <!-- implementador: atualize para 🟨 Em andamento / ✅ Concluído -->

**Depende de:** 04-analysis-feedback

> **Para o agente implementador:** leia antes o [`00-overview.md`](00-overview.md) (decisões fixas, arquitetura, modelo de dados, requisitos não funcionais).
> Marque os checkboxes `[x]` conforme concluir e atualize o **Status** acima e a tabela de progresso no overview.
> A numeração das seções é **global** entre os arquivos (ex.: "seção 5.4" está no overview).
> Onde aparecer **VERIFICAR**, confira na documentação/código da biblioteca antes de implementar.

Fecha o ciclo de aprendizado: relatório completo de cada sessão, painel de evolução, explorador de erros e sessões de drill com repetição espaçada. Inclui as páginas **Report**, **Dashboard**, **Errors** e **Drills**.

---

### 10.4 Relatório da sessão (`report jsonb` + página **Report**)

Gerado ao final (DeepSeek, com todos os turnos e erros):
- notas da rubrica do tipo, com justificativa;
- pontos fortes, os 3 principais pontos a melhorar e um exemplo de resposta melhor para a pergunta mais fraca;
- transcrição completa, com cada palavra do candidato colorida pela nota de pronúncia; clicar numa palavra com erro toca o clipe;
- lista de erros por tipo, com original → corrigido + explicação + clipe; cada um com o botão "Not an error";
- métricas de fluência;
- avaliação de como o candidato interrompeu, quando houver.

---

## 11. Drills (página **Drills**)

- **Geração**: depois de cada sessão, erros não dispensados viram `drill_items` (deduplicar por `category` + palavra/regra; um erro recorrente reforça o item existente).
  - `pron_read`: o LLM gera 2–3 frases curtas e naturais, de contexto técnico, contendo a palavra ou fonema problemático.
  - `grammar_rewrite`: mostra a frase errada do usuário; ele **fala** a versão corrigida.
  - `tech_explain`: pede para explicar em 30–60 s um conceito em que errou.
- **Sessão de drill** (5–10 min): pega os itens com `due_at <= now`, priorizando `lapses` altos.
  - `pron_read` usa **modo roteiro**: o texto esperado é conhecido, então a análise de fonemas usa o texto de referência, e não a transcrição. É mais preciso.
- **SRS**: SM-2 simplificado. Acerto → aumenta o intervalo. Erro → `lapses++` e o item volta logo. Item com 3 acertos seguidos em intervalos ≥ 7 dias → `retired`.
- Suspeitos de pronúncia (8.2) entram como `pron_read` para confirmação.

---

## 12. Painel de evolução (página **Dashboard**)

- **Ao longo do tempo** (por sessão e por semana):
  - nota média de pronúncia;
  - erros de gramática a cada 100 palavras;
  - notas da rubrica por tipo;
  - WPM;
  - muletas por minuto.
- **Top 5 erros recorrentes** (por `category`, janela de 30 dias), com tendência ↑/↓.
- **Erros superados**: categorias com queda forte de frequência e drills `retired`.
- **Heatmap de fonemas**: taxa de erro por fonema.
- Contador de drills pendentes e botão "Start drill session".
- Página **Errors**: explorador com filtros (tipo, categoria, período, dispensados), clipes tocáveis e o botão "Not an error".

---

### Futuro (fora do escopo)
- Quadro de desenho para system design (Excalidraw), com o diagrama enviado ao DeepSeek, que tem visão.
- Login e múltiplos usuários de fato.
- Voz do entrevistador via AWS Polly Generative, como opção paga.

---

---

## Checklist de aceite

### Relatório (seção 10.4)
- [x] Relatório gerado ao fim da sessão e salvo em `report jsonb`
- [x] Notas da rubrica com justificativa, pontos fortes, 3 pontos a melhorar e um exemplo de resposta melhor  <!-- vêm do LLM; sem LLM, o relatório mostra métricas e erros e avisa que falta a avaliação escrita -->
- [x] Transcrição com as palavras coloridas pela nota de pronúncia; clicar numa palavra toca o clipe
- [x] Lista de erros com original → corrigido, explicação, clipe e "Not an error"
- [x] Avaliação de como o candidato interrompeu, quando houver

### Painel e erros (seção 12)
- [x] Gráficos de evolução: pronúncia, erros de gramática a cada 100 palavras, rubrica, WPM, muletas
- [x] Top 5 erros recorrentes (30 dias), com tendência
- [x] Erros superados
- [x] Heatmap de fonemas
- [x] Página Errors com filtros, clipes e "Not an error"
- [x] Com 3 ou mais sessões de dados, o painel mostra tendências coerentes  <!-- testado com 3 sessões sintéticas (40/20/5 dias): tendência ↓/↑ e categoria superada corretas -->

### Drills (seção 11)
- [x] Erros não dispensados viram `drill_items` (deduplicados; um erro recorrente reforça o item existente)
- [x] Geração dos três tipos: `pron_read`, `grammar_rewrite`, `tech_explain`
- [x] Sessão de drill de 5–10 min com os itens vencidos, priorizando lapsos
- [x] `pron_read` usa o **modo roteiro** (análise com o texto de referência)  <!-- reprova só por erro no foco do item; leitura limpa passa e "tink" reprova (testado com áudio sintético) -->
- [x] SRS (SM-2) reagenda os itens; itens dominados ficam `retired`
- [x] Suspeitos de pronúncia entram como drill de confirmação
- [x] Testes unitários do SM-2

### Notas da implementação

- Relatório e drills rodam na mesma fila do worker de análise, depois das análises dos turnos da sessão (FIFO). Sessões abandonadas geram relatório pelo botão da página Report (`POST /api/sessions/{id}/report`).
- "Nota média de pronúncia" = **precisão de pronúncia**: % das palavras avaliadas sem erro de fonema. As cores da transcrição vêm do menor z-score dos fonemas de cada palavra em relação à calibração nativa.
- Tendência do Top 5: taxa por 100 palavras nos últimos 15 dias vs. os 15 anteriores. Superados: queda ≥ 60% na taxa de 30 dias vs. os 30 anteriores (mínimo de 3 ocorrências).
- SM-2: acerto → 1 dia, 3 dias, depois intervalo × facilidade; erro → `lapses++` e volta em 10 min; 3 acertos seguidos com intervalo ≥ 7 dias → `retired` (`drill_items.mature_streak`, migration 0002). Um suspeito lido corretamente é aposentado na hora.
- `grammar_rewrite`: aprovado com similaridade ≥ 0,8 (Levenshtein por palavra) com a frase corrigida. `tech_explain`: julgado pelo LLM; sem LLM, conta como prática pela duração.
