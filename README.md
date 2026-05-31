# Como Funciona o Agente Autônomo

Documentação gerada a partir do estudo do projeto `autonom-agent`.

---

## Estrutura do Projeto

```
autonom-agent/
├── runtime/                  # Motor de execução
│   ├── main.py               # CLI de entrada
│   ├── ciclo.py              # Loop principal — orquestra tudo
│   ├── planejador.py         # PERCEBER + PLANEJAR
│   ├── executor.py           # AGIR + AVALIAR
│   ├── ferramentas.py        # Fábrica de ferramentas
│   ├── contratos.py          # Leitura dos .md + criação do estado
│   ├── validador.py          # Validador de contratos
│   └── telemetria.py         # Observabilidade estruturada
│
└── monitor-agent/            # Exemplo de agente implementado
    ├── agent.md              # Identidade do agente
    ├── rules.md              # Regras e limites de segurança
    ├── skills.md             # Definição das ferramentas (interface)
    ├── memory.md             # Configuração de memória e resumo
    ├── hooks.md              # Handlers de ciclo de vida
    └── contracts/
        ├── loop.md           # Configuração do ciclo
        ├── planner.md        # Regras do planejador
        ├── executor.md       # Estratégia de execução
        └── toolbox.md        # Ferramentas disponíveis
```

---

## Os 9 Arquivos .md — A Base do Agente

Todo o comportamento do agente é definido em arquivos `.md` com blocos YAML. Nenhuma implementação de domínio existe no código Python — só a lógica de execução.

| Arquivo | Usado em | Para quê |
|---|---|---|
| `agent.md` | `criar_estado()` | Nome, tipo e objetivo do agente |
| `rules.md` | `criar_estado()` | Limites, ações sensíveis, ferramentas obrigatórias |
| `loop.md` | `criar_estado()` | Objetivo do ciclo e número máximo de etapas |
| `skills.md` | `construir_ferramenta()` + `avaliar()` | Interface de cada ferramenta (nome, entrada, saída) |
| `planner.md` | `construir_prompt_sistema()` | Regras que a LLM do planejador deve seguir |
| `executor.md` | `executar()` | Estratégia de execução (retry, validação) |
| `toolbox.md` | `construir_ferramentas_dos_contratos()` | Ferramentas disponíveis no ciclo |
| `memory.md` | `gerar_resumo_final()` | O que guardar no histórico e como resumir |
| `hooks.md` | `executar_gancho()` | Eventos de log/alerta no ciclo de vida |

---

## O Ciclo Principal — Perceber → Planejar → Agir → Avaliar

O `ciclo.py` orquestra tudo. Ele não implementa nenhuma fase diretamente — delega para os outros módulos.

### Quem faz o quê

| Fase | Arquivo | Função |
|---|---|---|
| Perceber | `planejador.py` | `perceber(estado)` |
| Planejar | `planejador.py` | `chamar_llm(percepcao, contratos, historico)` |
| Agir | `executor.py` + `ferramentas.py` | `executar(nome, argumentos, ferramentas, contratos)` |
| Avaliar | `executor.py` | `avaliar(plano, resultado_acao, contratos)` |
| Orquestrar | `ciclo.py` | `rodar(caminho_agente, texto_entrada)` |

---

## Ordem de Execução ao Rodar o Agente

```
ciclo.rodar()
    │
    ├── 1. contratos.carregar_contratos()     # lê os 9 arquivos .md
    ├── 2. contratos.criar_estado()           # cria o dicionário de estado
    ├── 3. ferramentas.construir_ferramentas_dos_contratos()  # cria as funções
    ├── 4. Telemetria()                       # inicia observabilidade
    │
    └── LOOP (enquanto não concluído e etapa < max_etapas):
            │
            ├── verifica limite de tempo
            ├── verifica limite de tokens
            │
            ├── PERCEBER  → perceber(estado)
            ├── PLANEJAR  → chamar_llm(percepcao, contratos)
            │
            ├── circuit breaker → valida resposta da LLM
            ├── verifica FINALIZAR + ferramentas obrigatórias
            ├── verifica limites de chamadas + estagnação
            ├── verifica ação sensível → confirmação humana
            │
            ├── AGIR      → executar(nome, argumentos, ferramentas, contratos)
            └── AVALIAR   → avaliar(plano, resultado_acao, contratos)
```

---

## O Estado

### Onde nasce

O estado é criado **uma única vez** em `contratos.criar_estado()` (antes do loop), usando três arquivos `.md` e o input do usuário:

