# src/recommender.py
# Recommendation Math & Graph Pathway Algorithms

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db_neo4j import get_driver

def load_jobs_and_skills() -> dict:
    """Fetches all jobs and their required skills from Neo4j."""
    driver = get_driver()
    query = """
        MATCH (j:Job)-[:REQUIRES]->(s:Skill)
        RETURN j.id AS job_id, j.title AS title, j.company AS company,
               j.location AS location, j.category AS category, collect(s.name) AS skills
    """
    jobs = {}
    with driver.session() as session:
        result = session.run(query)
        for r in result:
            jobs[r["job_id"]] = {
                "title": r["title"],
                "company": r["company"],
                "location": r["location"],
                "category": r["category"],
                "skills": r["skills"]
            }
    return jobs

def load_courses_and_skills() -> dict:
    """Fetches all courses and their taught skills from Neo4j."""
    driver = get_driver()
    query = """
        MATCH (c:Course)-[:TEACHES]->(s:Skill)
        RETURN c.id AS course_id, c.name AS name, collect(s.name) AS skills
    """
    courses = {}
    with driver.session() as session:
        result = session.run(query)
        for r in result:
            courses[r["course_id"]] = {
                "name": r["name"],
                "skills": r["skills"]
            }
    return courses

def get_graph_recommendations(user_skills: list, limit: int = 6) -> list:
    """
    Ranks jobs by simple set-based skill overlap percentage.
    Returns: list of job dicts including match scores, missing skills, and course pathways.
    """
    user_skill_set = set([s.lower() for s in user_skills])
    jobs = load_jobs_and_skills()
    courses = load_courses_and_skills()
    
    scored = []
    for jid, jdata in jobs.items():
        job_skills = jdata["skills"]
        job_skills_lower = [s.lower() for s in job_skills]
        job_skill_set = set(job_skills_lower)
        
        # Calculate overlap
        overlap = user_skill_set & job_skill_set
        score = len(overlap) / len(job_skill_set) if job_skill_set else 0
        
        # Determine missing skills
        missing_lower = job_skill_set - user_skill_set
        
        # Map back to original casing
        missing_skills = [s for s in job_skills if s.lower() in missing_lower]
        matched_skills = [s for s in job_skills if s.lower() in overlap]
        
        # Find recommended courses that teach missing skills
        recommended_courses = []
        for cid, cdata in courses.items():
            course_skills_lower = set([s.lower() for s in cdata["skills"]])
            covered_skills_lower = missing_lower & course_skills_lower
            if covered_skills_lower:
                covered_skills = [s for s in cdata["skills"] if s.lower() in covered_skills_lower]
                recommended_courses.append({
                    "course_id": cid,
                    "course_name": cdata["name"],
                    "skills_covered": covered_skills,
                    "coverage_score": len(covered_skills_lower) / len(missing_lower) if missing_lower else 1.0
                })
        
        # Sort courses by coverage
        recommended_courses.sort(key=lambda x: x["coverage_score"], reverse=True)
        
        scored.append({
            "job_id": jid,
            "title": jdata["title"],
            "company": jdata["company"],
            "location": jdata["location"],
            "category": jdata["category"],
            "score": round(score, 4),
            "matched": matched_skills,
            "missing": missing_skills,
            "courses": recommended_courses[:3],
            "method": "graph"
        })
        
    scored.sort(key=lambda x: x["score"], reverse=True)
    positive_scored = [s for s in scored if s["score"] > 0]
    if positive_scored:
        return positive_scored[:limit]
    return scored[:limit]

def get_ml_recommendations(user_skills: list, limit: int = 6) -> list:
    """
    Ranks jobs using TF-IDF vectorization and Cosine Similarity.
    Returns: list of job dicts including match scores, missing skills, and course pathways.
    """
    jobs = load_jobs_and_skills()
    if not jobs or not user_skills:
        return []
        
    job_ids = list(jobs.keys())
    
    # 1. Prepare documents: Space-separated skill strings
    job_docs = [" ".join(jobs[jid]["skills"]) for jid in job_ids]
    user_doc = " ".join(user_skills)
    all_docs = [user_doc] + job_docs
    
    # 2. Extract TF-IDF features
    vectorizer = TfidfVectorizer(token_pattern=r"[^\s]+")
    tfidf_matrix = vectorizer.fit_transform(all_docs)
    
    user_vector = tfidf_matrix[0]
    job_vectors = tfidf_matrix[1:]
    
    # 3. Compute cosine similarity between user skill profile and jobs
    scores = cosine_similarity(user_vector, job_vectors).flatten()
    
    # Pair scores with job IDs
    ranked = sorted(zip(job_ids, scores), key=lambda x: x[1], reverse=True)
    
    user_skill_set = set([s.lower() for s in user_skills])
    courses = load_courses_and_skills()
    
    results = []
    for jid, score in ranked:
        jdata = jobs[jid]
        job_skills = jdata["skills"]
        job_skills_lower = [s.lower() for s in job_skills]
        job_skill_set = set(job_skills_lower)
        
        # Overlaps
        overlap = user_skill_set & job_skill_set
        missing_lower = job_skill_set - user_skill_set
        
        missing_skills = [s for s in job_skills if s.lower() in missing_lower]
        matched_skills = [s for s in job_skills if s.lower() in overlap]
        
        # Determine courses
        recommended_courses = []
        for cid, cdata in courses.items():
            course_skills_lower = set([s.lower() for s in cdata["skills"]])
            covered_skills_lower = missing_lower & course_skills_lower
            if covered_skills_lower:
                covered_skills = [s for s in cdata["skills"] if s.lower() in covered_skills_lower]
                recommended_courses.append({
                    "course_id": cid,
                    "course_name": cdata["name"],
                    "skills_covered": covered_skills,
                    "coverage_score": len(covered_skills_lower) / len(missing_lower) if missing_lower else 1.0
                })
        
        recommended_courses.sort(key=lambda x: x["coverage_score"], reverse=True)
        
        results.append({
            "job_id": jid,
            "title": jdata["title"],
            "company": jdata["company"],
            "location": jdata["location"],
            "category": jdata["category"],
            "score": round(float(score), 4),
            "matched": matched_skills,
            "missing": missing_skills,
            "courses": recommended_courses[:3],
            "method": "ml"
        })
        
    positive_results = [r for r in results if r["score"] > 0]
    if positive_results:
        return positive_results[:limit]
    return results[:limit]
