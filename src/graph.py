"""Shared read-only Neo4j access for agent tools."""
import os

from dotenv import load_dotenv
from neo4j import READ_ACCESS, GraphDatabase

MAX_ROWS = 50

load_dotenv()

driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))


def read_graph(query: str, **params) -> list[dict]:
    with driver.session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)][:MAX_ROWS])
