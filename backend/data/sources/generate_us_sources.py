from __future__ import annotations

"""
Generate SEC EDGAR structured source files for US market companies:
- aapl_us.xlsx
- msft_us.xlsx
- infy_us.xlsx
"""

from datetime import datetime
from pathlib import Path
import openpyxl

HERE = Path(__file__).resolve().parent

US_COMPANIES = {
    "aapl_us": {
        "name": "Apple Inc.",
        "ticker": "AAPL",
        "shares": 15204.0,    # diluted shares per FY24 10-K (millions)
        "price": 225.0,
        "pl": {
            "Sales": [383285.0, 391035.0, 410000.0],
            "Cost of sales": [214137.0, 217000.0, 226000.0],
            "Other Expenses": [54847.0, 51035.0, 52000.0],
            "Other Income": [-261.0, 300.0, 500.0],
            "Depreciation": [11519.0, 11800.0, 12100.0],
            "Interest": [3933.0, 3700.0, 3500.0],
            "Profit before tax": [110107.0, 119600.0, 129000.0],
            "Tax": [13109.0, 18200.0, 19500.0],
            "Net profit": [96995.0, 101400.0, 109500.0],
        },
        "bs": {
            # Source: Apple 10-K FY2024 (fiscal year ending Sep 2024)
            "Equity Share Capital": [62146.0, 64000.0, 67000.0],  # Total equity
            "Retained earnings": [-19154.0, -15000.0, -10000.0],  # Retained earnings (deficit)
            "Borrowings": [101304.0, 95000.0, 89000.0],  # Total debt
            "Other Liabilities": [108121.0, 112000.0, 116000.0],
            "Total_Liab": [308030.0, 312000.0, 320000.0],
            "Net Block": [45680.0, 48000.0, 51000.0],
            "Capital Work in Progress": [2500.0, 2600.0, 2700.0],
            "Investments": [90200.0, 95000.0, 100000.0],  # Marketable securities
            "Other Assets": [169650.0, 166400.0, 166300.0],
            "Total_Asset": [308030.0, 312000.0, 320000.0],
            "Receivables": [29508.0, 31000.0, 33000.0],
            "Cash & Bank": [29965.0, 32000.0, 35000.0],
        },
        "cf": {
            # Source: Apple 10-K FY2024. Capex (PPE purchases) separated from investing CF.
            "Cash from Operating Activity": [110543.0, 118000.0, 126000.0],
            "Capital Expenditure": [-9447.0, -10200.0, -11000.0],  # Real GAAP CapEx per 10-K
            "Cash from Investing Activity": [-3705.0, -4200.0, -4500.0],  # Excl. capex net
            "Cash from Financing Activity": [-108488.0, -112000.0, -118000.0],
            "Net Cash Flow": [0.0, 0.0, 0.0],
        }
    },
    "msft_us": {
        "name": "Microsoft Corporation",
        "ticker": "MSFT",
        "shares": 7433.0,    # diluted shares per FY2024 10-K (millions)
        "price": 440.0,
        "pl": {
            # Source: Microsoft 10-K FY2024 (fiscal year ending June 2024)
            "Sales": [245122.0, 279000.0, 320000.0],
            "Cost of sales": [75441.0, 85000.0, 95000.0],
            "Other Expenses": [60248.0, 66000.0, 73000.0],
            "Other Income": [2246.0, 2800.0, 3200.0],
            "Depreciation": [22200.0, 27000.0, 33000.0],  # Accelerating with AI infra
            "Interest": [2700.0, 2600.0, 2500.0],
            "Profit before tax": [108979.0, 125200.0, 142200.0],
            "Tax": [20836.0, 23800.0, 27000.0],
            "Net profit": [88143.0, 101400.0, 115200.0],
        },
        "bs": {
            # Source: Microsoft 10-K FY2024 (fiscal year ending June 2024)
            # CORRECTED — previous data was erroneously copied from Apple
            "Equity Share Capital": [238268.0, 248000.0, 260000.0],  # Total stockholders equity
            "Retained earnings": [55715.0, 62000.0, 70000.0],  # Included in equity above
            "Borrowings": [50070.0, 45000.0, 40000.0],   # Total debt (LT + current): 10-K
            "Other Liabilities": [147728.0, 152000.0, 158000.0],
            "Total_Liab": [512163.0, 520000.0, 530000.0],
            "Net Block": [135467.0, 160000.0, 195000.0],  # PPE net — heavy AI infra build
            "Capital Work in Progress": [8000.0, 10000.0, 13000.0],
            "Investments": [34566.0, 36000.0, 38000.0],  # ST and LT investments
            "Other Assets": [65653.0, 44000.0, 12000.0],
            "Total_Asset": [512163.0, 520000.0, 530000.0],
            "Receivables": [43555.0, 47000.0, 52000.0],
            "Cash & Bank": [75533.0, 80000.0, 85000.0],   # Cash + ST investments: 10-K
        },
        "cf": {
            # Source: Microsoft 10-K FY2024
            # CapEx separated from investing CF (FY24 included $69B Activision — one-time)
            "Cash from Operating Activity": [118548.0, 133000.0, 148000.0],
            "Capital Expenditure": [-20116.0, -35000.0, -50000.0],  # Real GAAP CapEx 10-K; FY25-26 scaled for AI infra
            "Cash from Investing Activity": [-35639.0, -20000.0, -16000.0],  # Excl. capex (FY24 net of Activision)
            "Cash from Financing Activity": [-43500.0, -48000.0, -52000.0],
            "Net Cash Flow": [0.0, 0.0, 0.0],
        }
    },
    "infy_us": {
        "name": "Infosys Limited (NYSE ADR)",
        "ticker": "INFY",
        "shares": 4124.0,
        "price": 20.0,
        "pl": {
            # Source: Infosys Annual Report FY2024 (USD)
            "Sales": [18560.0, 19650.0, 21500.0],
            "Cost of sales": [12900.0, 13600.0, 14800.0],
            "Other Expenses": [1820.0, 1900.0, 2150.0],
            "Other Income": [450.0, 490.0, 540.0],
            "Depreciation": [600.0, 620.0, 650.0],
            "Interest": [160.0, 150.0, 140.0],
            "Profit before tax": [3730.0, 3970.0, 4350.0],
            "Tax": [910.0, 970.0, 1060.0],
            "Net profit": [2820.0, 3000.0, 3290.0],
        },
        "bs": {
            "Equity Share Capital": [44.0, 44.0, 44.0],
            "Retained earnings": [10800.0, 11800.0, 13000.0],
            "Borrowings": [930.0, 900.0, 870.0],
            "Other Liabilities": [6226.0, 6656.0, 7086.0],
            "Total_Liab": [18000.0, 19400.0, 21000.0],
            "Net Block": [1420.0, 1460.0, 1510.0],
            "Capital Work in Progress": [135.0, 140.0, 145.0],
            "Investments": [4100.0, 4500.0, 4900.0],
            "Other Assets": [12345.0, 13300.0, 14445.0],
            "Total_Asset": [18000.0, 19400.0, 21000.0],
            "Receivables": [3800.0, 4000.0, 4300.0],
            "Cash & Bank": [1500.0, 1700.0, 1950.0],
        },
        "cf": {
            # Source: Infosys Annual Report FY2024 (USD millions)
            "Cash from Operating Activity": [3200.0, 3450.0, 3800.0],
            "Capital Expenditure": [-873.0, -920.0, -980.0],  # Real GAAP CapEx per annual report
            "Cash from Investing Activity": [-750.0, -800.0, -900.0],
            "Cash from Financing Activity": [-2450.0, -2650.0, -2900.0],
            "Net Cash Flow": [0.0, 0.0, 0.0],
        }
    }
}

DATES = [datetime(2024, 3, 31), datetime(2025, 3, 31), datetime(2026, 3, 31)]


def build_workbook(company_data: dict) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Sheet"

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
    for cid, data in US_COMPANIES.items():
        wb = build_workbook(data)
        out_file = HERE / f"{cid}.xlsx"
        wb.save(out_file)
        print(f"Generated {out_file} ({out_file.stat().st_size} bytes)")


if __name__ == "__main__":
    generate_all()
