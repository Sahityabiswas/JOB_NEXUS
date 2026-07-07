# src/ingest_spark.py
# Spark Master-Worker Data Ingestion Pipeline (Multi-API & Dynamic Coursera)

import os
import sys
import csv
import json
import requests
from pyspark.sql import SparkSession
from db_neo4j import clear_db, setup_constraints

# Add src to python path for worker processes if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- API Fetching Functions (Run by Spark Driver) ---

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
        print(f"[Driver] Fetched {len(jobs)} jobs from Remotive API.")
        return jobs
    except Exception as e:
        print(f"[Driver] Error fetching Remotive jobs: {e}")
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
        print(f"[Driver] Fetched {len(jobs)} jobs from The Muse API.")
        return jobs
    except Exception as e:
        print(f"[Driver] Error fetching The Muse jobs: {e}")
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
        print(f"[Driver] Fetched {len(jobs)} jobs from Jobicy API.")
        return jobs
    except Exception as e:
        print(f"[Driver] Error fetching Jobicy jobs: {e}")
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
        print(f"[Driver] Fetched {len(courses)} courses from Coursera Catalog API.")
        return courses
    except Exception as e:
        print(f"[Driver] Error fetching Coursera courses: {e}")
        return []

def load_csv_courses() -> list:
    # Try multiple potential paths to courses.csv
    paths = ["data/courses.csv", "courses.csv", "../data/courses.csv"]
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
                print(f"[Driver] Loaded {len(courses)} courses from local backup CSV: {path}")
                return courses
            except Exception as e:
                print(f"[Driver] Error reading {path}: {e}")
    return []

# --- Spark Processing Functions (Run by Spark Workers) ---

def parse_job_record(job_dict: dict) -> dict:
    """Runs on Spark Workers. Cleans job description and extracts skills."""
    # Import inside task function to avoid pickling issues
    from normalize import clean_skill_list, extract_skills, infer_category, is_low_quality_job
    
    # Extract skills from both text description and API source tags
    text_blob = f"{job_dict['title']} {job_dict['description']}"
    raw_skills = job_dict['skills']
    
    extracted = extract_skills(text_blob)
    cleaned_source = clean_skill_list(raw_skills)
    
    final_skills = sorted(set(extracted) | set(cleaned_source))
    category = infer_category(job_dict['title'], final_skills)
    
    is_valid = not is_low_quality_job(job_dict['job_id'], job_dict['title'], final_skills)
    
    return {
        "job_id": job_dict["job_id"],
        "title": job_dict["title"],
        "company": job_dict["company"],
        "location": job_dict["location"],
        "category": category,
        "skills": final_skills,
        "is_valid": is_valid
    }

def parse_course_record(course_dict: dict) -> dict:
    """Runs on Spark Workers. Extracts skills taught by the course."""
    from normalize import extract_skills
    
    text_blob = f"{course_dict['name']} {course_dict['description']}"
    extracted_skills = extract_skills(text_blob)
    
    # Handle CSV course mapping fallback if description contains semicolon-separated values
    if not extracted_skills and course_dict["source"] == "csv":
        # Split skills
        extracted_skills = [s.strip() for s in course_dict["description"].split() if s.strip()]
        
    return {
        "course_id": course_dict["course_id"],
        "name": course_dict["name"],
        "skills": extracted_skills
    }

# --- Database Writers (Run in parallel on Workers using foreachPartition) ---

def save_jobs_partition_to_neo4j(partition_iter):
    """Worker database write task. Direct streaming connection to Neo4j database."""
    from neo4j import GraphDatabase
    
    import json
    def load_cfg():
        paths = ["config.json", "../config.json", "src/config.json"]
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, "r") as f:
                        return json.load(f)
                except:
                    pass
        return {}
    cfg = load_cfg()
    uri = os.getenv("NEO4J_URI", cfg.get("neo4j_uri", "bolt://localhost:7687"))
    user = os.getenv("NEO4J_USER", cfg.get("neo4j_user", "neo4j"))
    pwd = os.getenv("NEO4J_PASS", cfg.get("neo4j_pass", "YOUR_PASSWORD_HERE"))
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    with driver.session() as session:
        for job in partition_iter:
            if not job.get("is_valid", False):
                continue
            
            # 1. Merge Job node
            session.run("""
                MERGE (j:Job {id: $job_id})
                SET j.title = $title,
                    j.company = $company,
                    j.location = $location,
                    j.category = $category
            """, job_id=job["job_id"], title=job["title"], company=job["company"],
                 location=job["location"], category=job["category"])
            
            # 2. Merge Skills and CREATE REQUIRES edges
            for skill_name in job["skills"]:
                session.run("""
                    MERGE (s:Skill {name: $skill})
                    WITH s
                    MATCH (j:Job {id: $job_id})
                    MERGE (j)-[:REQUIRES]->(s)
                """, skill=skill_name, job_id=job["job_id"])
    driver.close()