```python
estado = {
    # de agent.md
    "tipo_agente":           "task_based",

    # de loop.md
    "objetivo":              "resolver_incidente",

    # de rules.md
    "max_etapas":            10,
    "max_chamadas_ferramenta": 9,
    "limite_tempo_segundos": 120,
    "max_tokens":            50000,
    "acoes_sensiveis":       ["rollback_deploy"],

    # do input do usuário
    "entrada":               "latência do checkout aumentou 300%",

    # começa zerado — atualizado durante o loop
    "etapa":                 0,
    "chamadas_ferramenta":   0,
    "chamadas_por_ferramenta": {},
    "tokens_consumidos":     {"prompt": 0, "completion": 0, "total": 0},
    "historico":             [],
    "concluido":             False,
}
```

### Como é atualizado no loop (`ciclo.py`)

| Campo | Quando muda |
|---|---|
| `etapa` | Início de cada iteração |
| `chamadas_ferramenta` | Após executar qualquer ferramenta |
| `chamadas_por_ferramenta` | Após executar, por nome de ferramenta |
| `tokens_consumidos` | Após cada chamada à LLM (planejador + ferramenta) |
| `historico` | Ao final de cada etapa completa |
| `concluido` | Quando FINALIZAR, limite atingido ou erro crítico |

### Persistência

- Durante a execução: **somente em memória**
- Ao terminar: salvo em `runtime/trace.json` com histórico completo + telemetria
- `replay()` lê o `trace.json` para repetir a mesma execução com o mesmo input

---

## PERCEBER — `planejador.perceber(estado)`

Não chama LLM. Monta uma string de contexto com quatro informações do estado:

```python
partes = [f"Alerta: {estado['entrada']}"]                           # 1. input do usuário
# + histórico de etapas anteriores (linha 35-40)                   # 2. o que já aconteceu
partes.append(f"Ferramentas ja utilizadas: ...")                    # 3. quais ferramentas já foram chamadas
partes.append(f"Etapas realizadas: {etapa}/{max_etapas}")           # 4. quanto resta
return "\n".join(partes)
```

Essa string é exatamente o que a LLM recebe como `user message` na fase de PLANEJAR.

---

## PLANEJAR — `planejador.chamar_llm(percepcao, contratos)`

Chama a LLM com dois inputs:

- **system prompt**: construído a partir dos contratos (ferramentas disponíveis, regras do `planner.md`, políticas do `rules.md`)
- **user message**: a string montada pelo `perceber()`

A LLM retorna um JSON com a decisão:

```json
{
  "proxima_acao": "CHAMAR_FERRAMENTA",
  "nome_ferramenta": "consultar_metricas",
  "argumentos_ferramenta": {
    "nome_servico": "checkout",
    "janela_tempo_minutos": 30
  },
  "criterio_sucesso": "obter métricas atuais do serviço"
}
```

`proxima_acao` só pode ser um de três valores: `CHAMAR_FERRAMENTA`, `FINALIZAR` ou `PERGUNTAR_USUARIO`.

---

## As Ferramentas

### Como são criadas

As ferramentas são criadas **em runtime**, a cada execução, a partir do `skills.md`. Nenhuma implementação real existe no código.

`skills.md` define apenas a **interface**:

```yaml
- nome: consultar_metricas
  descricao: consulta metricas de latencia, throughput e taxa de erro
  entrada:
    nome_servico: string
    janela_tempo_minutos: int
  saida:
    latencia_p99_ms: float
    vazao_rps: int
    taxa_erro: float
    status: string
```

`ferramentas.construir_ferramenta()` usa essa interface para gerar dinamicamente uma função Python via **closure**:

```
skills.md (interface)
    │
    ▼
construir_ferramenta()     ← sem chamar LLM
    │
    └── retorna função Python com prompt_sistema embutido
              │
              ▼ (quando EXECUTADA pelo AGIR)
         chama LLM para gerar dados simulados realistas
```

### Como a LLM da ferramenta funciona

É uma simulação — a LLM recebe a descrição da ferramenta e os argumentos, e **inventa dados plausíveis**:

```
system: "Você é consultar_metricas. Gere JSON com: latencia_p99_ms: float, vazao_rps: int..."
user:   "Argumentos: {nome_servico: checkout, janela_tempo_minutos: 30}"
saída:  {"latencia_p99_ms": 1842.5, "vazao_rps": 312, "taxa_erro": 0.087, "status": "degradado"}
```

Em produção, o interior de cada função seria substituído por chamadas reais a APIs, bancos ou sistemas de monitoramento. O ciclo permanece idêntico.

---

## AGIR — `executor.executar()`

Antes de executar, valida o payload (linha 39 de `executor.py`):

