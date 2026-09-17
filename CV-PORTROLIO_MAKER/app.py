from __future__ import annotations

import html
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import cgi


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DRAFT_DIR = DATA_DIR / "drafts"


DOCUMENT_TYPES = {
    "cv": "Professional CV",
    "portfolio": "Career Portfolio",
    "professional_bio": "Professional Bio",
    "cover_letter": "Cover Letter",
    "linkedin_profile": "LinkedIn Profile",
}

TEMPLATES = {
    "formal_lines": {
        "name": "Formal Lines",
        "description": "Inspired by the uploaded CV: strong spacing, uppercase sections, divider lines, and plus-style bullets.",
    },
    "modern_focus": {
        "name": "Modern Focus",
        "description": "Clean recruiter-friendly layout with compact spacing and clear hierarchy.",
    },
    "executive_box": {
        "name": "Executive Box",
        "description": "Structured professional layout with bordered sections and a polished header.",
    },
    "portfolio_showcase": {
        "name": "Portfolio Showcase",
        "description": "Visual, project-forward template for portfolios, case studies, and professional profiles.",
    },
}

PAYMENT_TIERS = [
    ("Starter", "999", "One download", "Best for a single CV, cover letter, or portfolio export."),
    ("Career Pack", "2,499", "Five downloads", "Good for CV, portfolio, cover letter, bio, and LinkedIn profile."),
    ("Professional", "4,999", "Unlimited for 30 days", "For active job seekers creating multiple versions."),
]


INTERVIEW_STEPS = [
    ("basics", "Basics", "Identity, target role, and contact details"),
    ("summary", "Summary", "Your strongest professional positioning"),
    ("experience", "Experience", "Roles, achievements, tools, and impact"),
    ("education", "Education", "Schools, certifications, and training"),
    ("skills", "Skills", "Technical, creative, leadership, and soft skills"),
    ("projects", "Projects", "Portfolio work, case studies, and outcomes"),
    ("preferences", "Style", "Tone, audience, template, and export focus"),
]


@dataclass
class CandidateProfile:
    full_name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: str = ""
    target_role: str = ""
    industry: str = ""
    summary: str = ""
    experience: str = ""
    education: str = ""
    skills: str = ""
    projects: str = ""
    achievements: str = ""
    tone: str = "Modern and confident"
    pasted_information: str = ""
    source_notes: str = ""
    document_type: str = "cv"
    template: str = "formal_lines"
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))


def ensure_dirs() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, DRAFT_DIR):
        directory.mkdir(exist_ok=True)


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def split_lines(text: str) -> list[str]:
    return [line.strip(" -•\t") for line in text.splitlines() if line.strip(" -•\t")]


def first_clean_line(lines: list[str]) -> str:
    ignored = {
        "cv",
        "resume",
        "curriculum vitae",
        "portfolio",
        "professional portfolio",
        "bio",
        "professional bio",
    }
    for line in lines:
        lowered = line.lower().strip(":")
        if lowered not in ignored and "@" not in line and not line.lower().startswith(("phone", "email")):
            return line[:80]
    return ""


def extract_uploaded_text(file_item: cgi.FieldStorage | None) -> str:
    if file_item is None or not getattr(file_item, "filename", ""):
        return ""

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(file_item.filename).name)
    upload_path = UPLOAD_DIR / f"{secrets.token_hex(4)}_{safe_name}"
    raw = file_item.file.read()
    upload_path.write_bytes(raw)

    suffix = upload_path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".rtf"}:
        return raw.decode("utf-8", errors="ignore")

    if suffix == ".pdf":
        return (
            f"Uploaded PDF saved as {upload_path.name}. Text extraction for PDFs can be "
            "added with pypdf when dependencies are available."
        )

    if suffix in {".doc", ".docx"}:
        return (
            f"Uploaded document saved as {upload_path.name}. Text extraction for Word files "
            "can be added with python-docx when dependencies are available."
        )

    return f"Uploaded file saved as {upload_path.name}."


