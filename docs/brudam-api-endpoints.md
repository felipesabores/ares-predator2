# Brudam API — endpoints

Fonte: https://acertaexpress.brudam.com.br/docs/swagger.php (Swagger 2.0, versão 1.1.2)  
Base URL: https://acertaexpress.brudam.com.br/api/v1  
Autenticação: Bearer (JWT no header Authorization)  
Total: 49 operações em 45 caminhos, 16 tags

## Tags

- **Login** — 1 endpoint(s)
- **Ocorrências** — 10 endpoint(s)
- **Embarque Aéreo** — 1 endpoint(s)
- **CT-e** — 4 endpoint(s)
- **Faturas** — 3 endpoint(s)
- **Minutas** — 5 endpoint(s)
- **Manifestos** — 7 endpoint(s)
- **Coletas** — 6 endpoint(s)
- **Cotações** — 2 endpoint(s)
- **Custos** — 1 endpoint(s)
- **Frete** — 1 endpoint(s)
- **Empresas** — 4 endpoint(s)
- **Prazos** — 1 endpoint(s)
- **Financeiro** — 1 endpoint(s)
- **Abastecimento** — 1 endpoint(s)
- **Trechos** — 1 endpoint(s)

## Login

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/acesso/auth/login` | Permite os usuários efetuarem o logim e receber o Token para as chamadas da API. | body: usuario*, senha* |

## Ocorrências

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/tracking/ocorrencias` | Insere no sistema ocorrências para uma entrega | body: auth, documentos |
| GET | `/tracking/ocorrencias/nfe` | Busca no sistema as ocorrências para uma determinada NF-e ou lista de NF-es. | chave (query, obrig.); comprovante (query) |
| GET | `/tracking/ocorrencias/cte` | Busca no sistema as ocorrências para um determinado CT-e ou lista de CT-es. | chave (query, obrig.); comprovante (query) |
| GET | `/tracking/ocorrencias/minuta` | Busca no sistema as ocorrências para uma determinada Minuta ou lista de Minutas. | codigo (query, obrig.); comprovante (query) |
| GET | `/tracking/ocorrencias/coleta` | Busca no sistema as ocorrências para uma determinada Coleta ou lista de Coletas. | codigo (query, obrig.) |
| GET | `/tracking/ocorrencias/cnpj/cte` | Busca no sistema as ocorrências para um determinado CTe e um remetente ou destinatário específico. | documento (query, obrig.); numero (query, obrig.); comprovante (query) |
| GET | `/tracking/ocorrencias/cnpj/nf` | Busca no sistema as ocorrências para uma determinada NF e um remetente ou destinatário específico. | documento (query, obrig.); numero (query, obrig.); comprovante (query) |
| GET | `/tracking/ocorrencias/pedidonf` | Busca no sistema as ocorrências para uma determinada NF-e. | numero (query, obrig.) |
| GET | `/tracking/ocorrencias/pedido` | Busca no sistema as ocorrências para uma determinada NF-e. | pedidos (query, obrig.) |
| GET | `/tracking/ocorrencias/aut_frete` | Busca no sistema as ocorrências de minutas conforme os valores da autorização de frete. | frete (query, obrig.) |

