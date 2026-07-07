# src/api.py
# FastAPI Web Application & Interface Dashboard

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from recommender import get_graph_recommendations, get_ml_recommendations

app = FastAPI(title="JOB NEXUS / VISION NEXUS", version="5.0")


@app.on_event("startup")
def startup_check():
    """Verify Neo4j connection on startup."""
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        from db_neo4j import get_driver
        driver = get_driver()
        with driver.session() as session:
            session.run("RETURN 1")
        logging.info("[Startup] Neo4j connection OK")
    except Exception as e:
        logging.error(f"[Startup] Neo4j connection FAILED: {e}")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def landing_page():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/ui/search", response_class=HTMLResponse)
def search_dashboard():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

def parse_and_normalize_skills(skills: str) -> list:
    from normalize import normalize_user_skill
    parsed = []
    for s in skills.split(","):
        s = s.strip()
        if s:
            ns = normalize_user_skill(s)
            if ns and ns not in parsed:
                parsed.append(ns)
    if not parsed:
        parsed = [s.strip() for s in skills.split(",") if s.strip()]
    return parsed

@app.get("/api/graph")
def get_graph_data(skills: str = Query(...), mode: str = Query("ml")):
    try:
        user_skill_list = parse_and_normalize_skills(skills)
        
        if mode == "ml":
            recommendations = get_ml_recommendations(user_skill_list, limit=6)
        else:
            recommendations = get_graph_recommendations(user_skill_list, limit=6)
            
        nodes = []
        edges = []
        
        nodes.append({"id": "user", "label": "You", "group": "user", "title": "Guest Profile"})
        seen_nodes = {"user"}
        
        for s in user_skill_list:
            node_id = f"skill_{s.lower()}"
            if node_id not in seen_nodes:
                nodes.append({"id": node_id, "label": s, "group": "user_skill"})
                seen_nodes.add(node_id)
            edges.append({"from": "user", "to": node_id, "label": "has"})
            
        for r in recommendations:
            job_node_id = f"job_{r['job_id']}"
            if job_node_id not in seen_nodes:
                nodes.append({"id": job_node_id, "label": f"{r['title']}\\n({r['company']})", "group": "job"})
                seen_nodes.add(job_node_id)
                
            for ms in r["matched"]:
                skill_node_id = f"skill_{ms.lower()}"
                if skill_node_id in seen_nodes:
                    edges.append({"from": skill_node_id, "to": job_node_id, "label": "matches"})
                    
            for mis in r["missing"]:
                missing_node_id = f"skill_{mis.lower()}"
                if missing_node_id not in seen_nodes:
                    nodes.append({"id": missing_node_id, "label": mis, "group": "missing_skill"})
                    seen_nodes.add(missing_node_id)
                edges.append({"from": missing_node_id, "to": job_node_id, "label": "requires", "dashes": True})
                
                for c in r["courses"]:
                    if mis in c["skills_covered"]:
                        course_node_id = f"course_{c['course_id']}"
                        if course_node_id not in seen_nodes:
                            nodes.append({"id": course_node_id, "label": c["course_name"], "group": "course"})
                            seen_nodes.add(course_node_id)
                        edges.append({"from": course_node_id, "to": missing_node_id, "label": "teaches"})
                        
        return JSONResponse(content={"nodes": nodes, "edges": edges})
    except Exception as e:
        import logging
        logging.error(f"[Graph] Error: {e}")
        return JSONResponse(
            content={"error": f"Database connection failed: {e}"},
            status_code=500
        )
 
@app.get("/api/skills/search")
def search_skills(q: str = Query("")):
    from normalize import CANONICAL_SKILLS, SKILL_ALIASES
    q = q.strip().lower()
    if not q:
        return JSONResponse({"skills": CANONICAL_SKILLS[:10]})
    results = set()
    for canonical in CANONICAL_SKILLS:
        if q in canonical.lower():
            results.add(canonical)
    for alias, canonical in SKILL_ALIASES.items():
        if q in alias.lower():
            results.add(canonical)
    sorted_results = sorted(results, key=lambda x: (x.lower().startswith(q), x))[:10]
    return JSONResponse({"skills": sorted_results})