def infer_profile_from_text(text: str) -> dict[str, str]:
    lines = split_lines(text)
    joined = "\n".join(lines)
    profile: dict[str, str] = {}

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", joined)
    phone = re.search(r"(\+?\d[\d\s().-]{7,}\d)", joined)
    links = re.findall(r"(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com|[\w-]+\.(?:com|dev|io|org))/[^\s,;]+", joined)

    clean_name = first_clean_line(lines)
    if clean_name:
        profile["full_name"] = clean_name
    if len(lines) > 1 and len(lines[1]) < 90:
        profile["title"] = lines[1]
    if email:
        profile["email"] = email.group(0)
    if phone:
        profile["phone"] = phone.group(1)
    if links:
        profile["links"] = ", ".join(dict.fromkeys(links))

    section_map = {
        "summary": ["summary", "profile", "objective"],
        "experience": ["experience", "employment", "work history"],
        "education": ["education", "academic"],
        "skills": ["skills", "competencies", "technologies"],
        "projects": ["projects", "portfolio"],
        "achievements": ["achievements", "awards", "accomplishments"],
    }
    lower_lines = [line.lower() for line in lines]
    for field_name, headings in section_map.items():
        for index, lower in enumerate(lower_lines):
            if any(heading in lower for heading in headings):
                profile[field_name] = extract_section_value(lines, index, headings)
                break

    keyword_groups = {
        "experience": ["worked", "work at", "job", "role", "position", "company", "intern", "managed", "led", "developed"],
        "education": ["education", "school", "university", "college", "degree", "diploma", "certificate", "certification", "training"],
        "skills": ["skill", "tools", "technology", "technologies", "can use", "good at", "expert in"],
        "projects": ["project", "portfolio", "built", "created", "designed", "developed"],
        "achievements": ["award", "achievement", "increased", "improved", "reduced", "won", "recognized"],
    }
    for field_name, keywords in keyword_groups.items():
        if profile.get(field_name):
            continue
        matches = []
        for line in lines:
            if any(keyword in line.lower() for keyword in keywords):
                matches.append(clean_inline_value(line, keywords))
        if matches:
            profile[field_name] = "\n".join(matches[:8])

    if not profile.get("summary") and lines:
        profile["summary"] = arrange_summary(lines)
    profile["source_notes"] = text[:4000]
    return profile


def extract_section_value(lines: list[str], index: int, headings: list[str]) -> str:
    line = lines[index]
    lowered = line.lower().strip()
    if any(lowered in {heading, f"{heading}:"} for heading in headings):
        return "\n".join(lines[index + 1 : index + 8])
    return clean_inline_value(line, headings)


def clean_inline_value(line: str, keywords: list[str]) -> str:
    cleaned = line.strip()
    for keyword in keywords:
        pattern = re.compile(rf"^\s*(?:my\s+)?{re.escape(keyword)}(?:\s+are|\s+include|\s+includes|\s+is)?\s*[:\-]?\s*", re.IGNORECASE)
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip(" .:-") or line.strip()


def profile_from_form(form: cgi.FieldStorage) -> CandidateProfile:
    uploaded_text = extract_uploaded_text(form["source_file"] if "source_file" in form else None)
    pasted_text = form.getfirst("pasted_information", "")
    pasted_text = pasted_text.strip() if isinstance(pasted_text, str) else ""
    combined_source = "\n\n".join(part for part in [pasted_text, uploaded_text] if part)
    inferred = infer_profile_from_text(combined_source) if combined_source else {}

    values = {}
    for field_name in CandidateProfile.__dataclass_fields__:
        if field_name == "created_at":
            continue
        form_value = form.getfirst(field_name, "")
        values[field_name] = form_value.strip() if isinstance(form_value, str) else form_value

    for key, value in inferred.items():
        if key in values and not values[key]:
            values[key] = value

    if combined_source and not values.get("source_notes"):
        values["source_notes"] = combined_source[:4000]

    return CandidateProfile(**values)


