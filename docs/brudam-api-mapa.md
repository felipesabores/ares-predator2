# API oficial do Brudam × relatórios do predator

Fonte: especificação Swagger 2.0 v1.1.2 em `https://acertaexpress.brudam.com.br/docs/swagger.php`
(lista completa em [`brudam-api-endpoints.md`](brudam-api-endpoints.md)). Base `…/api/v1`, login em
`POST /acesso/auth/login` (usuário + senha → token JWT no header `Authorization: Bearer`).
Credenciais só no `.env` (`BRUDAM_API_USER`, `BRUDAM_API_PASS`, `BRUDAM_API_TOKEN`).

Mapa feito em 07/11/2026 só lendo a especificação; ainda não testado com chamadas reais.

| Relatório | Tabela | Endpoint da API | Cobertura |
|---|---|---|---|
| 138 Coletas | `coletas` | `POST /operacional/consulta/coletas` | **Boa**: lista coletas com cliente, origem/destino, peso, volumes, NFs e minutas. Conferir filtros de data no body. |
| 147 Custo por operação | `custos_operacao` | `GET /operacional/custos` | **Parcial**: custo de coleta, entrega e despacho por minuta, com filtros de data (`emissao[gte]`…), status, CNPJ e paginação (`limit`/`skip`). Não traz receita/margem do 147; cruzar com outra fonte. |
| 106 / 106f Emissões | `emissoes`, `emissoes_dia` | — | **Não tem lista**. Só `GET /operacional/consulta/minuta/{id}` (uma por vez). Continua pelo relatório web. |
| 027 Cotações | `cotacoes` | — | Só criar/alterar cotação; sem consulta. Continua web. |
| 399 Remessas/agendamentos | `remessas` | — | Sem endpoint. Continua web. |
| 129 AWBs | `awbs` | (talvez `GET /operacional/consulta/manifestos`) | Manifestos por período e status, 50 por página; avaliar se cobre os embarques aéreos. |
| 295 Canhotos/reclamações | `canhotos` | — | Ocorrências só por documento (CT-e, NF, minuta). Continua web. |
| 314 Perecíveis | `pereciveis` | — | Só alteração de perecível. Continua web. |

**Dados novos que a API oferece** (bons para os KPIs do 2.0 e a I.A do WhatsApp):
- `GET /financeiro/faturas`: faturas por emissão/vencimento/status/CNPJ (até 100 por página).
- `GET /operacional/consulta/manifestos`: manifestos por período.
- `GET /cadastro/empresas`: cadastro de clientes.
- `GET /tracking/ocorrencias/*`: rastreio por documento.

**Estratégia proposta:** API para 138 e 147 (e para as fontes novas); para os demais, login uma vez e
chamadas HTTP diretas aos mesmos endereços que a tela usa (como o `brudam_scraper.py` já faz), sem abrir
navegador para exportar planilha. Cada relatório vira um plugin; a troca é feita um por um.