## Embarque Aéreo

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/embarque/aereo` | Insere no sistema um novo embarque aéreo | body: documentos |

## CT-e

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| GET | `/dfe/cte/nota` | Efetua consulta dos CT-es emitidos pela chave da nota fiscal | chave_nfe (query, obrig.) |
| GET | `/dfe/cte` | Efetua consulta dos CT-es emitidos | chave (query, obrig.) |
| POST | `/dfe/cte` | Insere no sistema uma nova minuta com base no CT-e enviado. Somente são permitidos **CT-es autorizados** nos últimos **30 dias**. | body: documentos |
| GET | `/dfe/cancela/cte/{chaveCte}` | Efetua consulta dos CT-es emitidos | chaveCte (path, obrig.) |

## Faturas

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| GET | `/financeiro/faturas` | Efetua consulta de lancamentos | emissao[gt] (query); emissao[gte] (query); emissao[lt] (query); emissao[lte] (query); emissao[eq] (query); vencimento[gt] (query); vencimento[gte] (query); vencimento[lt] (query); vencimento[lte] (query); vencimento[eq] (query); status (query); status[eq] (query); status[in] (query); status[nin] (query); cnpj (query); id (query); id[ne] (query); id[eq] (query); id[gt] (query); id[gte] (query); id[lt] (query); id[lte] (query); id[in] (query); id[nin] (query); limit (query); skip (query) |
| POST | `/financeiro/faturas` | Efetua inclusão de faturas | body: dEmis*, dVecto*, compet*, nFat*, nDocEmit*, nDocCli*, vFat*, vDesc, vAcre, xDescr, xObs, cStatus* … |
| POST | `/financeiro/alteracao/fatura` | Atualiza os dados da fatura no sistema | body: nFat*, vFat, cStatus, dVecto, nDocEmit*, nDocCli*, vDesc, vAcre, xDescr, xObs, formaPagto, documentos |

## Minutas

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/operacional/emissao/cte` | Gera minuta no sistema com os dados necessários para emitir um CTe | body: documentos |
| POST | `/operacional/emissao/minuta` | Gera minuta no sistema com os dados mínimos necessários | body: documentos |
| GET | `/operacional/consulta/minuta/{id}` | Consulta os dados de uma minuta no sistema com o envio do ID da minuta ou a Chave do CTe da minuta | id (path, obrig.) |
| GET | `/operacional/cancela/minuta/{id}` | Cancela uma minuta no sistema com o envio do ID | id (path, obrig.) |
| POST | `/operacional/alteracao/minuta_perecivel` | Altera controle de temperatura da minuta para perecível e atualiza data e hora da troca do gelo. | body: minuta*, data* |

## Manifestos

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/operacional/emissao/manifesto` | Gera manifestos no sistema com os dados necessários para emitir um MDFe | body: tpMan*, coletas, entregas, embarque, retira, Custos, nDocEmit, nDocMot, tpMot, placa*, cRoteiro, nLacres … |
| POST | `/operacional/alteracao/manifesto` | Atualiza os dados dos manifestos no sistema | body: idMan*, tpMan*, coletas, entregas, embarque, retira, cte, notas, nDocEmit, nDocMot, tpMot, placa … |
| POST | `/operacional/alteracao/manifesto/saidaEfetiva` | Atualiza os dados dos manifestos no sistema e realiza a saida efetiva | body: idMan*, kmInicial, dataSaida, dataChegada |
| POST | `/operacional/alteracao/manifesto/finalizarManifesto` | Atualiza os dados dos manifestos no sistema e realiza finalização do manifesto | body: idMan*, kmFinal, dataChegada |
| GET | `/operacional/cancela/manifesto/{id}` | Cancela um manifesto no sistema com o envio do ID | id (path, obrig.) |
| GET | `/operacional/consulta/manifesto/{id}` | Consulta um manifesto no sistema com o envio do ID | id (path, obrig.) |
| GET | `/operacional/consulta/manifestos` | Consulta manifestos no sistema por intervalo de data de emissão e status, com paginação | dataini (query, obrig.); datafim (query, obrig.); status (query, obrig.); pagina (query) |

## Coletas

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/operacional/emissao/coleta` | Gerar coleta | body: documentos |
| POST | `/operacional/alteracao/coleta` | Alterar coleta | body: documentos |
| PUT | `/operacional/alteracao/coleta/{id}` | Inclui um ou mais documentos fiscais em uma coleta já existente, atualizando peso, volumes e valor totais da coleta | id (path, obrig.); body: documentos |
| POST | `/operacional/consulta/coletas` | Listar coletas | body: documentos |
| GET | `/operacional/consulta/coleta/{id}` | Consulta os dados de uma coleta no sistema com o envio do ID | id (path, obrig.) |
| GET | `/operacional/cancela/coleta/{id}` | Cancela uma coleta no sistema com o envio do ID | id (path, obrig.) |