@app.get("/api/skills/normalize")
def normalize_skill(q: str = Query("")):
    from normalize import normalize_user_skill
    q = q.strip()
    if not q:
        return JSONResponse({"original": q, "canonical": q, "normalized": False})
    canonical = normalize_user_skill(q)
    if not canonical:
        canonical = q.strip().title()
    is_normalized = canonical.lower() != q.lower()
    return JSONResponse({
        "original": q,
        "canonical": canonical,
        "normalized": is_normalized
    })

@app.get("/api/skills/all")
def get_all_skills():
    from normalize import CANONICAL_SKILLS
    return JSONResponse({"skills": CANONICAL_SKILLS})

@app.get("/api/filters")
def get_filters():
    try:
        from db_neo4j import get_driver
        driver = get_driver()
        filters = {"categories": [], "locations": [], "companies": []}
        with driver.session() as session:
            result = session.run("MATCH (j:Job) RETURN collect(DISTINCT j.category) AS categories")
            filters["categories"] = sorted([c for c in result.single()["categories"] if c])
            result = session.run("MATCH (j:Job) RETURN collect(DISTINCT j.location) AS locations")
            filters["locations"] = sorted([l for l in result.single()["locations"] if l])
            result = session.run("MATCH (j:Job) RETURN collect(DISTINCT j.company) AS companies")
            filters["companies"] = sorted([c for c in result.single()["companies"] if c])
        return JSONResponse(content=filters)
    except Exception as e:
        import logging
        logging.error(f"[Filters] Error: {e}")
        return JSONResponse(
            content={"error": f"Database connection failed: {e}"},
            status_code=500
        )

def parse_proficiencies(prof_str: str) -> dict:
    """Parses 'skill:level,skill:level' into {skill_lower: level}."""
    result = {}
    if not prof_str:
        return result
    for part in prof_str.split(","):
        part = part.strip()
        if ":" in part:
            skill, level = part.rsplit(":", 1)
            try:
                result[skill.strip().lower()] = int(level.strip())
            except ValueError:
                pass
    return result

@app.get("/api/recommend")
def get_recommendations_json(
    skills: str = Query(...),
    proficiencies: str = Query(""),
    mode: str = Query("ml"),
    category: str = Query(""),
    location: str = Query(""),
    company: str = Query(""),
    sort_by: str = Query("score_desc")
):
    try:
        user_skill_list = parse_and_normalize_skills(skills)
        prof_dict = parse_proficiencies(proficiencies)
        if mode == "ml":
            recs = get_ml_recommendations(user_skill_list, limit=50, proficiencies=prof_dict)
        else:
            recs = get_graph_recommendations(user_skill_list, limit=50, proficiencies=prof_dict)

        # Apply filters
        if category:
            recs = [r for r in recs if r.get("category", "").lower() == category.lower()]
        if location:
            loc_lower = location.lower()
            recs = [r for r in recs if loc_lower in r.get("location", "").lower()]
        if company:
            comp_lower = company.lower()
            recs = [r for r in recs if comp_lower in r.get("company", "").lower()]

        # Apply sort
        if sort_by == "score_asc":
            recs.sort(key=lambda x: x["score"])
        elif sort_by == "title_asc":
            recs.sort(key=lambda x: x.get("title", "").lower())
        elif sort_by == "title_desc":
            recs.sort(key=lambda x: x.get("title", "").lower(), reverse=True)
        else:
            recs.sort(key=lambda x: x["score"], reverse=True)

        return JSONResponse(content={"recommendations": recs[:6]})
    except Exception as e:
        import logging
        logging.error(f"[Recommend] Error: {e}")
        return JSONResponse(
            content={"error": f"Database connection failed: {e}. Check that Neo4j AuraDB credentials are set in Render environment variables."},
            status_code=500
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
