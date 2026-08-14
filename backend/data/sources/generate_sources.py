from __future__ import annotations

"""
Generate Screener-formatted Excel source files for target companies:
- tcs_tcs.xlsx
- tatamotors_tatamotors.xlsx
- tatasteel_tatasteel.xlsx
"""

from datetime import datetime
from pathlib import Path
import openpyxl

HERE = Path(__file__).resolve().parent

COMPANIES = {
    "tcs_tcs": {
        "name": "Tata Consultancy Services Limited",
        "ticker": "TCS",
        "shares": 361.8,
        "price": 4120.0,
        "pl": {
            "Sales": [240893.0, 255273.0, 272400.0],
            "Employee Cost": [133000.0, 141000.0, 149000.0],
            "Other Expenses": [44321.0, 46900.0, 49800.0],
            "Other Income": [3747.0, 4120.0, 4500.0],
            "Depreciation": [5022.0, 5200.0, 5400.0],
            "Interest": [1326.0, 1280.0, 1200.0],
            "Profit before tax": [60971.0, 65013.0, 71500.0],
            "Tax": [14872.0, 15900.0, 17500.0],
            "Net profit": [46099.0, 49113.0, 54000.0],
        },
        "bs": {
            "Equity Share Capital": [362.0, 362.0, 362.0],
            "Reserves": [89950.0, 98500.0, 108200.0],
            "Borrowings": [7725.0, 7500.0, 7200.0],
            "Other Liabilities": [52100.0, 55200.0, 58400.0],
            "Total_Liab": [150137.0, 161562.0, 174162.0],
            "Net Block": [11850.0, 12200.0, 12600.0],
            "Capital Work in Progress": [1120.0, 1150.0, 1200.0],
            "Investments": [34200.0, 37500.0, 41000.0],
            "Other Assets": [102967.0, 110712.0, 119362.0],
            "Total_Asset": [150137.0, 161562.0, 174162.0],
            "Receivables": [41200.0, 43500.0, 46000.0],
            "Cash & Bank": [12500.0, 14200.0, 16500.0],
        },
        "cf": {
            "Cash from Operating Activity": [44340.0, 47800.0, 52000.0],
            "Cash from Investing Activity": [-6210.0, -7100.0, -7800.0],
            "Cash from Financing Activity": [-38130.0, -40700.0, -44200.0],
            "Net Cash Flow": [0.0, 0.0, 0.0],
        }
    },
    "tatamotors_tatamotors": {
        "name": "Tata Motors Limited",
        "ticker": "TATAMOTORS",
        "shares": 367.0,
        "price": 980.0,
        "pl": {
            "Sales": [437928.0, 468500.0, 502000.0],
            "Raw Material Cost": [270000.0, 288000.0, 308000.0],
            "Employee Cost": [38612.0, 41200.0, 44000.0],
            "Other Expenses": [70000.0, 75000.0, 80000.0],
            "Other Income": [3820.0, 4100.0, 4400.0],
            "Depreciation": [26450.0, 27800.0, 29200.0],
            "Interest": [10187.0, 9200.0, 8100.0],
            "Profit before tax": [26499.0, 31400.0, 37100.0],
            "Tax": [7000.0, 8300.0, 9800.0],
            "Net profit": [19499.0, 23100.0, 27300.0],
        },
        "bs": {
            "Equity Share Capital": [766.0, 766.0, 766.0],
            "Reserves": [84500.0, 102000.0, 124000.0],
            "Borrowings": [53745.0, 46200.0, 39500.0],
            "Other Liabilities": [201989.0, 216034.0, 230734.0],
            "Total_Liab": [341000.0, 365000.0, 395000.0],
            "Net Block": [142000.0, 151000.0, 161000.0],
            "Capital Work in Progress": [14500.0, 15200.0, 16000.0],
            "Investments": [38000.0, 41000.0, 45000.0],
            "Other Assets": [146500.0, 157800.0, 173000.0],
            "Total_Asset": [341000.0, 365000.0, 395000.0],
            "Receivables": [18500.0, 19800.0, 21000.0],
            "Cash & Bank": [28000.0, 31500.0, 35000.0],
        },
        "cf": {
            "Cash from Operating Activity": [68000.0, 72500.0, 78000.0],
            "Cash from Investing Activity": [-32000.0, -34000.0, -36000.0],
            "Cash from Financing Activity": [-36000.0, -38500.0, -42000.0],
            "Net Cash Flow": [0.0, 0.0, 0.0],
        }
    },
    "tatasteel_tatasteel": {
        "name": "Tata Steel Limited",
        "ticker": "TATASTEEL",
        "shares": 1248.0,
        "price": 155.0,
        "pl": {
            "Sales": [229171.0, 242000.0, 258000.0],
            "Raw Material Cost": [115000.0, 120000.0, 127000.0],
            "Power and Fuel": [25000.0, 26500.0, 28000.0],
            "Employee Cost": [24000.0, 25000.0, 26000.0],
            "Other Expenses": [41768.0, 43500.0, 46000.0],
            "Other Income": [1850.0, 1950.0, 2100.0],
            "Depreciation": [10230.0, 10800.0, 11400.0],
            "Interest": [7495.0, 7100.0, 6700.0],
            "Profit before tax": [7528.0, 11050.0, 15000.0],
            "Tax": [2610.0, 3850.0, 5200.0],
            "Net profit": [4918.0, 7200.0, 9800.0],
        },
        "bs": {
            "Equity Share Capital": [1248.0, 1248.0, 1248.0],
            "Reserves": [87500.0, 93200.0, 101000.0],
            "Borrowings": [84400.0, 79000.0, 73500.0],
            "Other Liabilities": [112852.0, 119552.0, 126252.0],
            "Total_Liab": [286000.0, 293000.0, 302000.0],
            "Net Block": [148000.0, 154000.0, 161000.0],
            "Capital Work in Progress": [31000.0, 29000.0, 27000.0],
            "Investments": [12000.0, 13000.0, 14000.0],
            "Other Assets": [95000.0, 97000.0, 100000.0],
            "Total_Asset": [286000.0, 293000.0, 302000.0],
            "Receivables": [11200.0, 11800.0, 12500.0],
            "Cash & Bank": [9800.0, 10500.0, 11200.0],
        },
        "cf": {
            "Cash from Operating Activity": [21500.0, 25000.0, 29000.0],
            "Cash from Investing Activity": [-14500.0, -15500.0, -16500.0],
            "Cash from Financing Activity": [-7000.0, -9500.0, -12500.0],
            "Net Cash Flow": [0.0, 0.0, 0.0],
        }
    }
}

