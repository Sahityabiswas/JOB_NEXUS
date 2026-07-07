# src/ingest_simple.py
# Lightweight Ingestor (No Spark Required - Fast Fallback)

import os
import sys
import csv
import requests
from db_neo4j import clear_db, setup_constraints, get_driver
from normalize import clean_skill_list, extract_skills, infer_category, is_low_quality_job

# --- Fetch API data ---

def fetch_remotive_jobs() -> list:
    url = "https://remotive.com/api/remote-jobs"
    params = {"limit": 30}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        jobs = []
        for j in data.get("jobs", []):
            jobs.append({
                "job_id": f"remotive_{j.get('id')}",
                "title": j.get("title", ""),
                "company": j.get("company_name", "Unknown"),
                "location": "Remote",
                "description": j.get("description", ""),
                "skills": j.get("tags", []),
                "source": "remotive"
            })
        print(f"[Ingest] Fetched {len(jobs)} jobs from Remotive.")
        return jobs
    except Exception as e:
        print(f"[Ingest] Error fetching Remotive jobs: {e}")
        return []

def fetch_themuse_jobs() -> list:
    url = "https://www.themuse.com/api/public/jobs"
    params = {"page": 1}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        jobs = []
        for j in data.get("results", []):
            locs = [l.get("name") for l in j.get("locations", []) if l.get("name")]
            location = locs[0] if locs else "Remote"
            jobs.append({
                "job_id": f"themuse_{j.get('id')}",
                "title": j.get("name", ""),
                "company": j.get("company", {}).get("name", "Unknown"),
                "location": location,
                "description": j.get("contents", ""),
                "skills": [cat.get("name") for cat in j.get("categories", [])],
                "source": "themuse"
            })
        print(f"[Ingest] Fetched {len(jobs)} jobs from The Muse.")
        return jobs
    except Exception as e:
        print(f"[Ingest] Error fetching The Muse jobs: {e}")
        return []

def fetch_jobicy_jobs() -> list:
    url = "https://jobicy.com/api/v2/remote-jobs"
    params = {"count": 30}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        jobs = []
        for j in data.get("jobs", []):
            jobs.append({
                "job_id": f"jobicy_{j.get('id')}",
                "title": j.get("jobTitle", ""),
                "company": j.get("companyName", "Unknown"),
                "location": j.get("jobGeo", "Remote"),
                "description": j.get("jobDescription", ""),
                "skills": [j.get("jobCategory", "")],
                "source": "jobicy"
            })
        print(f"[Ingest] Fetched {len(jobs)} jobs from Jobicy.")
        return jobs
    except Exception as e:
        print(f"[Ingest] Error fetching Jobicy jobs: {e}")
        return []

def fetch_coursera_courses() -> list:
    url = "https://api.coursera.org/api/courses.v1"
    params = {"limit": 100, "fields": "description"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        courses = []
        for c in data.get("elements", []):
            courses.append({
                "course_id": c.get("id"),
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "source": "coursera"
            })
        print(f"[Ingest] Fetched {len(courses)} courses from Coursera.")
        return courses
    except Exception as e:
        print(f"[Ingest] Error fetching Coursera courses: {e}")
        return []

def load_csv_courses() -> list:
    paths = ["data/courses.csv", "courses.csv"]
    for path in paths:
        if os.path.exists(path):
            courses = []
            try:
                with open(path, mode='r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        courses.append({
                            "course_id": row.get("course_id", "").strip(),
                            "name": row.get("name", "").strip(),
                            "description": row.get("skills", "").replace(";", " "),
                            "source": "csv"
                        })
                print(f"[Ingest] Loaded {len(courses)} courses from local CSV.")
                return courses
            except Exception as e:
                print(f"[Ingest] Error reading {path}: {e}")
    return []

# --- Write to Neo4j ---

def save_jobs(jobs: list):
    driver = get_driver()
    with driver.session() as session:
        for job in jobs:
            text_blob = f"{job['title']} {job['description']}"
            extracted = extract_skills(text_blob)
            cleaned = clean_skill_list(job['skills'])
            final_skills = sorted(set(extracted) | set(cleaned))
            
            if is_low_quality_job(job['job_id'], job['title'], final_skills):
                continue
                
            category = infer_category(job['title'], final_skills)
            
            # Merge Job
            session.run("""
                MERGE (j:Job {id: $job_id})
                SET j.title = $title,
                    j.company = $company,
                    j.location = $location,
                    j.category = $category
            """, job_id=job["job_id"], title=job["title"], company=job["company"],
                 location=job["location"], category=category)
            
            # Merge Skills and REQUIRES
            for s in final_skills:
                session.run("""
                    MERGE (sk:Skill {name: $skill})
                    WITH sk
                    MATCH (j:Job {id: $job_id})
                    MERGE (j)-[:REQUIRES]->(sk)
                """, skill=s, job_id=job["job_id"])
    print("[Ingest] Successfully loaded job nodes and edges.")

def save_courses(courses: list):
    driver = get_driver()
    with driver.session() as session:
        for course in courses:
            text_blob = f"{course['name']} {course['description']}"
            extracted = extract_skills(text_blob)
            
            if not extracted and course["source"] == "csv":
                extracted = [s.strip() for s in course["description"].split() if s.strip()]
                
            if not extracted:
                continue
                
            # Merge Course
            session.run("""
                MERGE (c:Course {id: $course_id})
                SET c.name = $name
            """, course_id=course["course_id"], name=course["name"])
            
            # Merge Skills and TEACHES
            for s in extracted:
                session.run("""
                    MERGE (sk:Skill {name: $skill})
                    WITH sk
                    MATCH (c:Course {id: $course_id})
                    MERGE (c)-[:TEACHES]->(sk)
                """, skill=s, course_id=course["course_id"])
    print("[Ingest] Successfully loaded course nodes and edges.")

# --- Main Runner ---

def main():
    print("[Ingest] Initializing database...")
    try:
        clear_db()
    except Exception as e:
        print(f"[Ingest] DB wipe warning: {e}")
    setup_constraints()
    
    print("[Ingest] Loading data...")
    jobs = []
    jobs += fetch_remotive_jobs()
    jobs += fetch_themuse_jobs()
    jobs += fetch_jobicy_jobs()
    
    courses = []
    courses += fetch_coursera_courses()
    courses += load_csv_courses()
    
    if jobs:
        print("[Ingest] Writing jobs...")
        save_jobs(jobs)
    if courses:
        print("[Ingest] Writing courses...")
        save_courses(courses)
    print("[Ingest] Complete!")

if __name__ == "__main__":
    main()
