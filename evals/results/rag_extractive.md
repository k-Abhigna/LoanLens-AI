# Q&A assistant evaluation

Answers: `extractive` · extractor: `rules` · 40 applications · 1080 questions · k=4

| Metric | Value |
|---|---|
| Retrieval hit@4 | 100.0% |
| Mean reciprocal rank | 0.989 |
| Answer accuracy | 96.1% |
| Says "not found" when the file has no answer | 100.0% |
| Adversarial questions blocked | 100.0% |
| Passages leaked from other applications | 0 of 1729 |
| Average answer time | 4.5 ms |

## Answer accuracy by source

| Source | Accuracy |
|---|---|
| application | 96.3% |
| bank_statement | 100.0% |
| payslip | 86.3% |
| policy | 100.0% |
| underwriting | 100.0% |

## Failures (17)

| Application | Question | Expected | Answer |
|---|---|---|---|
| DEMO0001 | What is the net pay on the payslip? | 6,664.44 | AI recommendation for this application: REVIEW (risk score 80 out of 100, confidence low). Reasons why: Income could not be verified; name_match: Application / payslip / bank: Maria Diaz / None / None |
| DEMO0001 | What gross pay does the payslip show? | 9,208.33 | AI recommendation for this application: REVIEW (risk score 80 out of 100, confidence low). Reasons why: Income could not be verified; name_match: Application / payslip / bank: Maria Diaz / None / None |
| DEMO0002 | How much money does the applicant want to borrow? | 18,250.00 | Loan application applicant name: Brian Perry (extracted from application.pdf by the rules extractor, read with pdf text) [1] |
| DEMO0004 | How much money does the applicant want to borrow? | 26,750.00 | Loan application applicant name: Kevin Wells (extracted from application.pdf by the rules extractor, read with pdf text) [1] |
| DEMO0011 | How much money does the applicant want to borrow? | 23,250.00 | Loan application applicant name: Steven Sanders (extracted from application.pdf by the rules extractor, read with pdf text) [1] |
| DEMO0014 | How much money does the applicant want to borrow? | 34,000.00 | Loan application applicant name: Maria Nguyen (extracted from application.pdf by the rules extractor, read with pdf text) [1] |
| DEMO0019 | What is the net pay on the payslip? | 4,738.62 | AI recommendation for this application: REVIEW (risk score 80 out of 100, confidence low). Reasons why: Income could not be verified; name_match: Application / payslip / bank: Linda Brooks / None / No |
| DEMO0019 | What gross pay does the payslip show? | 6,583.33 | Payslip employer: PAY SLIP (extracted from payslip.pdf by the rules extractor, read with pdf text) [2] |
| DEMO0026 | What is the net pay on the payslip? | 8,448.54 | AI recommendation for this application: REVIEW (risk score 80 out of 100, confidence low). Reasons why: Income could not be verified; name_match: Application / payslip / bank: Daniel Price / None / No |
| DEMO0026 | What gross pay does the payslip show? | 11,875.00 | Payslip employer: PAY SLIP (extracted from payslip.pdf by the rules extractor, read with pdf text) [2] |
| DEMO0032 | What is the net pay on the payslip? | 1,848.87 | Payslip employer: PAY SLIP (extracted from payslip_scan.jpg by the rules extractor, read with ocr) [3] |
| DEMO0032 | What gross pay does the payslip show? | 2,541.67 | Gross Earnings [4] Payslip employer: PAY SLIP (extracted from payslip_scan.jpg by the rules extractor, read with ocr) [3] |
| DEMO0033 | How much money does the applicant want to borrow? | 22,750.00 | Loan application applicant name: Steven Bennett (extracted from application.pdf by the rules extractor, read with pdf text) [1] |
| DEMO0037 | What is the net pay on the payslip? | 4,414.40 | AI recommendation for this application: REVIEW (risk score 80 out of 100, confidence low). Reasons why: Income could not be verified; name_match: Application / payslip / bank: Michelle Diaz / None / N |
| DEMO0037 | What gross pay does the payslip show? | 5,666.67 | Payslip employer: PAY SLIP (extracted from payslip.pdf by the rules extractor, read with pdf text) [3] |
| DEMO0038 | How much money does the applicant want to borrow? | 27,250.00 | Loan application applicant name: James Carter (extracted from application.pdf by the rules extractor, read with pdf text) [1] |
| DEMO0038 | What is the net pay on the payslip? | 7,273.46 | Payslip employer: PAY SLIP (extracted from payslip_scan.jpg by the rules extractor, read with ocr) [3] |
