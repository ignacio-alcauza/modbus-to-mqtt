#!/usr/bin/env python3
import sys
from pypdf import PdfReader

def extract_pdf(pdf_path, out_path):
    reader = PdfReader(pdf_path)
    with open(out_path, 'w', encoding='utf-8') as f:
        for i, page in enumerate(reader.pages):
            f.write(f"--- PAGE {i+1} ---\n")
            f.write(page.extract_text())
            f.write("\n\n")

if __name__ == '__main__':
    extract_pdf("BMS RS485 Modbus V1.1 for pb2a16s20p.pdf", "bms_pdf_content.txt")
