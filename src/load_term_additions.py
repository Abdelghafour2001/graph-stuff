"""Load human-reviewed vocabulary additions (knowledge/term_additions.yaml) into the graph."""
from pathlib import Path

import yaml

from graph import driver

ADDITIONS = Path(__file__).parent.parent / "knowledge" / "term_additions.yaml"


def main() -> None:
    terms = yaml.safe_load(ADDITIONS.read_text(encoding="utf-8"))["terms"]
    with driver.session() as s:
        missing = s.run("UNWIND $ids AS id OPTIONAL MATCH (c:Concept {id: id}) WITH id, c WHERE c IS NULL RETURN collect(id) AS ids",
                        ids=[t["concept"] for t in terms]).single()["ids"]
        assert not missing, f"term_additions.yaml points to unknown concepts: {missing}"
        s.run("UNWIND $terms AS t MATCH (c:Concept {id: t.concept}) MERGE (x:Term {text: t.text})-[:REFERS_TO]->(c) SET x.note = t.note, x.reviewed = true",
              terms=terms)
    print(f"loaded {len(terms)} reviewed terms")


if __name__ == "__main__":
    main()
