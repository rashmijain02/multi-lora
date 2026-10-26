---
id: finance-approvals
version: 1
owner: daniel-okafor-cfo
parameters:
  po_tolerance_percent: 1.0
  approval_tiers:
    - max_amount: 5000
      approvers: [budget owner]
    - max_amount: 25000
      approvers: [budget owner, CFO]
    - max_amount: null
      approvers: [CFO, CEO]
---
# Finance approval policy

1. An invoice may proceed only if it matches its purchase order within the tolerance.
   A larger difference requires a corrected invoice or an approved PO change.
2. Approval tiers are cumulative: every listed approver must sign in the finance system.
3. Email is never an approval record. Drafts may recommend; they never approve.
4. Late-fee pressure does not change the controls.
