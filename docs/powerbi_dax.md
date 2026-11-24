# Power BI: loan receipts dashboard

Data: `data/powerbi/loans.csv` (table **Loans**, one row per loan) and
`data/powerbi/emi_schedule.csv` (table **EMI_Schedule**, one row per instalment).
Build them with `python scripts/export_powerbi.py` after parsing (or `--source truth`).
Relationship: `Loans[Loan_ID]` 1 → * `EMI_Schedule[Loan_ID]`.

## Measures

```DAX
Total Principal = SUM ( Loans[Principal_Amount] )

Total EMI Collected = SUM ( Loans[Total_Paid] )

Total Late Fees = SUM ( Loans[Late_Fees] )

Average Interest Rate = AVERAGE ( Loans[Interest_Rate] )

Late Payment % =
DIVIDE (
    CALCULATE ( COUNTROWS ( Loans ), Loans[Late_Fees] > 0 ),
    COUNTROWS ( Loans ),
    0
)
```

Format **Late Payment %** as a percentage and **Average Interest Rate** with 2 decimals
(the column already holds percent values such as 9.25).

Optional extras that use the EMI table:

```DAX
Outstanding Principal = SUM ( Loans[Outstanding_Principal] )

Late Instalments = CALCULATE ( COUNTROWS ( EMI_Schedule ), EMI_Schedule[Status] = "Paid Late" )

On-time Rate =
DIVIDE (
    CALCULATE ( COUNTROWS ( EMI_Schedule ), EMI_Schedule[Status] = "Paid" ),
    CALCULATE ( COUNTROWS ( EMI_Schedule ), EMI_Schedule[Status] <> "Due" ),
    0
)
```

Note: the handwritten plan used `Loans[Late_Fee]` in the last measure and `Late_Fees`
elsewhere; the table has one column, **`Late_Fees`**, so both use that name here.

## Suggested visuals
KPI cards for the five measures · Total Principal by Loan_Type (bar) · Late Payment % by
Lender (bar) · EMI collected over time from EMI_Schedule[Paid_Date] (line) · a table of
loans with late fees.
