"""Step 4. Build the intervention cost and break-even workbook. Data cells come from results.json;
every result cell is a live Excel formula so the model recalculates when an assumption changes."""
import json, pathlib, sqlite3
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.comments import Comment

ROOT = pathlib.Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "data" / "results.json").read_text())
con = sqlite3.connect(ROOT / "data" / "olist.db")
P, H, B = R["pilot"], R["holdout"]["dispatch miss flag"], R["promise_buffer"]
lanes = R["lane_holdout"]["lanes_flagged"]
lane_value = con.execute(f"""SELECT AVG(order_value) FROM mart_orders WHERE purchase_month >= '2018-04'
                             AND lane IN ({','.join('?' * len(lanes))})""", lanes).fetchone()[0]

import csv
_fl = sorted((int(float(r["late_dispatch"])) for r in csv.DictReader(open(ROOT / "data" / "seller_scorecard.csv")) if r["flag_dispatch"] == "True"), reverse=True)
COVER = round(sum(_fl[:30]) / sum(_fl), 3)

F = "Arial"
BLUE, BLACK = Font(name=F, color="0000FF"), Font(name=F)
BOLD, TITLE = Font(name=F, bold=True), Font(name=F, bold=True, size=14)
HEAD = PatternFill("solid", fgColor="1F3A5F"); HEADF = Font(name=F, bold=True, color="FFFFFF")
YELLOW, GREY = PatternFill("solid", fgColor="FFFF00"), PatternFill("solid", fgColor="F2F2F2")
thin = Side(style="thin", color="BFBFBF"); BOX = Border(top=thin, bottom=thin, left=thin, right=thin)
BRL, PCT, NUM = 'R$ #,##0;(R$ #,##0);-', '0.0%', '#,##0;(#,##0);-'

wb = Workbook()

def sheet(name, widths):
    ws = wb.create_sheet(name)
    for col, w in zip("ABCDEFGHIJ", widths):
        ws.column_dimensions[col].width = w
    ws.sheet_view.showGridLines = False
    return ws

def header(ws, row, labels):
    for i, l in enumerate(labels):
        c = ws.cell(row, i + 1, l); c.font, c.fill, c.border = HEADF, HEAD, BOX
        c.alignment = Alignment(wrap_text=True, vertical="center")

def line(ws, row, label, value, fmt, note="", kind="formula"):
    a = ws.cell(row, 1, label); a.font, a.border = BLACK, BOX
    b = ws.cell(row, 2, value); b.number_format, b.border = fmt, BOX
    b.font = BLUE if kind in ("data", "assumption") else BLACK
    if kind == "assumption": b.fill = YELLOW
    if kind == "result": b.font, b.fill = BOLD, GREY
    c = ws.cell(row, 3, note); c.font, c.border = Font(name=F, color="595959", size=9), BOX
    c.alignment = Alignment(wrap_text=True, vertical="top")

# ---------------- Read me ----------------
ws = wb.active; ws.title = "Read me"; ws.sheet_view.showGridLines = False
ws.column_dimensions["A"].width = 110
rows = [("Delivery reliability: intervention cost and break-even model", TITLE),
        ("Two interventions are costed: coaching sellers who miss dispatch deadlines, and a longer delivery promise on lanes that stay late.", BLACK),
        ("", BLACK), ("How to use", BOLD),
        ("Yellow cells with blue text on the Inputs sheet are assumptions. Change them and every result recalculates.", BLACK),
        ("Blue text without fill is measured from the Olist data. Leave it unless you rerun the pipeline.", BLACK),
        ("Black text is a formula. Do not overwrite.", BLACK),
        ("", BLACK), ("Sheets", BOLD),
        ("Inputs: measured values and assumptions.", BLACK),
        ("Seller pilot: cost, benefit and break-even of coaching the flagged sellers.", BLACK),
        ("Lane promise: effect of adding days to the delivery estimate on the 12 lanes that stayed late in the holdout.", BLACK),
        ("Sensitivity: net benefit of the seller pilot across coaching effect and cost of a late order.", BLACK),
        ("", BLACK), ("Important", BOLD),
        ("Cost figures are placeholders. Olist does not publish support, refund or coaching costs, so replace the yellow cells with real numbers before using a result.", BLACK),
        (f"Data: Olist public dataset, {R['scope']['orders']:,} delivered orders, {R['scope']['from']} to {R['scope']['to']}. Currency: Brazilian real (R$).", BLACK)]
for i, (t, f) in enumerate(rows, 1):
    c = ws.cell(i, 1, t); c.font = f; c.alignment = Alignment(wrap_text=True)

