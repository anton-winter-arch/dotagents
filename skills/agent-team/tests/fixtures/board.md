# EPIC-NNNN01
- [ ] Reporting Platform Stability

**DESCRIPTION**
````
**OUTCOME**:
Make scheduled reporting dependable enough to run unattended.

**OUT OF SCOPE**:
- Report content changes

**END STATE**:
- Scheduled reports complete within their window

**COMPLETION EVIDENCE**:
- Run history for one observation period
````

---

## FEATURE-NNNN02
- [ ] Report Delivery Reliability
- Parent: EPIC-NNNN01

**DESCRIPTION**
````
**PURPOSE**:
Confirm scheduled reports are produced and delivered on time.

**KEY ACTIVITIES**:
- [ ] Record job outcomes

**ACCEPTANCE CRITERIA**:
- [ ] Every run records its outcome (STORY-NNNN03)

**PRIMARY OWNER**: Platform Engineer
````

---

### STORY-NNNN03
- [ ] Record scheduler job outcomes
- Parent: FEATURE-NNNN02
- State: Resolved

**DESCRIPTION**
````
**USER STORY**:
As the platform team, we need each scheduler run to record its outcome.

**DEVELOPMENT APPROACH**:
- [ ] Add an outcome column
- [ ] Write the outcome on completion
````

**ACCEPTANCE CRITERIA**
````
- [ ] Every run writes an outcome
- [ ] Outcomes survive a restart

**VALIDATION**:
- [ ] outcome_test.py passes

**Definition of Done**:
- [ ] Runbook updated
````

**COMMENTS**
````
- 2026-11-22T10:00:00Z (none) -> New by seat
- 2026-11-22T10:05:00Z New -> Active by seat
- 2026-11-22T11:00:00Z Active -> Resolved by seat
````