DATES = [datetime(2024, 3, 31), datetime(2025, 3, 31), datetime(2026, 3, 31)]


def build_workbook(company_data: dict) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Sheet"

    # Row 1-8 Metadata
    ws.cell(row=1, column=1, value="COMPANY NAME")
    ws.cell(row=1, column=2, value=company_data["name"])
    ws.cell(row=8, column=1, value="Market Capitalization")
    ws.cell(row=8, column=2, value=company_data["shares"] * company_data["price"])

    # PROFIT & LOSS
    ws.cell(row=15, column=1, value="PROFIT & LOSS")
    ws.cell(row=16, column=1, value="Report Date")
    for col_idx, d in enumerate(DATES, start=2):
        ws.cell(row=16, column=col_idx, value=d)

    curr_row = 17
    for label, vals in company_data["pl"].items():
        ws.cell(row=curr_row, column=1, value=label)
        for col_idx, val in enumerate(vals, start=2):
            ws.cell(row=curr_row, column=col_idx, value=val)
        curr_row += 1

    # BALANCE SHEET
    curr_row += 2
    ws.cell(row=curr_row, column=1, value="BALANCE SHEET")
    curr_row += 1
    ws.cell(row=curr_row, column=1, value="Report Date")
    for col_idx, d in enumerate(DATES, start=2):
        ws.cell(row=curr_row, column=col_idx, value=d)
    curr_row += 1

    for label, vals in company_data["bs"].items():
        if label == "Total_Liab":
            clean_label = "Total Liabilities & Equity"
        elif label == "Total_Asset":
            clean_label = "Total Assets"
        else:
            clean_label = label
        ws.cell(row=curr_row, column=1, value=clean_label)
        for col_idx, val in enumerate(vals, start=2):
            ws.cell(row=curr_row, column=col_idx, value=val)
        curr_row += 1

    # CASH FLOW:
    curr_row += 2
    ws.cell(row=curr_row, column=1, value="CASH FLOW:")
    curr_row += 1
    ws.cell(row=curr_row, column=1, value="Report Date")
    for col_idx, d in enumerate(DATES, start=2):
        ws.cell(row=curr_row, column=col_idx, value=d)
    curr_row += 1

    for label, vals in company_data["cf"].items():
        ws.cell(row=curr_row, column=1, value=label)
        for col_idx, val in enumerate(vals, start=2):
            ws.cell(row=curr_row, column=col_idx, value=val)
        curr_row += 1

    return wb


def generate_all() -> None:
    for cid, data in COMPANIES.items():
        wb = build_workbook(data)
        out_file = HERE / f"{cid}.xlsx"
        wb.save(out_file)
        print(f"Generated {out_file} ({out_file.stat().st_size} bytes)")


if __name__ == "__main__":
    generate_all()