# ---------------- Inputs ----------------
ws = sheet("Inputs", [52, 16, 78])
ws["A1"] = "Inputs"; ws["A1"].font = TITLE
header(ws, 3, ["Measured from the data", "Value", "Source"])
line(ws, 4, "Sellers flagged for missing dispatch deadlines", P["sellers"], NUM, "pipeline/03_analyse.py: 30 or more orders and Wilson lower bound of dispatch miss rate above the platform rate", "data")
line(ws, 5, "Late orders caused by dispatch at those sellers, in the data window", P["late_dispatch"], NUM, "mart_sellers.late_dispatch summed over flagged sellers", "data")
line(ws, 6, "Months in the data window", P["months_of_data"], NUM, "January 2017 to August 2018", "data")
line(ws, 7, "Persistence of the dispatch gap", H["persistence"], '0.00', "Holdout test: share of the flagged sellers' excess dispatch miss rate that remained in April to August 2018", "data")
line(ws, 8, "Average value of a late order (R$)", P["avg_value_of_late_order"], BRL, "mart_orders: mean order_value where is_late = 1", "data")
line(ws, 9, "Orders on the 12 persistent lanes, holdout window", B["test_orders"], NUM, "April to August 2018", "data")
line(ws, 10, "Late orders on those lanes, holdout window", B["test_late"], NUM, "April to August 2018", "data")
line(ws, 11, "Months in the holdout window", B["months"], NUM, "April to August 2018", "data")
line(ws, 12, "Average order value on those lanes (R$)", round(lane_value, 2), BRL, "mart_orders, holdout window", "data")
header(ws, 14, ["Assumptions (replace with real figures)", "Value", "Why this starting value"])
line(ws, 15, "Coaching effect: share of dispatch caused late orders removed", 0.30, PCT, "Unknown until piloted. Simulation range is 15% to 50%. The pilot exists to measure this.", "assumption")
line(ws, 16, "Cost to coach one seller for the pilot (R$)", 400, BRL, "Placeholder: a few hours of an account manager plus reporting", "assumption")
line(ws, 17, "Cost of one late order to the marketplace (R$)", 40, BRL, "Placeholder: support contact, goodwill credit and lost repeat purchase. 62% of late orders get 1 or 2 stars against 9% on time.", "assumption")
line(ws, 18, "Sellers in the pilot", 30, NUM, "A bounded pilot: start with the sellers with the most dispatch caused late orders", "assumption")
line(ws, 19, "Share of flagged sellers' dispatch late orders covered by the pilot sellers", COVER, PCT, "Measured for the top 30 flagged sellers by dispatch caused late orders. Update if you change the pilot size; the dashboard simulator shows any size.", "data")
line(ws, 20, "Days added to the delivery promise on persistent lanes", 3, NUM, "Whole number from 1 to 7", "assumption")
line(ws, 21, "Orders lost per extra promised day", 0.002, '0.00%', "Placeholder: 0.2% fewer orders for each day added. Unknown; needs an A/B test.", "assumption")
line(ws, 22, "Marketplace take rate", 0.12, PCT, "Placeholder commission on order value", "assumption")

# ---------------- Seller pilot ----------------
ws = sheet("Seller pilot", [58, 18, 70])
ws["A1"] = "Seller dispatch coaching pilot: annual cost, benefit and break-even"; ws["A1"].font = TITLE
header(ws, 3, ["Step", "Value", "How it is calculated"])
line(ws, 4, "Dispatch caused late orders per year, all flagged sellers", "=Inputs!B5*12/Inputs!B6", NUM, "Data window scaled to 12 months")
line(ws, 5, "Of which at the pilot sellers", "=B4*Inputs!B19", NUM, "Pilot coverage share")
line(ws, 6, "Expected to recur without action", "=B5*Inputs!B7", NUM, "Only the persistent part of the gap can be fixed. The rest was noise or carrier driven.")
line(ws, 7, "Late orders avoided per year", "=B6*Inputs!B15", NUM, "Recurring late orders x coaching effect")
line(ws, 8, "Annual benefit (R$)", "=B7*Inputs!B17", BRL, "Avoided late orders x cost of a late order")
line(ws, 9, "Pilot cost (R$)", "=Inputs!B18*Inputs!B16", BRL, "Sellers x cost per seller")
line(ws, 10, "Net benefit (R$)", "=B8-B9", BRL, "", "result")
line(ws, 11, "Return on cost", "=IF(B9=0,0,B10/B9)", PCT, "", "result")
header(ws, 13, ["Break-even", "Value", "Reading"])
line(ws, 14, "Coaching effect needed to break even", "=IF(B6*Inputs!B17=0,0,B9/(B6*Inputs!B17))", PCT, "Above 100% means coaching cannot pay for itself at these costs", "result")
line(ws, 15, "Cost of a late order needed to break even (R$)", "=IF(B7=0,0,B9/B7)", BRL, "If a late order truly costs more than this, the pilot pays", "result")
line(ws, 16, "Highest affordable cost per seller (R$)", "=IF(Inputs!B18=0,0,B8/Inputs!B18)", BRL, "Spend less than this per seller", "result")

