# Spec 03 — Motor de entrevista: currículo, vagas e entrevistador

**Status:** 🟨 Em andamento — implementado e coberto por testes com LLM falso; falta validar o comportamento do entrevistador com o LLM real (OpenRouter) e as páginas no navegador  <!-- implementador: atualize para 🟨 Em andamento / ✅ Concluído -->

**Depende de:** 02-voice-loop

> **Para o agente implementador:** leia antes o [`00-overview.md`](00-overview.md) (decisões fixas, arquitetura, modelo de dados, requisitos não funcionais).
> Marque os checkboxes `[x]` conforme concluir e atualize o **Status** acima e a tabela de progresso no overview.
> A numeração das seções é **global** entre os arquivos (ex.: "seção 5.4" está no overview).
> Onde aparecer **VERIFICAR**, confira na documentação/código da biblioteca antes de implementar.

Troca o entrevistador genérico da spec 02 por entrevistas reais dos três tipos, personalizadas pelo currículo e pela vaga, com estilos configuráveis e gestão de tempo. Inclui as páginas **Profile**, **Jobs**, **NewInterview** e **Settings**.

---

## 6. Personalização: currículo e vaga

### 6.1 Currículo (PDF)

1. Upload do PDF na página **Profile**; salvar em `data/uploads/`.
2. Extrair texto (`pypdf` ou `pdfplumber`).
3. DeepSeek extrai o `parsed_profile` em **JSON estruturado** (usar JSON mode/structured output da API; validar com Pydantic; retentar uma vez se inválido).
4. Mostrar o perfil extraído para o usuário (só leitura no MVP, com botão "re-parse"). Um currículo fica marcado como `is_active`.

### 6.2 Vaga

1. Página **Jobs**: colar a descrição da vaga; salvar várias.
2. DeepSeek extrai `parsed` (stack, senioridade inferida, requisitos, domínio).
3. Ao iniciar uma entrevista, o usuário escolhe opcionalmente uma vaga.

### 6.3 Como isso afeta a entrevista

- **Stack das perguntas técnicas**: vem da vaga, ou do currículo se não houver vaga. É **variável**: o usuário trabalha com Node.js/TypeScript e Python, mas a vaga manda.
- **Senioridade**: vem da vaga ou da configuração (pleno/sênior); sempre editável na tela de nova entrevista.
- **Comportamental**: perguntas STAR ancoradas nos projetos reais do currículo.
- **System design**: escolher problemas compatíveis com o domínio da vaga quando possível.

---

## 9. Motor de entrevista (LLM)

### 9.1 Configuração da sessão (tela "New Interview")

- tipo: system design, técnica ou comportamental;
- vaga (opcional) e currículo ativo;
- senioridade: pleno ou sênior;
- estilo: friendly, neutral ou tough;
- duração: 15, 30, 45 ou 60 min;
- modo de feedback: live, end ou hybrid.

Os padrões vêm de `user_settings`.

### 9.2 Prompt do entrevistador (montagem)

O system prompt contém:
- persona e estilo;
- tipo e roteiro do tipo (9.3);
- senioridade esperada;
- resumo da vaga e do perfil;
- regras de voz: respostas curtas e faladas, sem markdown e sem listas, uma pergunta por vez, sem ler código em voz alta;
- regras de interrupção (7.6).

Durante a sessão, o backend injeta mensagens de sistema com o **tempo restante**. O entrevistador administra o tempo e, no fim, pergunta "Do you have any questions for me?" e encerra.

O entrevistador **não corrige o inglês durante a entrevista** (isso é papel do feedback, seção 10). Ele só reage ao conteúdo, como um entrevistador real.

### 9.3 Roteiros e rubricas por tipo

- **System design**:
  - roteiro: problema (escolhido e salvo em `plan`) → requisitos funcionais e não funcionais → estimativas → API e modelo de dados → arquitetura em alto nível → aprofundamentos (gargalos, escala, consistência, falhas) → trade-offs;
  - o entrevistador faz perguntas de aprofundamento conforme as respostas;
  - rubrica 1–5 por etapa: requisitos, estimativa, arquitetura, aprofundamento, trade-offs, comunicação.
- **Técnica**:
  - perguntas sobre a stack da vaga ou do currículo (linguagem, runtime, bancos, filas, concorrência, APIs, testes, observabilidade), subindo a profundidade conforme a senioridade;
  - rubrica: correção técnica, profundidade, clareza, exemplos práticos.
- **Comportamental**:
  - perguntas STAR ancoradas no currículo (incidente em produção, conflito, liderança, falha, entrega difícil);
  - rubrica: estrutura STAR, ser específico, impacto quantificado, papel pessoal ("I" vs "we"), concisão.

### 9.4 Estilos

- **Friendly**: encorajador, dá dicas se o candidato travar.
- **Neutral**: realista, educado, sem dicas.
- **Tough**: pressiona, faz perguntas de aprofundamento, questiona premissas, e pode interromper respostas muito longas. Para isso, o entrevistador pode tomar a palavra se o candidato falar mais de ~3 min sem pausa. Implementar como regra do orquestrador, só nesse estilo.

---

---

## Checklist de aceite

- [x] Upload de currículo em PDF → texto extraído → `parsed_profile` validado com Pydantic
- [x] Página Profile mostra o perfil extraído, com "re-parse" e currículo ativo
- [x] Página Jobs: colar, salvar, listar e apagar vagas; `parsed` extraído pelo LLM
- [x] Página NewInterview com todas as opções da seção 9.1 e padrões vindos de `user_settings`
- [x] Página Settings edita `user_settings`
- [ ] System design: problema escolhido e salvo em `plan`; o entrevistador segue o roteiro e faz perguntas de aprofundamento  <!-- problema escolhido pelo domínio da vaga e salvo em `plan` (testado); seguir o roteiro depende do LLM real -->
- [ ] Técnica: perguntas da stack da vaga, ou do currículo se não houver vaga  <!-- `plan.stack` vem da vaga ou do currículo (testado); as perguntas dependem do LLM real -->
- [ ] Comportamental: perguntas STAR ancoradas nos projetos do currículo  <!-- projetos do currículo em `plan.anchor_projects` (testado); as perguntas dependem do LLM real -->
- [ ] Estilos friendly, neutral e tough perceptivelmente diferentes; o tough interrompe respostas com mais de ~3 min  <!-- corte do tough testado (limite reduzido no teste); a diferença perceptível entre estilos depende do LLM real -->
- [ ] O entrevistador não corrige o inglês durante a entrevista  <!-- regra explícita no prompt; validar com o LLM real -->
- [x] Gestão de tempo: a sessão termina perto da duração configurada, com "Do you have any questions for me?"  <!-- nota de tempo por resposta + encerramento pelo marcador, com parada forçada 3 min após o fim (testado com LLM falso) -->
- [x] Sessões e turnos persistidos (`interview_sessions`, `turns`), com o status atualizado no fim ou no abandono
- [x] O system prompt fica estável no início, para aproveitar o cache do DeepSeek