def arrange_summary(lines: list[str]) -> str:
    useful = [
        line
        for line in lines
        if len(line) > 35 and not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", line)
    ]
    if useful:
        sentence = useful[0].rstrip(".")
        return f"{sentence}. Brings a clear record of practical experience, transferable strengths, and professional value."
    return ""


def bullets(text: str, fallback: list[str]) -> list[str]:
    lines = split_lines(text)
    return lines[:8] if lines else fallback


def generate_document(profile: CandidateProfile) -> str:
    name = profile.full_name or "Your Name"
    title = profile.title or profile.target_role or "Professional"
    target = profile.target_role or title
    skills = ", ".join(bullets(profile.skills, ["Communication", "Problem solving", "Leadership", "Digital tools"]))

    summary = profile.summary or (
        f"{title} with a practical, results-focused approach to work. Brings strong "
        f"communication, ownership, and a clear interest in {target} opportunities."
    )

    if profile.document_type == "portfolio":
        return render_markdown_portfolio(profile, name, title, summary, skills)
    if profile.document_type == "cover_letter":
        return render_cover_letter(profile, name, title, summary)
    if profile.document_type == "professional_bio":
        return render_bio(profile, name, title, summary)
    if profile.document_type == "linkedin_profile":
        return render_linkedin(profile, name, title, summary, skills)
    return render_cv(profile, name, title, summary, skills)


def render_cv(profile: CandidateProfile, name: str, title: str, summary: str, skills: str) -> str:
    experience = bullets(profile.experience, [f"Delivered reliable work aligned with {profile.target_role or 'business'} goals."])
    projects = bullets(profile.projects, ["Selected portfolio projects available on request."])
    achievements = bullets(profile.achievements, ["Recognized for dependable execution and collaborative problem solving."])
    education = bullets(profile.education, ["Education and professional training details."])

    return f"""# {name}
{title}

{profile.email} | {profile.phone} | {profile.location} | {profile.links}

## Professional Summary
{summary}

## Core Skills
{skills}

## Experience
{format_bullets(experience)}

## Selected Achievements
{format_bullets(achievements)}

## Projects
{format_bullets(projects)}

## Education
{format_bullets(education)}
"""


def render_markdown_portfolio(profile: CandidateProfile, name: str, title: str, summary: str, skills: str) -> str:
    projects = bullets(profile.projects, ["Project title - challenge, contribution, tools used, and measurable outcome."])
    achievements = bullets(profile.achievements, ["A clear result that proves credibility and growth."])
    return f"""# {name} Portfolio
## {title}

{summary}

## Signature Strengths
{skills}

## Featured Work
{format_bullets(projects)}

## Proof Of Impact
{format_bullets(achievements)}

## Contact
{profile.email} | {profile.phone} | {profile.location} | {profile.links}
"""


def render_cover_letter(profile: CandidateProfile, name: str, title: str, summary: str) -> str:
    role = profile.target_role or "the role"
    return f"""Dear Hiring Manager,

I am excited to apply for {role}. {summary}

In my previous work, I have built a strong record across these areas:
{format_bullets(bullets(profile.experience or profile.achievements, ["Solving practical problems, communicating clearly, and delivering dependable results."]))}

I would welcome the opportunity to bring this experience, focus, and professional energy to your team.

Sincerely,
{name}
{profile.email} | {profile.phone}
"""


def render_bio(profile: CandidateProfile, name: str, title: str, summary: str) -> str:
    return f"""{name} is a {title} focused on {profile.target_role or profile.industry or 'meaningful professional impact'}.

{summary}

Known strengths include {', '.join(bullets(profile.skills, ['clear communication', 'disciplined execution', 'creative problem solving'])[:5])}. {name.split()[0] if name != 'Your Name' else 'They'} brings a polished, practical approach to projects, teams, and client-facing work.
"""


