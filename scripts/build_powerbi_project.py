"""Write the LoanLens Power BI project (PBIP: TMDL semantic model + PBIR report).

    python scripts/build_powerbi_project.py      # -> powerbi/LoanLens.pbip

Open powerbi/LoanLens.pbip in Power BI Desktop, set the DataFolder parameter to your
data/powerbi folder if it differs, Refresh, then File > Save As > .pbix if you want one file.
The report JSON validates against Microsoft's published PBIR schemas.
"""

import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "powerbi"
NAME = "LoanLens"
DEFAULT_DATA_FOLDER = r"C:\Job\MyProject\LoanLens-AI\data\powerbi"
S = "https://developer.microsoft.com/json-schemas/fabric"


def tag(key: str) -> str:  # stable lineage tags, so re-running gives identical files
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"loanlens/{key}"))


def write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, indent=2) if not isinstance(content, str) else content
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8")


if OUT.exists():
    shutil.rmtree(OUT)
model = OUT / f"{NAME}.SemanticModel"
report = OUT / f"{NAME}.Report"

# ------------------------------------------------------------------ project + model files
write(OUT / f"{NAME}.pbip", {
    "$schema": f"{S}/pbip/pbipProperties/1.0.0/schema.json",
    "version": "1.0",
    "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
    "settings": {"enableAutoRecovery": True},
})
write(model / "definition.pbism", {
    "$schema": f"{S}/item/semanticModel/definitionProperties/1.0.0/schema.json",
    "version": "4.0", "settings": {}})
