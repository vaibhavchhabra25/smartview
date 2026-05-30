"""
Skill normalisation and matching utilities.
match_skills()          — deterministic alias-based matching (fallback)
semantic_match_skills() — LLM-based semantic matching (primary)
"""

SKILL_ALIASES: dict[str, str] = {
    # JavaScript / TypeScript
    "js": "JavaScript", "javascript": "JavaScript",
    "ts": "TypeScript", "typescript": "TypeScript",
    "es6": "JavaScript", "es2015": "JavaScript",

    # Frontend frameworks
    "react": "React", "reactjs": "React", "react.js": "React",
    "vue": "Vue.js", "vuejs": "Vue.js", "vue.js": "Vue.js",
    "angular": "Angular", "angularjs": "Angular",
    "svelte": "Svelte",
    "next": "Next.js", "nextjs": "Next.js", "next.js": "Next.js",
    "nuxt": "Nuxt.js", "nuxtjs": "Nuxt.js",
    "redux": "Redux", "zustand": "Zustand", "mobx": "MobX",

    # CSS / styling
    "css": "CSS", "scss": "SCSS", "sass": "SASS",
    "tailwind": "Tailwind CSS", "tailwindcss": "Tailwind CSS",
    "bootstrap": "Bootstrap", "material-ui": "Material UI", "mui": "Material UI",

    # Backend
    "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js",
    "express": "Express.js", "expressjs": "Express.js",
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
    "rails": "Ruby on Rails", "ror": "Ruby on Rails",
    "spring": "Spring Boot", "springboot": "Spring Boot",
    "laravel": "Laravel", "symfony": "Symfony",
    "graphql": "GraphQL", "rest": "REST API", "grpc": "gRPC",

    # Languages
    "python": "Python", "py": "Python",
    "java": "Java", "kotlin": "Kotlin",
    "go": "Go", "golang": "Go",
    "rust": "Rust", "cpp": "C++", "c++": "C++", "csharp": "C#", "c#": "C#",
    "ruby": "Ruby", "php": "PHP", "swift": "Swift",
    "scala": "Scala", "elixir": "Elixir", "haskell": "Haskell",

    # Databases
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "pg": "PostgreSQL",
    "mysql": "MySQL", "mariadb": "MariaDB",
    "mongodb": "MongoDB", "mongo": "MongoDB",
    "redis": "Redis",
    "sqlite": "SQLite",
    "elasticsearch": "Elasticsearch", "elastic": "Elasticsearch",
    "cassandra": "Cassandra",
    "dynamodb": "DynamoDB",
    "neo4j": "Neo4j",
    "sql": "SQL", "nosql": "NoSQL",

    # Cloud / DevOps
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud": "GCP",
    "azure": "Azure", "microsoft azure": "Azure",
    "docker": "Docker", "containers": "Docker",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "terraform": "Terraform", "pulumi": "Pulumi",
    "ansible": "Ansible",
    "ci/cd": "CI/CD", "cicd": "CI/CD",
    "github actions": "GitHub Actions",
    "jenkins": "Jenkins", "circleci": "CircleCI",
    "helm": "Helm",
    "nginx": "Nginx", "apache": "Apache",
    "serverless": "Serverless",

    # ML / Data
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "dl": "Deep Learning", "deep learning": "Deep Learning",
    "ai": "AI",
    "pytorch": "PyTorch", "torch": "PyTorch",
    "tensorflow": "TensorFlow", "tf": "TensorFlow",
    "keras": "Keras",
    "sklearn": "scikit-learn", "scikit-learn": "scikit-learn", "scikit learn": "scikit-learn",
    "pandas": "pandas", "numpy": "NumPy", "scipy": "SciPy",
    "spark": "Apache Spark", "pyspark": "PySpark",
    "hadoop": "Hadoop",
    "kafka": "Apache Kafka",
    "airflow": "Apache Airflow",
    "dbt": "dbt",
    "tableau": "Tableau", "powerbi": "Power BI", "power bi": "Power BI",
    "nlp": "NLP", "natural language processing": "NLP",
    "llm": "LLMs", "large language models": "LLMs",
    "langchain": "LangChain", "langgraph": "LangGraph",
    "openai": "OpenAI API", "anthropic": "Anthropic API",

    # Architecture / practices
    "microservices": "Microservices",
    "monolith": "Monolith",
    "event driven": "Event-Driven Architecture",
    "cqrs": "CQRS",
    "solid": "SOLID principles",
    "tdd": "TDD", "test driven": "TDD",
    "bdd": "BDD",
    "agile": "Agile", "scrum": "Scrum", "kanban": "Kanban",
    "git": "Git", "github": "GitHub", "gitlab": "GitLab",
    "api": "REST API",
    "oauth": "OAuth", "jwt": "JWT",
    "websockets": "WebSockets",
    "message queue": "Message Queues", "rabbitmq": "RabbitMQ",
}