def save_courses_partition_to_neo4j(partition_iter):
    """Worker database write task. Direct streaming connection to Neo4j database."""
    from neo4j import GraphDatabase
    
    import json
    def load_cfg():
        paths = ["config.json", "../config.json", "src/config.json"]
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, "r") as f:
                        return json.load(f)
                except:
                    pass
        return {}
    cfg = load_cfg()
    uri = os.getenv("NEO4J_URI", cfg.get("neo4j_uri", "bolt://localhost:7687"))
    user = os.getenv("NEO4J_USER", cfg.get("neo4j_user", "neo4j"))
    pwd = os.getenv("NEO4J_PASS", cfg.get("neo4j_pass", "YOUR_PASSWORD_HERE"))
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    with driver.session() as session:
        for course in partition_iter:
            if not course.get("skills"):
                continue
            
            # 1. Merge Course node
            session.run("""
                MERGE (c:Course {id: $course_id})
                SET c.name = $name
            """, course_id=course["course_id"], name=course["name"])
            
            # 2. Merge Skills and CREATE TEACHES edges
            for skill_name in course["skills"]:
                session.run("""
                    MERGE (s:Skill {name: $skill})
                    WITH s
                    MATCH (c:Course {id: $course_id})
                    MERGE (c)-[:TEACHES]->(s)
                """, skill=skill_name, course_id=course["course_id"])
    driver.close()

# --- Main Distributed Ingestion Runner ---

def run_ingestion():
    # 1. Clear database and create unique graph constraints
    print("[Driver] Resetting database...")
    try:
        clear_db()
    except Exception as e:
        print(f"[Driver] Warning wiping DB (database might be clean or unreachable): {e}")
    setup_constraints()
    
    # 2. Fetch API data from dynamic sources
    print("[Driver] Fetching job posting datasets...")
    jobs = []
    jobs += fetch_remotive_jobs()
    jobs += fetch_themuse_jobs()
    jobs += fetch_jobicy_jobs()
    
    print("[Driver] Fetching online course pathways...")
    courses = []
    courses += fetch_coursera_courses()
    courses += load_csv_courses() # Load local CSV backup as fallback/enrichment
    
    if not jobs:
        print("[Driver] ERROR: No jobs fetched. Ingestion aborted.")
        return
        
    # 3. Spin up Spark session (distributed driver-executor threads)
    print("[Driver] Initializing Spark Master-Worker threadpool...")
    spark = SparkSession.builder \
        .appName("RecommendationSystemIngest") \
        .master(os.getenv("SPARK_MASTER", "spark://localhost:7077")) \
        .config("spark.driver.bindAddress", os.getenv("SPARK_BIND_ADDRESS", "localhost")) \
        .getOrCreate()
        
    spark.sparkContext.setLogLevel("WARN")
    
    try:
        # 4. Distribute Job Processing
        print("[Driver] Parallelizing job listings on Spark workers...")
        jobs_rdd = spark.sparkContext.parallelize(jobs)
        clean_jobs_rdd = jobs_rdd.map(parse_job_record)
        
        print("[Driver] Streaming clean jobs to Neo4j in parallel partitions...")
        clean_jobs_rdd.foreachPartition(save_jobs_partition_to_neo4j)
        
        # 5. Distribute Course Processing
        if courses:
            print("[Driver] Parallelizing courses on Spark workers...")
            courses_rdd = spark.sparkContext.parallelize(courses)
            clean_courses_rdd = courses_rdd.map(parse_course_record)
            
            print("[Driver] Streaming course pathways to Neo4j in parallel partitions...")
            clean_courses_rdd.foreachPartition(save_courses_partition_to_neo4j)
            
        print("[Driver] Distributed Ingestion complete!")
        
    finally:
        spark.stop()

if __name__ == "__main__":
    run_ingestion()