```python
def validar_payload(nome_ferramenta, argumentos, contratos):
    # campo obrigatório presente?
    # tipo bate com o schema do skills.md?
    # retorna lista de erros (não bloqueia — graceful degradation)
```

Executa a ferramenta. Se `executor.md` tiver `tentar_novamente_em_falha: true`, tenta uma segunda vez em caso de exceção.

---

## AVALIAR — `executor.avaliar()`

Lógica Python pura — sem LLM. Três caminhos:

```
plano era FINALIZAR?
    └── objetivo_alcancado: True  (encerra o loop)

ferramenta falhou tecnicamente?
    └── qualidade: "falha"

ferramenta funcionou → valida saída contra schema do skills.md
    ├── campos faltando ou vazios → qualidade: "parcial"
    └── tudo certo               → qualidade: "completa"
```

`objetivo_alcancado` só vira `True` quando a LLM do planejador decide `FINALIZAR`. É a LLM quem decide quando parar — não o avaliador.

O resultado entra no `historico` e o `perceber()` da próxima etapa vai incluí-lo no contexto.

---

## Onde a LLM é chamada

Apenas **dois pontos** no código fazem chamadas reais à LLM:

| Arquivo | Linha | Fase | Propósito |
|---|---|---|---|
| `planejador.py` | 163 | PLANEJAR | Decidir o próximo passo (qual ferramenta, quais argumentos, ou finalizar) |
| `ferramentas.py` | 36 | AGIR | Gerar dados simulados realistas para a ferramenta executada |

Por etapa do loop, o consumo máximo é **2 chamadas LLM** (1 do planejador + 1 da ferramenta). Etapas com `FINALIZAR` consomem apenas 1.

```
Total de chamadas LLM = (número de etapas × 1) + (ferramentas executadas × 1)
```

---

## Proteções de Segurança

Todas implementadas em `ciclo.py`, em camadas:

### 1. Limites de tempo e tokens (início de cada etapa)

```yaml
# rules.md
limites:
  limite_tempo_segundos: 120
  max_tokens: 50000
```

Verificados antes de qualquer coisa. Encerram o loop imediatamente se excedidos.

### 2. Circuit Breaker (entre PLANEJAR e AGIR)

Valida a resposta da LLM antes de executar qualquer coisa:

- `proxima_acao` é um dos 3 valores válidos?
- A ferramenta indicada existe?
- Os argumentos são um dicionário?

Tenta auto-corrigir antes de encerrar. Registrado na telemetria como `circuit_breaker_ativacoes`.

### 3. Limites de chamadas de ferramenta (antes do AGIR)

```yaml
# rules.md
limites:
  chamadas_ferramenta:
    consultar_metricas: 3
    total: 9
  sem_progresso: 3
```

Três verificações distintas: total de chamadas, limite por ferramenta individual e estagnação (mesma ferramenta N vezes seguidas).

### 4. Ferramentas obrigatórias (quando FINALIZAR)

```yaml
# rules.md
ferramentas_obrigatorias: [relatorio_incidente]
```

Se a LLM tentar finalizar sem ter chamado uma ferramenta obrigatória, o sistema intercepta e força a chamada antes de aceitar o `FINALIZAR`.

### 5. Confirmação humana para ações sensíveis (antes do AGIR)

```yaml
# rules.md
acoes_sensiveis: [rollback_deploy]
```

Pausa a execução e exige aprovação do operador. Se negado, encerra com segurança.

### Camadas no fluxo

```
início da etapa
    ├── [1] tempo excedido?   → encerra
    ├── [1] tokens excedidos? → encerra
    PERCEBER → PLANEJAR
    ├── [2] circuit breaker   → corrige ou encerra
    ├── [4] quer FINALIZAR + ferramenta obrigatória pendente? → força chamada
    ├── [3] limite de chamadas atingido? → encerra
    ├── [3] estagnação?       → encerra
    ├── [5] ação sensível?    → confirmação humana
    AGIR → AVALIAR
```

---

## memory.md — O que ele controla

Não é só telemetria. Tem duas responsabilidades:

**1. Memória de curto prazo** — o que entra no histórico durante o loop:

```yaml
memoria_curta:
  guardar:   [resultado_de_ferramenta, decisao_do_planejador, evidencia_coletada]
  descartar: [prompt_sistema_completo, argumentos_mock_internos]
  max_registros: 20
```

**2. Formato do resumo final** — gerado por `gerar_resumo_final()` ao terminar:

```yaml
resumo_final:
  max_linhas: 5
  campos: [objetivo, etapas_executadas, ferramentas_chamadas, resultado_final]
```

A telemetria é gerenciada separadamente pela classe `Telemetria` em `telemetria.py`.