CATEGORY_WEIGHTS: dict[str, float] = {
    "technical": 0.50,
    "behavioral": 0.25,
    "situational": 0.15,
    "resume_specific": 0.10,
}


def normalise_skill(raw: str) -> str:
    """Lowercase, strip, look up alias, return canonical name."""
    key = raw.strip().lower()
    return SKILL_ALIASES.get(key, raw.strip())


def normalise_skills(skills: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for s in skills:
        canonical = normalise_skill(s)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def match_skills(
    resume_skills: list[str],
    jd_required: list[str],
) -> dict:
    """
    Deterministic skill matching — no LLM.
    Returns matched, missing, extra, and coverage percentage.
    """
    resume_norm = set(normalise_skills(resume_skills))
    jd_norm = set(normalise_skills(jd_required))

    matched = sorted(resume_norm & jd_norm)
    missing = sorted(jd_norm - resume_norm)
    extra = sorted(resume_norm - jd_norm)
    coverage = len(matched) / len(jd_norm) * 100 if jd_norm else 0.0

    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "coverage_pct": round(coverage, 1),
    }


def semantic_match_skills(
    resume_skills: list[str],
    work_history_techs: list[str],
    jd_required: list[str],
) -> dict:
    """
    LLM-based semantic skill matching.

    Combines the resume's explicit skills list with technologies extracted from
    work history, then asks the LLM to determine which JD-required skills are
    covered — handling synonyms (React = React.js), acronyms (ML = Machine
    Learning, k8s = Kubernetes), and implied skills (Docker Compose → Docker).

    Falls back to alias-based matching if the LLM call fails.
    """
    if not jd_required:
        return {"matched": [], "missing": [], "extra": normalise_skills(resume_skills), "coverage_pct": 0.0}

    # Merge and deduplicate all resume skill signals
    all_resume = list(dict.fromkeys(resume_skills + work_history_techs))

    from schemas import SemanticSkillMatch
    from services.claude_service import call_structured, QUALITY_MODEL

    prompt = f"""You are a technical recruiter comparing a candidate's skills to job requirements.

REQUIRED BY JOB ({len(jd_required)} skills):
{', '.join(jd_required)}

CANDIDATE HAS (skills + work history technologies):
{', '.join(all_resume[:50])}

Rules — a required skill is COVERED when:
- Direct or near-exact match (React = React.js, Postgres = PostgreSQL, JS = JavaScript)
- Acronym or alias (ML = Machine Learning, k8s = Kubernetes, TS = TypeScript, AI = Artificial Intelligence)
- Version or flavour variant (Python 3 → Python, Node 18 → Node.js, GPT-4 → LLMs)
- Phrase contains a matching technology ("data pipelines" is covered by "Apache Airflow" or "data engineering")
- Candidate has a superset ("LangGraph" covers "LangChain", "ChromaDB" covers "vector search")
- Implied by demonstrated experience (FastAPI + Python → "Python web development")

Be generous: if the candidate clearly has the underlying skill even under a different name, mark it covered.

Classify EVERY required skill into exactly one group.
Return the exact skill names as they appear in the "REQUIRED BY JOB" list above.

covered: comma-separated required skills the candidate HAS
missing: comma-separated required skills the candidate LACKS"""

    try:
        result = call_structured(prompt, SemanticSkillMatch, model=QUALITY_MODEL)

        def parse_csv(s: str) -> list[str]:
            return [x.strip() for x in s.split(',') if x.strip().lower() not in ('', 'none', 'n/a')]

        covered = parse_csv(result.covered)
        missing = parse_csv(result.missing)

        # If a skill appears in both lists, covered wins
        covered_lower = {s.lower() for s in covered}
        missing = [s for s in missing if s.lower() not in covered_lower]

        # Ensure every JD skill is classified (guard against LLM omissions)
        classified = covered_lower | {s.lower() for s in missing}
        for skill in jd_required:
            if skill.lower() not in classified:
                missing.append(skill)

        # Extra = normalised resume skills not semantically covered by JD requirements
        jd_lower = {s.lower() for s in jd_required} | {s.lower() for s in covered}
        seen: set[str] = set()
        extra: list[str] = []
        for s in all_resume:
            canonical = normalise_skill(s)
            if canonical not in seen and canonical.lower() not in jd_lower:
                seen.add(canonical)
                extra.append(canonical)

        coverage = round(len(covered) / len(jd_required) * 100, 1) if jd_required else 0.0

        return {
            "matched": covered,
            "missing": missing,
            "extra": extra[:12],
            "coverage_pct": coverage,
        }

    except Exception:
        # Deterministic fallback — always works, less accurate
        return match_skills(resume_skills, jd_required)