def render_linkedin(profile: CandidateProfile, name: str, title: str, summary: str, skills: str) -> str:
    return f"""Headline:
{title} | {profile.target_role or profile.industry or 'Open to professional opportunities'} | {skills}

About:
{summary}

Featured Experience:
{format_bullets(bullets(profile.experience, ['Add 2-4 concise role highlights with results, tools, and business impact.']))}

Featured Projects:
{format_bullets(bullets(profile.projects, ['Add portfolio projects with links, responsibilities, and measurable outcomes.']))}
"""


def format_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def save_draft(profile: CandidateProfile, generated: str) -> str:
    draft_id = secrets.token_hex(6)
    payload = {"profile": profile.__dict__, "generated": generated}
    (DRAFT_DIR / f"{draft_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return draft_id


def load_draft(draft_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-f0-9]{12}", draft_id or ""):
        return None
    draft_path = DRAFT_DIR / f"{draft_id}.json"
    if not draft_path.exists():
        return None
    return json.loads(draft_path.read_text(encoding="utf-8"))


def document_filename(payload: dict[str, Any], draft_id: str, extension: str) -> str:
    profile = payload.get("profile", {})
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", profile.get("full_name") or "career-document").strip("-")
    doc_type = re.sub(r"[^A-Za-z0-9_-]+", "-", profile.get("document_type") or "document").strip("-")
    return f"{name.lower()}-{doc_type}-{draft_id}.{extension}"


def markdown_to_html(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    parts = []
    in_list = False
    in_paragraph = False

    def close_blocks() -> None:
        nonlocal in_list, in_paragraph
        if in_paragraph:
            parts.append("</p>")
            in_paragraph = False
        if in_list:
            parts.append("</ul>")
            in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_blocks()
            continue
        if stripped.startswith("# "):
            close_blocks()
            parts.append(f"<h1>{escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            close_blocks()
            parts.append(f"<h2>{escape(stripped[3:])}</h2>")
        elif stripped.startswith("- "):
            if in_paragraph:
                parts.append("</p>")
                in_paragraph = False
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{escape(stripped[2:])}</li>")
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            if not in_paragraph:
                parts.append("<p>")
                in_paragraph = True
            else:
                parts.append("<br>")
            parts.append(escape(stripped))

    close_blocks()
    return "\n".join(parts)


def page_shell(content: str, title: str = "CV Portfolio Maker") -> bytes:
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  {content}
</body>
</html>"""
    return html_doc.encode("utf-8")


def render_landing() -> bytes:
    tiers = "\n".join(
        f"""
        <article class="pricing-card">
          <span class="tier-name">{escape(name)}</span>
          <strong>₦{escape(price)}</strong>
          <p>{escape(label)}</p>
          <small>{escape(description)}</small>
          <a class="primary compact" href="/builder">Choose Plan</a>
        </article>
        """
        for name, price, label, description in PAYMENT_TIERS
    )
    content = f"""
<main class="landing-page">
  <nav class="landing-nav">
    <a class="logo-link" href="/">CV Portfolio Maker</a>
    <div>
      <a href="#signin">Sign In</a>
      <a class="download" href="/builder">Start Building</a>
    </div>
  </nav>

  <section class="landing-hero">
    <div>
      <p class="eyebrow">Professional CV and portfolio generator</p>
      <h1>Create polished career documents from rough information</h1>
      <p>Paste notes, upload an old CV, choose a template, and generate downloadable CVs, portfolios, cover letters, bios, and LinkedIn profiles.</p>
      <div class="hero-actions">
        <a class="primary" href="/builder">Create My Document</a>
        <a class="secondary-action" href="#pricing">View Payment Tiers</a>
      </div>
    </div>
  </section>

  <section class="auth-pricing-grid" id="signin">
    <section class="panel auth-panel">
      <p class="eyebrow">Owner access</p>
      <h2>Admin / Owner Sign Up</h2>
      <form class="auth-form">
        <input placeholder="Owner name">
        <input placeholder="Owner email">
        <input placeholder="Platform password" type="password">
        <button class="primary compact" type="button">Create Owner Account</button>
      </form>
    </section>
    <section class="panel auth-panel">
      <p class="eyebrow">User access</p>
      <h2>General User Sign Up / Sign In</h2>
      <form class="auth-form">
        <input placeholder="Full name or email">
        <input placeholder="Password" type="password">
        <button class="primary compact" type="button">Continue</button>
      </form>
    </section>
  </section>

  <section class="panel pricing-panel" id="pricing">
    <p class="eyebrow">Payment options</p>
    <h2>Affordable downloads from ₦999</h2>
    <p>Users can generate documents freely, then pay per download or choose a larger plan. ₦999 is approximately less than one US dollar depending on exchange rates and payment fees.</p>
    <div class="pricing-grid">{tiers}</div>
  </section>
</main>
"""
    return page_shell(content)


def render_home(profile: CandidateProfile | None = None, generated: str = "", draft_id: str = "") -> bytes:
    profile = profile or CandidateProfile()
    type_options = "\n".join(
        f'<option value="{escape(key)}" {"selected" if profile.document_type == key else ""}>{escape(label)}</option>'
        for key, label in DOCUMENT_TYPES.items()
    )
    template_cards = "\n".join(
        f"""
        <label class="template-card">
          <input type="radio" name="template" value="{escape(key)}" {"checked" if profile.template == key else ""}>
          <span>{escape(value["name"])}</span>
          <small>{escape(value["description"])}</small>
        </label>
        """
        for key, value in TEMPLATES.items()
    )
    step_cards = "\n".join(
        f'<button class="step" type="button" data-step="{escape(key)}"><span>{escape(label)}</span><small>{escape(copy)}</small></button>'
        for key, label, copy in INTERVIEW_STEPS
    )
    content = f"""
<main class="app-shell">
  <aside class="side-panel">
    <div class="brand">
      <span class="mark">CP</span>
      <div>
        <h1>CV Portfolio Maker</h1>
        <p>Build polished career documents from an old CV, notes, or a guided interview.</p>
      </div>
    </div>
    <nav class="doc-menu" aria-label="Document tools">
      <a href="/">Landing</a>
      <a href="#builder">Builder</a>
      <a href="#paste">Paste & Arrange</a>
      <a href="#templates">Templates</a>
      <a href="#upload">Upload</a>
      <a href="#interview">Interview</a>
      <a href="#preview">Preview</a>
      {f'<a href="/downloads?id={escape(draft_id)}">Downloads</a>' if draft_id else ''}
    </nav>
    <div class="quick-card">
      <strong>Document menus</strong>
      <p>CV, portfolio, bio, cover letter, and LinkedIn profile share one profile so users do not repeat themselves.</p>
    </div>
  </aside>

  <section class="workspace" id="builder">
    <form method="post" action="/generate" enctype="multipart/form-data" class="builder-grid">
      <section class="panel intro-panel">
        <div>
          <p class="eyebrow">Career document studio</p>
          <h2>Create a professional document in minutes</h2>
          <p>Paste rough information, upload an existing CV, or answer the interview prompts. The generator arranges your details into clear, recruiter-friendly content.</p>
        </div>
        <label class="select-label">Document type
          <select name="document_type">{type_options}</select>
        </label>
      </section>

      <section class="panel templates-panel" id="templates">
        <h3>Choose Template</h3>
        <p>Select the design style before generating. The chosen template is applied to the preview and every download page.</p>
        <div class="template-grid">{template_cards}</div>
      </section>

      <section class="panel paste-panel" id="paste">
        <h3>Paste & Arrange Menu</h3>
        <p>Paste messy notes, an old CV, WhatsApp-style details, project history, certificates, or copied job information. The platform will read it, organize it, and convert it into the selected document type.</p>
        <label class="field always-visible">
          <span>Paste information here</span>
          <textarea class="paste-box" name="pasted_information" placeholder="Example: My name is..., I worked at..., skills include..., projects include..., education..., achievements...">{escape(profile.pasted_information)}</textarea>
        </label>
        <div class="menu-actions">
          <a class="secondary-action" href="#upload">Add Upload</a>
          <button class="primary compact" type="submit">Arrange Pasted Info</button>
        </div>
      </section>

      <section class="panel upload-panel" id="upload">
        <h3>Upload Source</h3>
        <p>Use an old CV, portfolio notes, project list, or interview transcript. Plain text files are copied into the form automatically.</p>
        <input type="file" name="source_file" accept=".txt,.md,.csv,.rtf,.pdf,.doc,.docx">
        <div class="menu-actions">
          <a class="secondary-action" href="#interview">Continue Interview</a>
          <button class="primary compact" type="submit">Arrange Uploaded Info</button>
        </div>
      </section>

      <section class="panel interview-panel" id="interview">
        <h3>Guided Interview</h3>
        <div class="steps">{step_cards}</div>
        {render_fields(profile)}
        <div class="menu-actions">
          <a class="secondary-action" href="#paste">Back To Paste</a>
          <button class="primary" type="submit">Generate Document</button>
        </div>
      </section>
    </form>

    <section class="panel preview-panel" id="preview">
      <div class="preview-header">
        <div>
          <p class="eyebrow">Preview</p>
          <h3>{escape(DOCUMENT_TYPES.get(profile.document_type, "Generated Document"))}</h3>
        </div>
        {f'<a class="download" href="/downloads?id={escape(draft_id)}">Open Downloads</a>' if draft_id else ''}
      </div>
      <div class="document-sheet mini {escape(profile.template)}">
        {markdown_to_html(generated) if generated else '<p>Your generated CV, portfolio, bio, cover letter, or profile will appear here.</p>'}
      </div>
    </section>
  </section>
</main>
<script src="/static/app.js"></script>
"""
    return page_shell(content)


def render_downloads(draft_id: str) -> bytes:
    payload = load_draft(draft_id)
    if not payload:
        content = """
<main class="download-page">
  <section class="panel download-hero">
    <p class="eyebrow">Downloads</p>
    <h1>Draft not found</h1>
    <p>The generated document could not be found. Create a new document from the builder, then open the downloads page again.</p>
    <a class="download" href="/builder">Back To Builder</a>
  </section>
</main>
"""
        return page_shell(content, "Downloads")

    profile = payload.get("profile", {})
    generated = payload.get("generated", "")
    title = DOCUMENT_TYPES.get(profile.get("document_type", "cv"), "Generated Document")
    template = profile.get("template", "formal_lines")
    content = f"""
<main class="download-page">
  <section class="panel download-hero">
    <p class="eyebrow">Downloads</p>
    <h1>{escape(title)} Ready</h1>
    <p>Choose the format that fits your next step. Use HTML for a clean browser view, then print or save as PDF from your browser.</p>
    <div class="format-grid">
      <a class="format-card" href="/download?id={escape(draft_id)}&format=md"><span>Markdown</span><small>Editable .md document</small></a>
      <a class="format-card" href="/download?id={escape(draft_id)}&format=txt"><span>Plain Text</span><small>Simple copy-friendly text</small></a>
      <a class="format-card" href="/download?id={escape(draft_id)}&format=html"><span>HTML</span><small>Open in browser or save as PDF</small></a>
      <a class="format-card" href="/download?id={escape(draft_id)}&format=json"><span>Profile Data</span><small>Reusable structured data</small></a>
    </div>
    <div class="download-actions">
      <a class="secondary-action" href="/builder">Back To Builder</a>
      <button class="primary compact" type="button" onclick="window.print()">Print / Save PDF</button>
    </div>
  </section>
  <section class="document-sheet {escape(template)}">
    {markdown_to_html(generated)}
  </section>
</main>
"""
    return page_shell(content, "Downloads")


def input_field(name: str, label: str, profile: CandidateProfile, step: str, multiline: bool = False, placeholder: str = "") -> str:
    value = escape(getattr(profile, name))
    if multiline:
        field = f'<textarea name="{name}" placeholder="{escape(placeholder)}">{value}</textarea>'
    else:
        field = f'<input name="{name}" value="{value}" placeholder="{escape(placeholder)}">'
    return f'<label class="field" data-panel="{escape(step)}"><span>{escape(label)}</span>{field}</label>'


def render_fields(profile: CandidateProfile) -> str:
    return "\n".join(
        [
            input_field("full_name", "Full name", profile, "basics", placeholder="Ada Johnson"),
            input_field("title", "Current title", profile, "basics", placeholder="Frontend Developer"),
            input_field("email", "Email", profile, "basics"),
            input_field("phone", "Phone", profile, "basics"),
            input_field("location", "Location", profile, "basics"),
            input_field("links", "Links", profile, "basics", placeholder="LinkedIn, GitHub, website"),
            input_field("target_role", "Target role", profile, "summary"),
            input_field("industry", "Industry", profile, "summary"),
            input_field("summary", "Professional summary", profile, "summary", True, "What should employers remember about you?"),
            input_field("experience", "Experience highlights", profile, "experience", True, "One role, achievement, or responsibility per line"),
            input_field("education", "Education and certifications", profile, "education", True),
            input_field("skills", "Skills", profile, "skills", True, "One skill or skill group per line"),
            input_field("projects", "Portfolio projects", profile, "projects", True, "Project, contribution, tools, and result"),
            input_field("achievements", "Achievements", profile, "projects", True),
            input_field("tone", "Preferred tone", profile, "preferences", placeholder="Modern and confident"),
            input_field("source_notes", "Copied source notes", profile, "preferences", True),
        ]
    )


class AppHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/builder", "/downloads", "/download", "/static/styles.css", "/static/app.js"}:
            content_type = "text/html"
            if parsed.path.endswith(".css"):
                content_type = "text/css"
            elif parsed.path.endswith(".js"):
                content_type = "application/javascript"
            elif parsed.path == "/download":
                file_format = parse_qs(parsed.query).get("format", ["md"])[0]
                content_type = {
                    "txt": "text/plain",
                    "html": "text/html",
                    "json": "application/json",
                }.get(file_format, "text/markdown")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        ensure_dirs()
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond(render_landing(), "text/html")
        elif parsed.path == "/builder":
            self.respond(render_home(), "text/html")
        elif parsed.path == "/downloads":
            self.respond(render_downloads(parse_qs(parsed.query).get("id", [""])[0]), "text/html")
        elif parsed.path == "/static/styles.css":
            self.respond((ROOT / "static" / "styles.css").read_bytes(), "text/css")
        elif parsed.path == "/static/app.js":
            self.respond((ROOT / "static" / "app.js").read_bytes(), "application/javascript")
        elif parsed.path == "/download":
            query = parse_qs(parsed.query)
            self.download(query.get("id", [""])[0], query.get("format", ["md"])[0])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        ensure_dirs()
        if self.path != "/generate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        profile = profile_from_form(form)
        generated = generate_document(profile)
        draft_id = save_draft(profile, generated)
        self.respond(render_home(profile, generated, draft_id), "text/html")

    def download(self, draft_id: str, file_format: str) -> None:
        payload = load_draft(draft_id)
        if not payload:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        generated = payload.get("generated", "")
        if file_format == "txt":
            content_type = "text/plain"
            extension = "txt"
            content = generated.encode("utf-8")
        elif file_format == "html":
            content_type = "text/html"
            extension = "html"
            template = payload.get("profile", {}).get("template", "formal_lines")
            content = page_shell(f'<main class="download-page"><section class="document-sheet {escape(template)}">{markdown_to_html(generated)}</section></main>', "Generated Document")
        elif file_format == "json":
            content_type = "application/json"
            extension = "json"
            content = json.dumps(payload, indent=2).encode("utf-8")
        else:
            content_type = "text/markdown"
            extension = "md"
            content = generated.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{document_filename(payload, draft_id, extension)}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def respond(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    ensure_dirs()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("CV Portfolio Maker running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    run()
