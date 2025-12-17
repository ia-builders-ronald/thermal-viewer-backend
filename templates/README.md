# Line Loss Report Template

This template is used by the ReportService to generate Line Loss Analytics PDF reports.

## Template Placeholders

The template uses `docxtpl` syntax (Jinja2-like). Replace static text with these placeholders:

### Simple Variables
| Placeholder | Description | Example Value |
|-------------|-------------|---------------|
| `{{date}}` | Date extracted | "December 17, 2025" |
| `{{period}}` | Survey period | "20250228-PMSB" |
| `{{site}}` | Site name (uppercase) | "EDC" |
| `{{sector}}` | Sector name (uppercase) | "MAHANAGDONG" |

### Table Row Loop
The table rows are generated dynamically. Use this syntax in ONE row only:

| Cell | Content |
|------|---------|
| LOCATION | `{%for row in rows%}{{row.section}}` |
| LENGTH (m) | `{{row.length}}{%endfor%}` |
| DESCRIPTION | (leave empty) |
| QTY | (leave empty) |
| UNIT COST | (leave empty) |
| TOTAL COST | (leave empty) |

**Important:** Delete all other static data rows (like `[PAD]`, `[LEN]`). The loop will generate as many rows as needed.

## Template Setup Steps

1. Open `line-loss-template.docx` in Microsoft Word or LibreOffice Writer
2. Replace `[DATE]` with `{{date}}`
3. Replace `[PERIOD]` with `{{period}}`
4. Replace `LEYTE` (or static site) with `{{site}}`
5. Replace `TONGONAN` (or static sector) with `{{sector}}`
6. In the table's first data row:
   - LOCATION cell: `{%for row in rows%}{{row.section}}`
   - LENGTH cell: `{{row.length}}{%endfor%}`
7. **Delete all other data rows** below the loop row
8. Save the file

## Data Structure

The backend receives this JSON and renders the template:

```json
{
  "site": "EDC",
  "sector": "MAHANAGDONG",
  "date": "December 17, 2025",
  "period": "20250228-PMSB",
  "rows": [
    {"section": "Pad 101", "length": "1.50"},
    {"section": "Pad 102", "length": "2.75"},
    {"section": "Pad 103", "length": "N/A"}
  ]
}
```

## Testing Locally

```python
from docxtpl import DocxTemplate

doc = DocxTemplate('line-loss-template.docx')
doc.render({
    'site': 'EDC',
    'sector': 'MAHANAGDONG',
    'date': 'December 17, 2025',
    'period': '20250228-PMSB',
    'rows': [
        {'section': 'Pad 101', 'length': '1.50'},
        {'section': 'Pad 102', 'length': '2.75'},
    ]
})
doc.save('test-output.docx')
```

Then convert to PDF:
```bash
libreoffice --headless --convert-to pdf --outdir . test-output.docx
```
