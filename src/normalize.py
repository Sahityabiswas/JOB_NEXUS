# src/normalize.py
# Skill Normalization & Extraction Utilities

import re
import difflib
from typing import Any, Dict, List, Optional

# Canonical skill mapping
SKILL_ALIASES = {
    "python": "Python",
    "sql": "SQL",
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "excel": "Excel",
    "java": "Java",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "c++": "C++",
    "c#": "C#",
    "c sharp": "C#",
    "r": "R",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "ai/ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "nlp": "NLP",
    "llm": "LLM",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "scikit-learn": "Scikit-learn",
    "sklearn": "Scikit-learn",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "hadoop": "Hadoop",
    "spark": "Spark",
    "kafka": "Kafka",
    "hive": "Hive",
    "hbase": "HBase",
    "neo4j": "Neo4j",
    "mongodb": "MongoDB",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "tableau": "Tableau",
    "power bi": "Power BI",
    "rest api": "REST API",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "git": "Git",
    "github": "Git",
    "linux": "Linux",
    "bash": "Bash",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "react": "React",
    "react js": "React",
    "react.js": "React",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "php": "PHP",
    "laravel": "Laravel",
    "ruby on rails": "Ruby on Rails",
    "rails": "Ruby on Rails",
    "golang": "Go",
    "go": "Go",
    "scala": "Scala",
}

CANONICAL_SKILLS = sorted(set(SKILL_ALIASES.values()))

NOISE_TERMS = {
    "startup", "video", "research", "diversity", "themes", "responsive",
    "documentation", "advertising", "insurance", "marketplace", "social media",
    "frontend", "backend", "fullstack", "full-stack", "remote", "office",
    "assistant", "online", "senior", "junior", "lead", "manager", "team player",
    "communication", "motivated", "detail oriented", "detail-oriented"
}

CATEGORY_HINTS = {
    "Data": {"SQL", "Excel", "Tableau", "Power BI", "Pandas", "NumPy", "PostgreSQL", "MySQL"},
    "Software": {"Java", "Python", "JavaScript", "TypeScript", "React", "Node.js", "Flask", "Django"},
    "ML/AI": {"Machine Learning", "Deep Learning", "NLP", "LLM", "TensorFlow", "PyTorch", "Scikit-learn"},
    "Big Data": {"Hadoop", "Spark", "Kafka", "Hive", "HBase"},
    "DevOps/Cloud": {"Docker", "Kubernetes", "AWS", "Azure", "GCP", "Linux", "Bash"},
}

def normalize_skill(skill: str) -> str:
    """Standardizes alternate skill aliases directly."""
    skill = skill.strip().lower()
    mapping = {
        "python programming": "python",
        "py": "python",
        "python3": "python",
        "sql server": "sql",
        "mysql": "sql",
        "postgresql": "sql",
        "ms excel": "excel",
        "microsoft excel": "excel",
        "powerbi": "power bi",
        "nodejs": "node.js",
        "js": "javascript"
    }
    return mapping.get(skill, skill)

def canonicalize_skill(skill: str) -> Optional[str]:
    """Convert skill/alias to one canonical form, or None if invalid/noise."""
    if not skill:
        return None
    s = skill.strip().lower()
    if not s or s in NOISE_TERMS:
        return None
    return SKILL_ALIASES.get(s)

def extract_skills(text: str) -> List[str]:
    """Extract canonical skills from free text using boundary-safe regex pattern matching."""
    if not text:
        return []
    text = text.lower()
    found = set()
    for alias, canonical in SKILL_ALIASES.items():
        # Ensure we don't match substrings inside other words (e.g. 'go' in 'good')
        # handles special characters like C++, C#
        pattern = r'(?<!\w)' + re.escape(alias.lower()) + r'(?!\w)'
        if re.search(pattern, text):
            found.add(canonical)
    return sorted(found)

def clean_skill_list(skills: List[Any]) -> List[str]:
    """Cleans an array of raw input skills or split strings."""
    cleaned = set()
    for skill in skills or []:
        if not skill:
            continue
        if isinstance(skill, str) and any(sep in skill for sep in [",", "/", "|"]):
            parts = re.split(r"[,|/]+", skill)
        else:
            parts = [skill]
        for part in parts:
            if not isinstance(part, str):
                continue
            canon = canonicalize_skill(part)
            if canon:
                cleaned.add(canon)
    return sorted(cleaned)

def infer_category(title: str, skills: List[str]) -> str:
    """Infer simple job category from title + skill set matches."""
    title_lower = (title or "").lower()
    skill_set = set(skills)

    if any(k in title_lower for k in ["analyst", "data", "bi", "business intelligence"]):
        return "Data"
    if any(k in title_lower for k in ["machine learning", "ml", "ai", "nlp"]):
        return "ML/AI"
    if any(k in title_lower for k in ["devops", "cloud", "platform", "site reliability"]):
        return "DevOps/Cloud"
    if any(k in title_lower for k in ["spark", "hadoop", "kafka", "etl", "data engineer"]):
        return "Big Data"
    if any(k in title_lower for k in ["developer", "engineer", "backend", "frontend", "full stack", "full-stack"]):
        return "Software"

    best_category = "General"
    best_score = 0
    for category, hints in CATEGORY_HINTS.items():
        score = len(skill_set & hints)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category

def is_low_quality_job(job_id: str, title: str, skills: List[str]) -> bool:
    """Filters low value records."""
    if not job_id.strip():
        return True
    if not title.strip():
        return True
    if len(skills) < 1:
        return True
    return False

def normalize_user_skill(skill: str) -> Optional[str]:
    """
    Standardizes a user-inputted skill, resolving spelling mistakes and aliases.
    Uses difflib for fuzzy matching against canonical skills and known aliases.
    """
    if not skill:
        return None
        
    s = skill.strip().lower()
    if not s or s in NOISE_TERMS:
        return None
        
    # 1. Direct check in aliases
    if s in SKILL_ALIASES:
        return SKILL_ALIASES[s]
        
    # 2. Fuzzy match against all known aliases and canonical forms
    all_targets = list(SKILL_ALIASES.keys()) + list(CANONICAL_SKILLS)
    matches = difflib.get_close_matches(s, all_targets, n=1, cutoff=0.6)
    if matches:
        matched_target = matches[0].lower()
        if matched_target in SKILL_ALIASES:
            return SKILL_ALIASES[matched_target]
        # Check canonical list directly
        for c in CANONICAL_SKILLS:
            if c.lower() == matched_target:
                return c
                
    # 3. Fuzzy match fallback against canonical skills directly
    matches_canon = difflib.get_close_matches(skill.strip(), CANONICAL_SKILLS, n=1, cutoff=0.5)
    if matches_canon:
        return matches_canon[0]
        
    return skill.strip().title()