## Cotações

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/comercial/emissao/cotacao` | Gerar cotações de frete | body: nDocEmit*, nDocCli*, solicit, telSolicit, rem, dest, cOrigCalc*, cDestCalc*, CEP, cTab, cServ, pBru* … |
| POST | `/comercial/alteracao/cotacao` | Alterar status cotação | body: idCotacao*, idStatus* |

## Custos

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| GET | `/operacional/custos` | Efetua consulta de custos | emissao[gt] (query); emissao[gte] (query); emissao[lt] (query); emissao[lte] (query); emissao[eq] (query); inclusao[gt] (query); inclusao[gte] (query); inclusao[lt] (query); inclusao[lte] (query); inclusao[eq] (query); autorizacao[gt] (query); autorizacao[gte] (query); autorizacao[lt] (query); autorizacao[lte] (query); autorizacao[eq] (query); cancelamento[gt] (query); cancelamento[gte] (query); cancelamento[lt] (query); cancelamento[lte] (query); cancelamento[eq] (query); status (query); status[eq] (query); status[in] (query); status[nin] (query); cnpj (query); id (query); id[ne] (query); id[eq] (query); id[gt] (query); id[gte] (query); id[lt] (query); id[lte] (query); id[in] (query); id[nin] (query); numero (query); numero[ne] (query); numero[eq] (query); numero[gt] (query); numero[gte] (query); numero[lt] (query); numero[lte] (query); numero[in] (query); numero[nin] (query); serie (query); serie[eq] (query); serie[in] (query); serie[nin] (query); tipo (query); limit (query); skip (query) |

## Frete

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/frete/cotacao/calcula` | Realiza o cálculo de frete | body: nDocEmit*, nDocCli*, nDocRem, nDocDest, cOrigCalc*, cDestCalc*, CEP, cTab, cServ, pBru*, pCub, qVol* … |

## Empresas

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| GET | `/cadastro/empresas` | Efetua consulta de empresas | cnpj (query); id (query); data_inicial (query); data_final (query) |
| POST | `/cadastro/empresas` | Efetua o cadastro de empresas. | body: tipo, nCNPJ*, xFant*, xNome*, IE*, cFiscal*, xLgr*, nro*, xCpl, xBairro*, cMun*, CEP* … |
| PATCH | `/cadastro/empresas` | Atualiza o cadastro de empresas. | body: nCNPJ*, xFant, xNome, IE, cFiscal, xLgr, nro, xCpl, xBairro, cMun, CEP, xContato … |
| POST | `/cadastro/empresas/motorista` | Efetua o cadastro de motoristas. | body: fornecedor*, motorista* |

## Prazos

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/prazos/entrega` | Busca no sistema os prazos de entrega por trecho. | body: cIbgeOrig*, cIbgeDest*, cModal*, cServ, cepOrig, cepDest |

## Financeiro

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/financeiro/liquidar/lancamento` | Realiza a liquidação de lançamentos financeiro | body: documentos* |

## Abastecimento

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/frota/emissao/abastecimento` | Insere no sistema uma nova ordem de abastecimento. | body: data*, hora*, funcionario*, fornecedor*, posto*, veiculo*, produto*, transacao, valor*, litros*, kmAnterior*, kmAtual* … |

## Trechos

| Método | Caminho | Resumo | Parâmetros principais |
|---|---|---|---|
| POST | `/cadastro/trechos/{idTabela}` | Cadastra um novo trecho em uma tabela de frete. | body: origem, destino, tarifas, tde, prazo, devolucao, reentrega, soma_icms*, reverso*, servico*, tipo_emissao, valor_minimo_trecho* |

\* = campo obrigatório no body.
