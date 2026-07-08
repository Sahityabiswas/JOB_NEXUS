# src/db_neo4j.py
# Neo4j Database Connection Pool and Constraints Setup

import os
import json
from neo4j import GraphDatabase

# Load dynamic configuration from config.json if available
def load_config():
    paths = ["config.json", "../config.json", "src/config.json"]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}

config = load_config()
NEO4J_URI = os.getenv("NEO4J_URI", config.get("neo4j_uri", "bolt://localhost:7687"))
NEO4J_USER = os.getenv("NEO4J_USER", config.get("neo4j_user", "neo4j"))
NEO4J_PASS = os.getenv("NEO4J_PASS", config.get("neo4j_pass", "YOUR_PASSWORD_HERE"))

_driver = None

def get_driver():
    """Returns the Neo4j database driver connection pool singleton."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASS)
        )
    return _driver

def close_driver():
    """Closes the Neo4j driver connection pool."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None

def setup_constraints():
    """Sets up unique constraints on Neo4j nodes for optimal indexing performance."""
    driver = get_driver()
    queries = [
        "CREATE CONSTRAINT job_id_unique IF NOT EXISTS FOR (j:Job) REQUIRE j.id IS UNIQUE",
        "CREATE CONSTRAINT skill_name_unique IF NOT EXISTS FOR (s:Skill) REQUIRE s.name IS UNIQUE",
        "CREATE CONSTRAINT course_id_unique IF NOT EXISTS FOR (c:Course) REQUIRE c.id IS UNIQUE"
    ]
    with driver.session() as session:
        for q in queries:
            try:
                session.run(q)
            except Exception as e:
                print(f"[Neo4j Setup] Warning setting up constraint: {e}")
    print("[Neo4j Setup] Unique constraints initialized successfully.")

def clear_db():
    """Clears all nodes and relationships in the Neo4j database (for resetting data)."""
    driver = get_driver()
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("[Neo4j Setup] Database wiped clean successfully.")
