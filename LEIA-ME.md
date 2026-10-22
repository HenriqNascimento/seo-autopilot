# Piloto SEO multi-site

Sistema 100 % automático que, para cada site, pesquisa o que o público procura, escreve (Gemini 3.8 Flash), verifica, publica, mede no Search Console, testa e aprende.

Sites atuais: `sitios/innovadental` (3 artigos/semana) e `sitios/cresco` (4 artigos/semana).

## Como funciona
Todos os dias às 08:00 o GitHub Actions corre `diario`:
- **Cada site publica o que lhe toca hoje**, conforme `articulos_semana` no seu `sitio.json`: até 5 por semana de segunda a sexta, mais de 5 em todos os dias.
- **Cada artigo**: tema de maior prioridade → briefing da SERP (via grounding do Gemini) → rascunho → editor com verificação de factos e anti-IA (até 3 voltas) → controlo de qualidade automático → publicação.
- **Domingo**: em cada site, medição no GSC, teste de títulos, atualização de 1 artigo e aprendizagens. Depois, avaliação da experiência de formato, que é comum a todos os sites.

## Fontes de dados (todas autorizadas)
- **Search Console API**: consultas e páginas reais, e a Inspeção de URL para saber quando o Google voltou a rastrear uma página.
- **Gemini com grounding de Google Search**: API oficial e paga, usada para pesquisar temas e verificar factos.
- O piloto **não consulta nem recolhe** a Pesquisa Google diretamente.

## Testes, desenhados para não enganar
**Formato (artigos novos, partilhado entre os sites para ter mais dados)**
- Aleatorização estratificada por site + cluster, com A e B intercalados no mesmo período.
- Mesma janela de idade para todos: dias 14 a 70 após a publicação.
- Ajuste pela procura estimada do tema; teste de permutação estratificado.
- Só avalia em 3 pontos fixos (12, 20 e 30 artigos por braço), com o limiar de Pocock (p < 0,022 em cada ponto).
- Calibração por simulação: **5 % de falsos positivos**. Potência: um efeito de +60 % é detetado em 78 % dos casos, um de +30 % em 28 %. Se não houver conclusão, nenhuma regra é adotada.

**Títulos e meta descriptions (artigos existentes)**
- Pares emparejados (teste/controlo).
- A janela "depois" só começa quando o Google voltou a rastrear a página. Se não a rastrear em 21 dias, o título é revertido.
- Mede cliques observados ÷ cliques esperados para a posição, sobre o **mesmo conjunto de consultas** antes e depois, com a curva de CTR do próprio site.
- Diferença em diferenças face ao controlo. Pares cuja posição muda mais de 1,5 ficam de fora. O que não melhora é revertido.
- Limite: o Google pode mostrar outro título que não o `<title>`, e a API não o indica.

**FAQ**: só aparece no artigo quando responde a perguntas reais. Não há JSON-LD de FAQ, porque o Google limita esses resultados enriquecidos a sites de saúde e governamentais com autoridade.

## Acrescentar um site
1. Copie `sitios/cresco` para `sitios/<novo>`.
2. Edite `sitio.json`: URL, propriedade do GSC, publicador, `articulos_semana`, `presupuesto_usd_mes`, público, objetivo, autor, CTA e sementes.
3. Escreva `conocimiento/empresa.md` (factos reais) e `conocimiento/voz.md`. O estilo anti-IA comum está em `comun/estilo.md`.
4. Opcional: fotos em `imagenes/` + `descripciones.json`.
5. Acrescente o secret do token ao workflow e corra `configurar` com `--sitio <novo>`.

## Instalação (uma vez)
1. **Gemini (custo 0 € com o Google AI Pro)**:
   - Em developers.google.com/program ative os benefícios do Google AI Pro (10 USD/mês de crédito Google Cloud) e associe uma conta de faturação.
   - Em aistudio.google.com crie uma API key **no projeto ligado a essa faturação**. Pagar com crédito conta como uso pago: os seus dados não treinam modelos e há 5.000 pesquisas Google grátis por mês.
   - No Google Cloud → Faturação → Orçamentos, crie um alerta de 10 USD. O piloto para ao chegar a 9 USD/mês no total (`PRESUPUESTO_USD_MES`) e ao limite de cada site.
2. **HubSpot** (um por site): Definições → Integrações → *Private apps* → scopes `content` e `files`.
3. **Search Console**: crie uma conta de serviço no Google Cloud, ative a *Search Console API* e adicione o e-mail da conta de serviço como utilizador *Restrito* em **cada** propriedade.
4. **GitHub** (repositório privado) → *Settings → Secrets and variables → Actions*: `GEMINI_API_KEY`, `GSC_CREDENCIALES` (JSON inteiro), `HUBSPOT_TOKEN_INNOVADENTAL`, `HUBSPOT_TOKEN_CRESCO`.
5. *Actions → Piloto SEO → Run workflow*: `configurar` com sitio `innovadental`, depois `publicar`.

## Controlo
- **Pausar tudo**: variável `PAUSADO` = `1`.
- **Ritmo e orçamento de cada site**: `sitio.json`.
- **Alertas**: se algum site falhar (qualidade insuficiente 2× seguidas, chave em falta…), a execução falha e o GitHub envia e-mail. Os outros sites continuam.
- **Simular**: `SIMULAR=1 python -m piloto publicar --sitio cresco` (HTML em `sitios/cresco/salida/`).
- **Estado**: `python -m piloto estado`.