write(report / "definition.pbir", {
    "$schema": f"{S}/item/report/definitionProperties/2.0.0/schema.json",
    "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})

D = model / "definition"
write(D / "database.tmdl", "database\n\tcompatibilityLevel: 1567\n\n")
write(D / "model.tmdl", """model Model
\tculture: en-US
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tsourceQueryCulture: en-US
\tdataAccessOptions
\t\tlegacyRedirects
\t\treturnErrorValuesAsNull

annotation PBI_QueryOrder = ["DataFolder","Loans","EMI_Schedule"]

ref table Loans
ref table EMI_Schedule

""")
write(D / "expressions.tmdl", f"""expression DataFolder = "{DEFAULT_DATA_FOLDER}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
\tlineageTag: {tag('param/DataFolder')}

\tannotation PBI_ResultType = Text

""")

# (column, TMDL dataType, M type, summarizeBy, formatString)
LOANS = [
    ("Loan_ID", "string", "type text", "none", None),
    ("Receipt_ID", "string", "type text", "none", None),
    ("Lender", "string", "type text", "none", None),
    ("Loan_Type", "string", "type text", "none", None),
    ("Borrower", "string", "type text", "none", None),
    ("Principal_Amount", "double", "type number", "sum", "#,##0"),
    ("Interest_Rate", "double", "type number", "none", "0.00"),
    ("Tenure_Months", "int64", "Int64.Type", "none", "0"),
    ("EMI_Amount", "double", "type number", "sum", "#,##0.00"),
    ("Disbursement_Date", "dateTime", "type date", "none", "dd-mmm-yyyy"),
    ("Installments_Paid", "int64", "Int64.Type", "sum", "0"),
    ("Total_Paid", "double", "type number", "sum", "#,##0"),
    ("Principal_Repaid", "double", "type number", "sum", "#,##0"),
    ("Interest_Paid", "double", "type number", "sum", "#,##0"),
    ("Late_Fees", "double", "type number", "sum", "#,##0.00"),
    ("Outstanding_Principal", "double", "type number", "sum", "#,##0"),
    ("Next_Due_Date", "dateTime", "type date", "none", "dd-mmm-yyyy"),
    ("Source", "string", "type text", "none", None),
]
EMI = [
    ("Loan_ID", "string", "type text", "none", None),
    ("Installment_No", "int64", "Int64.Type", "none", "0"),
    ("Due_Date", "dateTime", "type date", "none", "dd-mmm-yyyy"),
    ("Paid_Date", "dateTime", "type date", "none", "dd-mmm-yyyy"),
    ("EMI_Amount", "double", "type number", "sum", "#,##0.00"),
    ("Principal_Component", "double", "type number", "sum", "#,##0.00"),
    ("Interest_Component", "double", "type number", "sum", "#,##0.00"),
    ("Late_Fee", "double", "type number", "sum", "#,##0.00"),
    ("Outstanding_Balance", "double", "type number", "sum", "#,##0.00"),
    ("Status", "string", "type text", "none", None),
]
MEASURES = {  # name: (DAX, formatString, description)
    "Total Principal": ("SUM ( Loans[Principal_Amount] )", "#,##0",
                        "Sum of sanctioned principal across loans (INR)"),
    "Total EMI Collected": ("SUM ( Loans[Total_Paid] )", "#,##0",
                            "Sum of EMIs paid to date (INR)"),
    "Total Late Fees": ("SUM ( Loans[Late_Fees] )", "#,##0.00",
                        "Sum of late payment charges (INR)"),
    "Average Interest Rate": ("AVERAGE ( Loans[Interest_Rate] )", "0.00",
                              "Average annual interest rate (percent)"),
    "Late Payment %": ("DIVIDE ( CALCULATE ( COUNTROWS ( Loans ), Loans[Late_Fees] > 0 ), "
                       "COUNTROWS ( Loans ), 0 )", "0.0%",
                       "Share of loans with at least one late payment"),
    "Outstanding Principal": ("SUM ( Loans[Outstanding_Principal] )", "#,##0",
                              "Principal still to be repaid (INR)"),
    "Late Instalments": ("CALCULATE ( COUNTROWS ( EMI_Schedule ), "
                         "EMI_Schedule[Status] = \"Paid Late\" )", "0",
                         "Number of instalments paid late"),
}


def table_tmdl(name: str, file: str, cols: list, measures: dict) -> str:
    out = [f"table {name}", f"\tlineageTag: {tag('table/' + name)}", ""]
    for m, (dax, fmt, desc) in measures.items():
        out += [f"\t/// {desc}", f"\tmeasure '{m}' = {dax}", f"\t\tformatString: {fmt}",
                f"\t\tlineageTag: {tag('measure/' + m)}", ""]
    for col, dtype, _, summ, fmt in cols:
        out += [f"\tcolumn {col}", f"\t\tdataType: {dtype}"]
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out += [f"\t\tlineageTag: {tag(f'column/{name}/{col}')}", f"\t\tsummarizeBy: {summ}",
                f"\t\tsourceColumn: {col}", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    types = ", ".join(f'{{"{c}", {m}}}' for c, _, m, _, _ in cols)
    out += [
        f"\tpartition {name} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Csv.Document(File.Contents(DataFolder & "\\{file}"), '
        '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "\t\t\t\t    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        '\t\t\t\t    Blanks = Table.TransformColumns(Headers, {}, each if _ = "" then null else _),',
        f'\t\t\t\t    Typed = Table.TransformColumnTypes(Blanks, {{{types}}}, "en-US")',
        "\t\t\t\tin",
        "\t\t\t\t    Typed",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(out)


write(D / "tables" / "Loans.tmdl", table_tmdl("Loans", "loans.csv", LOANS, MEASURES))
write(D / "tables" / "EMI_Schedule.tmdl", table_tmdl("EMI_Schedule", "emi_schedule.csv", EMI, {}))
write(D / "relationships.tmdl", f"""relationship {tag('rel/emi-loans')}
\tfromColumn: EMI_Schedule.Loan_ID
\ttoColumn: Loans.Loan_ID

""")

# ------------------------------------------------------------------ report (PBIR)
R = report / "definition"
write(report / "StaticResources" / "RegisteredResources" / "LoanLensTheme.json", {
    "name": "LoanLens",
    "dataColors": ["#0F766E", "#1F3A5F", "#F59E0B", "#DC2626", "#6B2D5C", "#0EA5E9",
                   "#84CC16", "#64748B"],
    "background": "#FFFFFF", "foreground": "#1F2937", "tableAccent": "#0F766E",
})
write(R / "version.json", {"$schema": f"{S}/item/report/definition/versionMetadata/1.0.0/schema.json",
                           "version": "2.0.0"})
write(R / "report.json", {
    "$schema": f"{S}/item/report/definition/report/1.3.0/schema.json",
    "layoutOptimization": "None",
    "themeCollection": {"customTheme": {"name": "LoanLensTheme.json",
                                        "reportVersionAtImport": "5.61",
                                        "type": "RegisteredResources"}},
    "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                          "items": [{"name": "LoanLensTheme.json", "path": "LoanLensTheme.json",
                                     "type": "CustomTheme"}]}],
    "settings": {"useStylableVisualContainerHeader": True,
                 "exportDataMode": "AllowSummarizedAndUnderlying",
                 "defaultDrillFilterOtherVisuals": True, "useEnhancedTooltips": True},
})
PAGE = "loanPortfolio"
write(R / "pages" / "pages.json", {
    "$schema": f"{S}/item/report/definition/pagesMetadata/1.0.0/schema.json",
    "pageOrder": [PAGE], "activePageName": PAGE})
