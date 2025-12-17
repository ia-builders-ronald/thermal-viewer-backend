"""
ReportService - Generates Line Loss Analytics PDF reports

Uses docxtpl to fill Word templates and LibreOffice to convert to PDF.
"""

import os
import subprocess
import tempfile
import logging
from docxtpl import DocxTemplate

logger = logging.getLogger(__name__)


class ReportService:
    """
    Service for generating PDF reports from Word templates.
    """

    def __init__(self, template_path: str):
        """
        Initialize the ReportService.

        Args:
            template_path: Path to the Word template file (.docx)
        """
        self.template_path = template_path
        if not os.path.exists(template_path):
            logger.warning(f"Template file not found: {template_path}")
        else:
            logger.info(f"ReportService initialized with template: {template_path}")

    def generate_pdf(self, report_data: dict) -> bytes:
        """
        Generate PDF report from data.

        1. Fill Word template with data using docxtpl
        2. Convert to PDF using LibreOffice headless mode
        3. Return PDF bytes

        Args:
            report_data: Dictionary containing:
                - site: Site name (string)
                - sector: Sector name (string)
                - rows: List of dicts with 'section' and 'length' keys

        Returns:
            PDF file as bytes

        Raises:
            FileNotFoundError: If template file doesn't exist
            Exception: If LibreOffice conversion fails
        """
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template file not found: {self.template_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Load and fill template
            logger.info(f"Loading template from: {self.template_path}")
            doc = DocxTemplate(self.template_path)
            doc.render(report_data)

            # 2. Save filled docx to temp directory
            filled_path = os.path.join(temp_dir, 'report.docx')
            doc.save(filled_path)
            logger.info(f"Filled template saved to: {filled_path}")

            # 3. Convert to PDF using LibreOffice
            logger.info("Converting to PDF using LibreOffice...")
            result = subprocess.run(
                [
                    'libreoffice',
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', temp_dir,
                    filled_path
                ],
                capture_output=True,
                timeout=60
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode() if result.stderr else 'Unknown error'
                logger.error(f"LibreOffice conversion failed: {error_msg}")
                raise Exception(f"PDF conversion failed: {error_msg}")

            # 4. Read and return PDF
            pdf_path = os.path.join(temp_dir, 'report.pdf')
            if not os.path.exists(pdf_path):
                raise Exception("PDF file was not created by LibreOffice")

            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()
                logger.info(f"PDF generated successfully ({len(pdf_bytes)} bytes)")
                return pdf_bytes

    def generate_docx(self, report_data: dict) -> bytes:
        """
        Generate filled Word document (without PDF conversion).

        Useful for testing or when PDF conversion is not needed.

        Args:
            report_data: Dictionary containing report data

        Returns:
            DOCX file as bytes
        """
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template file not found: {self.template_path}")

        doc = DocxTemplate(self.template_path)
        doc.render(report_data)

        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
            doc.save(tmp.name)
            tmp.seek(0)
            with open(tmp.name, 'rb') as f:
                docx_bytes = f.read()
            os.unlink(tmp.name)
            return docx_bytes