# ---------------- Lane promise ----------------
ws = sheet("Lane promise", [58, 18, 70])
ws["A1"] = "Longer delivery promise on the 12 persistent lanes: annual effect"; ws["A1"].font = TITLE
header(ws, 3, ["Days added", "Late orders avoided in holdout window", "Source"])
for k in range(1, 8):
    line(ws, 3 + k, k, B["avoided_by_days"][str(k)], NUM, "Late orders in the holdout whose excess was this many days or fewer", "data")
    ws.cell(3 + k, 1).alignment = Alignment(horizontal="left")
header(ws, 12, ["Step", "Value", "How it is calculated"])
line(ws, 13, "Days added (from Inputs)", "=Inputs!B20", NUM, "")
line(ws, 14, "Late orders avoided per year", "=INDEX(B4:B10,B13)*12/Inputs!B11", NUM, "Holdout window scaled to 12 months")
line(ws, 15, "Share of those lanes' late orders removed", "=INDEX(B4:B10,B13)/Inputs!B10", PCT, "")
line(ws, 16, "Annual benefit (R$)", "=B14*Inputs!B17", BRL, "Avoided late orders x cost of a late order")
line(ws, 17, "Orders per year on those lanes", "=Inputs!B9*12/Inputs!B11", NUM, "")
line(ws, 18, "Orders lost to the longer promise per year", "=B17*Inputs!B21*B13", NUM, "Orders x loss per day x days added")
line(ws, 19, "Annual commission lost (R$)", "=B18*Inputs!B12*Inputs!B22", BRL, "Lost orders x order value x take rate")
line(ws, 20, "Net benefit (R$)", "=B16-B19", BRL, "", "result")
line(ws, 21, "Order loss per day at which this breaks even", "=IF(B17*B13*Inputs!B12*Inputs!B22=0,0,B16/(B17*B13*Inputs!B12*Inputs!B22))", '0.00%', "If the true loss per day is below this, the longer promise pays", "result")

# ---------------- Sensitivity ----------------
ws = sheet("Sensitivity", [34, 14, 14, 14, 14, 14, 14, 14])
ws["A1"] = "Seller pilot net benefit (R$): coaching effect against cost of a late order"; ws["A1"].font = TITLE
ws["A2"] = "Rows: coaching effect. Columns: cost of one late order (R$). Other inputs come from the Inputs sheet."; ws["A2"].font = Font(name=F, color="595959", size=9)
costs, effects = [20, 40, 60, 80, 120, 160, 200], [0.15, 0.20, 0.30, 0.40, 0.50]
c = ws.cell(4, 1, "Effect \\ Cost of late order"); c.font, c.fill, c.border = HEADF, HEAD, BOX
for j, v in enumerate(costs):
    c = ws.cell(4, 2 + j, v); c.font, c.fill, c.border, c.number_format = HEADF, HEAD, BOX, BRL
for i, e in enumerate(effects):
    c = ws.cell(5 + i, 1, e); c.font, c.fill, c.border, c.number_format = HEADF, HEAD, BOX, PCT
    c.alignment = Alignment(horizontal="left")
    for j in range(len(costs)):
        col = "BCDEFGH"[j]
        c = ws.cell(5 + i, 2 + j, f"='Seller pilot'!$B$6*$A{5 + i}*{col}$4-'Seller pilot'!$B$9")
        c.number_format, c.border, c.font = BRL, BOX, BLACK
ws["A11"] = "Negative cells mean the pilot loses money at that combination."; ws["A11"].font = Font(name=F, color="595959", size=9)
from openpyxl.formatting.rule import CellIsRule
ws.conditional_formatting.add("B5:H9", CellIsRule(operator="lessThan", formula=["0"], font=Font(name=F, color="C00000")))
ws.conditional_formatting.add("B5:H9", CellIsRule(operator="greaterThan", formula=["0"], fill=PatternFill("solid", bgColor="E2EFDA")))

out = ROOT / "excel" / "intervention_break_even.xlsx"
wb.save(out); print("saved", out)