write(R / "pages" / PAGE / "page.json", {
    "$schema": f"{S}/item/report/definition/page/1.4.0/schema.json",
    "name": PAGE, "displayName": "Loan Portfolio", "displayOption": "FitToPage",
    "height": 720, "width": 1280})


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def measure(m, entity="Loans"):
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": m}},
            "queryRef": f"{entity}.{m}", "nativeQueryRef": m}


def column(c, entity="Loans"):
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": c}},
            "queryRef": f"{entity}.{c}", "nativeQueryRef": c, "active": True}


def title(text):
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'")}}]}


def visual(name, x, y, w, h, z, body):
    write(R / "pages" / PAGE / "visuals" / name / "visual.json", {
        "$schema": f"{S}/item/report/definition/visualContainer/2.0.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": {**body, "drillFilterOtherVisuals": True}})


visual("headerText", 20, 10, 900, 50, 0, {
    "visualType": "textbox",
    "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [
        {"value": "LoanLens AI  ·  Loan Receipts Portfolio",
         "textStyle": {"fontWeight": "bold", "fontSize": "20pt", "color": "#1F3A5F"}}]}]}}]}})

cards = ["Total Principal", "Total EMI Collected", "Total Late Fees", "Average Interest Rate",
         "Late Payment %"]
for i, m in enumerate(cards):
    visual(f"card{i + 1}", 20 + i * 250, 70, 235, 110, 1000 + i, {
        "visualType": "card",
        "query": {"queryState": {"Values": {"projections": [measure(m)]}}},
        "objects": {"labels": [{"properties": {"fontSize": lit("22D")}}]}})

visual("principalByType", 20, 195, 610, 250, 2000, {
    "visualType": "clusteredBarChart",
    "query": {"queryState": {"Category": {"projections": [column("Loan_Type")]},
                             "Y": {"projections": [measure("Total Principal")]}},
              "sortDefinition": {"sort": [{"field": measure("Total Principal")["field"],
                                           "direction": "Descending"}]}},
    "visualContainerObjects": title("Total Principal by Loan Type")})

visual("lateByLender", 650, 195, 610, 250, 3000, {
    "visualType": "clusteredColumnChart",
    "query": {"queryState": {"Category": {"projections": [column("Lender")]},
                             "Y": {"projections": [measure("Late Payment %")]}}},
    "visualContainerObjects": title("Late Payment % by Lender")})

visual("loanTable", 20, 460, 1240, 250, 4000, {
    "visualType": "tableEx",
    "query": {"queryState": {"Values": {"projections": [
        column("Loan_ID"), column("Lender"), column("Loan_Type"), column("Borrower"),
        measure("Total Principal"), measure("Average Interest Rate"),
        measure("Total EMI Collected"), measure("Total Late Fees"),
        measure("Outstanding Principal")]}}},
    "visualContainerObjects": title("Loans")})

write(OUT / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
print("written", sum(1 for p in OUT.rglob("*") if p.is_file()), "files to", OUT)
