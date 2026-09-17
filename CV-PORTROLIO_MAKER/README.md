# CV Portfolio Maker

A small Python platform for generating career documents from pasted information, an uploaded source file, or a guided interview.

## Features

- Menus for CVs, portfolios, professional bios, cover letters, and LinkedIn-style profiles.
- Paste & Arrange menu for dropping rough information that is automatically organized into the selected document type.
- Upload area for old CVs, notes, project lists, or transcripts.
- Interview-style form sections for basics, summary, experience, education, skills, projects, and style.
- Landing page with admin/owner sign-up, general user sign-up/sign-in, and payment tier menus.
- Multiple visual templates, including a formal line-based CV style inspired by the provided PDF reference.
- Action buttons at the bottom of menus so users can arrange pasted/uploaded information or generate a document quickly.
- Dedicated downloads page for Markdown, plain text, HTML, and JSON exports.
- Browser print support from the downloads page for saving a clean PDF.
- No required third-party Python dependencies.

## Run

```bash
python3 app.py
```

Open `http://127.0.0.1:8000`.

Uploaded files and drafts are stored in `data/`, which is ignored by git.
