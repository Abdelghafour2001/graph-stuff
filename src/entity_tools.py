"""Tools of the entity specialist: canonical assets resolved from market-intel source records."""
import json

from anthropic import beta_tool

from graph import read_graph


@beta_tool
def resolve_entity(name: str) -> str:
    """Find the canonical asset(s) behind a company, plant, mine or site name as written in data sources
    (e.g. "ocp_la_youne", "Jorf Fertilizer Company", "Maaden JV"), with merge status and confidence.

    Args:
        name: Name or fragment, case-insensitive.
    """
    rows = read_graph(
        "MATCH (e:SourceEntity)-[s:SAME_AS]->(a:Asset) WHERE toLower(e.name) CONTAINS toLower($snake) OR toLower(a.name) CONTAINS toLower($q) "
        "OPTIONAL MATCH (a)-[:LOCATED_AT]->(site:Concept) "
        "RETURN DISTINCT a.id AS asset_id, a.name AS asset, a.kind AS kind, site.id AS site, a.confidence AS confidence, s.status AS status, "
        "[(x:SourceEntity)-[:SAME_AS]->(a) | x.name] AS source_names",
        q=name, snake=name.strip().replace(" ", "_"),  # source names are snake_case, asset names are readable
    )
    return json.dumps(rows, ensure_ascii=False) if rows else f"No asset matches '{name}'."


@beta_tool
def ocp_assets(site_id: str) -> str:
    """OCP-controlled assets at one site (khouribga, benguerir, youssoufia, boucraa, jorf_lasfar, safi) or 'all',
    with the products and number of market-intel metrics recorded for their source records.

    Args:
        site_id: Site concept id or "all".
    """
    rows = read_graph(
        "MATCH (a:Asset)-[:PART_OF]->(:Concept {id: 'ocp_group'}) OPTIONAL MATCH (a)-[:LOCATED_AT]->(site:Concept) "
        "WITH a, site WHERE $site = 'all' OR site.id = $site "
        "MATCH (e:SourceEntity)-[:SAME_AS]->(a) "
        "RETURN a.id AS asset_id, a.name AS asset, a.kind AS kind, site.id AS site, a.confidence AS confidence, "
        "collect(DISTINCT e.products) AS products, sum(e.metrics) AS metrics ORDER BY metrics DESC",
        site=site_id,
    )
    return json.dumps(rows, ensure_ascii=False) if rows else f"No OCP asset at '{site_id}'."
