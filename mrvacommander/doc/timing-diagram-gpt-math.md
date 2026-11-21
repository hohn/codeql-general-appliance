# MRVA Two-Session Timing Diagram (GPT-Optimized Format)

## Parameters

| Symbol | Value | Meaning |
|--------|-------|---------|
| \\(W\\) | 2 | max workers |
| \\(T\_{\text{poll}}\\) | 10 s | scheduler poll interval |
| \\(T\_w\\) | 3600 s | runtime window |
| job duration | 30 s | each sub-job |
| workers | \\(\alpha\_1, \alpha\_2\\) | |
| \\(O\\) | \\(O\_a, O\_b\\) | owner (organization) |
| \\(R\\) | \\(R\_1, \ldots, R\_6\\) | repository |
| \\(\sigma\\) | \\(\sigma\_P, \sigma\_I, \sigma\_S\\) | status: Pending, InProgress, Succeeded |

## Sessions

**\\(J\_1\\)** (user \\(U\_1\\), session\_id = 1):

| Job | \\(O\\) | \\(R\\) |
|-----|-----|-----|
| \\(J\_{1.1}\\) | \\(O\_a\\) | \\(R\_1\\) |
| \\(J\_{1.2}\\) | \\(O\_a\\) | \\(R\_2\\) |
| \\(J\_{1.3}\\) | \\(O\_a\\) | \\(R\_3\\) |

**\\(J\_2\\)** (user \\(U\_2\\), session\_id = 2):

| Job | \\(O\\) | \\(R\\) |
|-----|-----|-----|
| \\(J\_{2.1}\\) | \\(O\_b\\) | \\(R\_4\\) |
| \\(J\_{2.2}\\) | \\(O\_b\\) | \\(R\_5\\) |
| \\(J\_{2.3}\\) | \\(O\_b\\) | \\(R\_6\\) |

## Components

| Symbol | Component |
|--------|-----------|
| \\(C\_1\\) | Client for \\(U\_1\\) |
| \\(C\_2\\) | Client for \\(U\_2\\) |
| \\(S\\) | Server (API coordinator + result consumer) |
| DB | PostgreSQL |
| \\(\Sigma\_L\\) | Scheduler (leader) |
| \\(\Omega\\) | Argo Workflows |
| \\(\alpha\_1\\) | Worker pod 1 |
| \\(\alpha\_2\\) | Worker pod 2 |
| MQ | RabbitMQ "results" queue |

---

## Timeline

### \\(t{=}0\\) — \\(U\_1\\) Submits Session \\(J\_1\\)

**Messages:**
- \\(C\_1 \to S\\): submit(\\(\mathcal{Q}\\), \\(\\{R\_1, R\_2, R\_3\\}\\), \\(U\_1\\))
- \\(S \to \text{DB}\\): INSERT \\(J\_{1.1}\\), \\(J\_{1.2}\\), \\(J\_{1.3}\\)

**Server actions:**
1. Generate session\_id = 1 via `SELECT nextval('session_id_seq')`
2. Save query pack to MinIO
3. For each repo in \\(\\{R\_1, R\_2, R\_3\\}\\):
   - INSERT INTO analyze\_jobs (session\_id, \\(O\\), \\(R\\), payload)
   - INSERT INTO job\_status (session\_id, \\(O\\), \\(R\\), \\(\sigma = \sigma\_P\\))
   - INSERT INTO job\_info (session\_id, \\(O\\), \\(R\\), payload, user\_id = '\\(U\_1\\)',
                            \\(t^s\\) = NULL, \\(t^c\\) = NULL, \\(\omega\\) = '')
   - UPSERT INTO job\_repo\_map (\\(O\\), \\(R\\))

**DB State at \\(t{=}0\\):**

| Table: job\_status | session\_id | \\(O\\)   | \\(R\\)   | \\(\sigma\\)   |
|--------------------|-------------|-------|-------|------------|
|                    | 1           | \\(O\_a\\) | \\(R\_1\\) | \\(\sigma\_P\\) |
|                    | 1           | \\(O\_a\\) | \\(R\_2\\) | \\(\sigma\_P\\) |
|                    | 1           | \\(O\_a\\) | \\(R\_3\\) | \\(\sigma\_P\\) |

| Table: job\_info | session\_id | \\(O\\) | \\(R\\) | user\_id | \\(t^s\\) | \\(t^c\\) | \\(\omega\\) |
|------------------|-------------|-----|-----|---------|-------|-------|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(U\_1\\) | NULL | NULL | '' |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(U\_1\\) | NULL | NULL | '' |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(U\_1\\) | NULL | NULL | '' |

---

### \\(t{=}10\\) — Scheduler Poll Cycle 1

**Messages:**
- \\(\Sigma\_L \to \text{DB}\\): SELECT pending, running jobs
- \\(\text{DB} \to \Sigma\_L\\): \\(\\{J\_{1.1}, J\_{1.2}, J\_{1.3}\\}\\); \\(W\_r{=}0\\), \\(W\_a{=}2\\), pending: 3

**Fair Scheduling Decision:**

Only one user has pending jobs:

\\[\pi(U\_1) = (n\_r,\\; \tau,\\; {-}n\_p) = (0,\\; 0,\\; {-}3)\\]

Allocate \\(\min(W\_a, n\_p) = \min(2, 3) = 2\\) slots:
- Pass 1: \\(U\_1\\) gets 1 slot → \\(a\_{U\_1}{=}1\\), remaining = 1
- Pass 2: \\(U\_1\\) gets 1 slot → \\(a\_{U\_1}{=}2\\), remaining = 0

Result: \\(J\_{1.1} \to \alpha\_1\\), \\(J\_{1.2} \to \alpha\_2\\)

**Job Submission:**
- \\(\Sigma\_L \to \Omega\\): SubmitWorkflow(\\(J\_{1.1}\\)) → \\(\omega\_{1.1}\\)
- \\(\Omega \to \alpha\_1\\): CreatePod (execute \\(J\_{1.1}\\))
- \\(\Sigma\_L \to \Omega\\): SubmitWorkflow(\\(J\_{1.2}\\)) → \\(\omega\_{1.2}\\)
- \\(\Omega \to \alpha\_2\\): CreatePod (execute \\(J\_{1.2}\\))

**DB Updates:**
```sql
UPDATE job_status SET status=1 WHERE (1, O_a, R_1);  -- sigma_I
UPDATE job_status SET status=1 WHERE (1, O_a, R_2);
UPDATE job_info SET started_at='t=10', argo_workflow_id='omega_1.1' WHERE (1, O_a, R_1);
UPDATE job_info SET started_at='t=10', argo_workflow_id='omega_1.2' WHERE (1, O_a, R_2);
```

**Argo Status Polling:**
- \\(\Sigma\_L \to \Omega\\): GetWorkflowStatus(\\(\omega\_{1.1}\\)) → Pending
- \\(\Sigma\_L \to \Omega\\): GetWorkflowStatus(\\(\omega\_{1.2}\\)) → Pending

**DB State at \\(t{=}10\\):**

| Table: job\_status | session\_id | \\(O\\) | \\(R\\) | \\(\sigma\\) |
|--------------------|-------------|-----|-----|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(\sigma\_I\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(\sigma\_I\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(\sigma\_P\\) |

| Table: job\_info | session\_id | \\(O\\) | \\(R\\) | user\_id | \\(t^s\\) | \\(t^c\\) | \\(\omega\\) |
|------------------|-------------|-----|-----|---------|-------|-------|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(U\_1\\) | \\(t{=}10\\) | NULL | \\(\omega\_{1.1}\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(U\_1\\) | NULL | NULL | \\(\omega\_{1.2}\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(U\_1\\) | NULL | NULL | '' |

| Worker | Job | Status |
|--------|-----|--------|
| \\(\alpha\_1\\) | \\(J\_{1.1}\\) | Running |
| \\(\alpha\_2\\) | \\(J\_{1.2}\\) | Running |

---

### \\(t{=}15\\) — \\(U\_2\\) Submits Session \\(J\_2\\)

**Messages:**
- \\(C\_2 \to S\\): submit(\\(\mathcal{Q}'\\), \\(\\{R\_4, R\_5, R\_6\\}\\), \\(U\_2\\))
- \\(S \to \text{DB}\\): INSERT \\(J\_{2.1}\\), \\(J\_{2.2}\\), \\(J\_{2.3}\\)

**Server actions:** identical pattern to \\(t{=}0\\), with session\_id = 2, user\_id = \\(U\_2\\).

**DB State at \\(t{=}15\\) (new rows only):**

| Table: job\_status | session\_id | \\(O\\) | \\(R\\) | \\(\sigma\\) |
|--------------------|-------------|-----|-----|----------|
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(\sigma\_P\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(\sigma\_P\\) |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(\sigma\_P\\) |

| Table: job\_info | session\_id | \\(O\\) | \\(R\\) | user\_id | \\(t^s\\) | \\(t^c\\) | \\(\omega\\) |
|------------------|-------------|-----|-----|---------|-------|-------|----------|
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(U\_2\\) | NULL | NULL | '' |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(U\_2\\) | NULL | NULL | '' |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(U\_2\\) | NULL | NULL | '' |

---

### \\(t{=}20\\) — Scheduler Poll Cycle 2

**Messages:**
- \\(\Sigma\_L \to \text{DB}\\): SELECT running → \\(W\_r{=}2\\), \\(W\_a{=}0\\)

**Scheduling:** \\(W\_a{=}0\\), no slots available. Skip fair scheduling.

**Argo Status Polling:**
- \\(\Sigma\_L \to \Omega\\): GetWorkflowStatus(\\(\omega\_{1.1}\\)) → Running (10 s into 30 s execution)
- \\(\Sigma\_L \to \Omega\\): GetWorkflowStatus(\\(\omega\_{1.2}\\)) → Running

No DB changes. Pending jobs \\(\\{J\_{1.3}, J\_{2.1}, J\_{2.2}, J\_{2.3}\\}\\) wait.

---

### \\(t{=}30\\) — Scheduler Poll Cycle 3

Same as \\(t{=}20\\). Both workers still executing (20 s into 30 s execution).

\\(\Sigma\_L\\) polls \\(\Omega\\): \\(J\_{1.1}\\) Running, \\(J\_{1.2}\\) Running. \\(W\_r{=}2\\), \\(W\_a{=}0\\), no scheduling.

---

### \\(t{=}40\\) — \\(J\_{1.1}\\) and \\(J\_{1.2}\\) Complete; Scheduler Poll Cycle 4

This is the most complex event. Three things happen in rapid succession:

#### Step 1: Pods Complete and Publish Results

- \\(\alpha\_1\\): execute(\\(\mathcal{Q}\\), \\(R\_1\\)) completes → \\(\text{result}\_{1.1}\\)
- \\(\alpha\_1 \to \text{MQ}\\): publish(\\(\text{result}\_{1.1}\\))
- \\(\alpha\_2\\): execute(\\(\mathcal{Q}\\), \\(R\_2\\)) completes → \\(\text{result}\_{1.2}\\)
- \\(\alpha\_2 \to \text{MQ}\\): publish(\\(\text{result}\_{1.2}\\))

#### Step 2: Server Consumes Results from RabbitMQ

- \\(\text{MQ} \to S\\): consume(\\(\text{result}\_{1.1}\\))
- \\(S \to \text{DB}\\): SetResult(\\(J\_{1.1}\\), \\(\text{result}\_{1.1}\\)) — INSERT INTO analyze\_results
- \\(S \to \text{DB}\\): SetStatus(\\(J\_{1.1}\\), \\(\sigma\_S\\))
- \\(S \to \Sigma\_L\\): TriggerScheduling()
- \\(\text{MQ} \to S\\): consume(\\(\text{result}\_{1.2}\\))
- \\(S \to \text{DB}\\): SetResult(\\(J\_{1.2}\\), \\(\text{result}\_{1.2}\\))
- \\(S \to \text{DB}\\): SetStatus(\\(J\_{1.2}\\), \\(\sigma\_S\\))
- \\(S \to \Sigma\_L\\): TriggerScheduling()

**DB updates from result consumption:**
```sql
INSERT INTO analyze_results (session_id, O, R, result)
  VALUES (1, 'O_a', 'R_1', '<sarif_json>');
UPDATE job_status SET status=2 WHERE (1, O_a, R_1);  -- sigma_S

INSERT INTO analyze_results (session_id, O, R, result)
  VALUES (1, 'O_a', 'R_2', '<sarif_json>');
UPDATE job_status SET status=2 WHERE (1, O_a, R_2);
```

#### Step 3: Scheduler Runs (triggered or on poll)

- \\(\Sigma\_L \to \text{DB}\\): SELECT running → \\(W\_r{=}0\\), \\(W\_a{=}2\\) (both now \\(\sigma\_S\\))

**Fair Scheduling Decision — \\(U\_2\\) prioritized:**

\\[\pi(U\_1) = (n\_r,\\; \tau,\\; {-}n\_p) = (0,\\; 60,\\; {-}1)\\]
\\[\pi(U\_2) = (n\_r,\\; \tau,\\; {-}n\_p) = (0,\\; 0,\\; {-}3)\\]

Priority comparison: first components tie (both 0); second component \\(\tau\_{U\_2}{=}0 < \tau\_{U\_1}{=}60\\), so \\(U\_2\\) wins.

Priority order: \\([U\_2, U\_1]\\).  \\(W\_a{=}2\\).

Round-robin allocation:
- Pass 1: \\(U\_2\\) gets 1 slot → \\(a\_{U\_2}{=}1\\); \\(U\_1\\) gets 1 slot → \\(a\_{U\_1}{=}1\\); remaining = 0

Result: \\(J\_{2.1} \to \alpha\_1\\), \\(J\_{1.3} \to \alpha\_2\\)

**Note on fairness:** \\(U\_2\\) is prioritized because \\(U\_1\\) has already consumed 60 s of
compute time (\\(\tau{=}60\\)) while \\(U\_2\\) has consumed 0 s. Even though both have \\(n\_r{=}0\\),
the second component of \\(\pi\\) breaks the tie in \\(U\_2\\)'s favor.

**Job Submission:**
- \\(\Sigma\_L \to \Omega\\): SubmitWorkflow(\\(J\_{2.1}\\)) → \\(\omega\_{2.1}\\)
- \\(\Omega \to \alpha\_1\\): CreatePod
- \\(\Sigma\_L \to \Omega\\): SubmitWorkflow(\\(J\_{1.3}\\)) → \\(\omega\_{1.3}\\)
- \\(\Omega \to \alpha\_2\\): CreatePod

**DB updates:**
```sql
UPDATE job_status SET status=1 WHERE (2, O_b, R_4);  -- J_{2.1} sigma_I
UPDATE job_status SET status=1 WHERE (1, O_a, R_3);  -- J_{1.3} sigma_I
UPDATE job_info SET started_at='t=40', argo_workflow_id='omega_2.1' WHERE (2, O_b, R_4);
UPDATE job_info SET started_at='t=40', argo_workflow_id='omega_1.3' WHERE (1, O_a, R_3);
-- Also set completed_at for finished jobs:
UPDATE job_info SET completed_at='t=40' WHERE (1, O_a, R_1);
UPDATE job_info SET completed_at='t=40' WHERE (1, O_a, R_2);
```

**DB State at \\(t{=}40\\):**

| Table: job\_status | session\_id | \\(O\\) | \\(R\\) | \\(\sigma\\) |
|--------------------|-------------|-----|-----|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(\sigma\_S\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(\sigma\_S\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(\sigma\_I\\) |
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(\sigma\_I\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(\sigma\_P\\) |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(\sigma\_P\\) |

| Table: job\_info | session\_id | \\(O\\) | \\(R\\) | user\_id | \\(t^s\\) | \\(t^c\\) | \\(\omega\\) |
|------------------|-------------|-----|-----|---------|-------|-------|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(U\_1\\) | \\(t{=}10\\) | \\(t{=}40\\) | \\(\omega\_{1.1}\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(U\_1\\) | \\(t{=}10\\) | \\(t{=}40\\) | \\(\omega\_{1.2}\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(U\_1\\) | \\(t{=}40\\) | NULL | \\(\omega\_{1.3}\\) |
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(U\_2\\) | \\(t{=}40\\) | NULL | \\(\omega\_{2.1}\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(U\_2\\) | NULL | NULL | '' |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(U\_2\\) | NULL | NULL | '' |

| Worker | Job | Status |
|--------|-----|--------|
| \\(\alpha\_1\\) | \\(J\_{2.1}\\) | Running |
| \\(\alpha\_2\\) | \\(J\_{1.3}\\) | Running |

---

### \\(t{=}50\\) — Scheduler Poll Cycle 5

\\(\Sigma\_L\\): \\(W\_r{=}2\\), \\(W\_a{=}0\\). No slots.
Argo status: \\(J\_{2.1}\\) Running, \\(J\_{1.3}\\) Running.
Pending: \\(\\{J\_{2.2}, J\_{2.3}\\}\\). No changes.

---

### \\(t{=}60\\) — Scheduler Poll Cycle 6

Same as \\(t{=}50\\). Workers at 20 s into 30 s execution.

---

### \\(t{=}70\\) — \\(J\_{2.1}\\) and \\(J\_{1.3}\\) Complete; Scheduler Poll Cycle 7

#### Step 1: Pods Complete

- \\(\alpha\_1\\): execute(\\(\mathcal{Q}'\\), \\(R\_4\\)) completes → \\(\text{result}\_{2.1}\\)
- \\(\alpha\_1 \to \text{MQ}\\): publish(\\(\text{result}\_{2.1}\\))
- \\(\alpha\_2\\): execute(\\(\mathcal{Q}\\), \\(R\_3\\)) completes → \\(\text{result}\_{1.3}\\)
- \\(\alpha\_2 \to \text{MQ}\\): publish(\\(\text{result}\_{1.3}\\))

#### Step 2: Server Consumes Results

- \\(\text{MQ} \to S\\): consume(\\(\text{result}\_{2.1}\\))
- \\(S \to \text{DB}\\): SetResult + SetStatus(\\(J\_{2.1}\\), \\(\sigma\_S\\))
- \\(S \to \Sigma\_L\\): TriggerScheduling()
- \\(\text{MQ} \to S\\): consume(\\(\text{result}\_{1.3}\\))
- \\(S \to \text{DB}\\): SetResult + SetStatus(\\(J\_{1.3}\\), \\(\sigma\_S\\))
- \\(S \to \Sigma\_L\\): TriggerScheduling()

#### Step 3: Scheduler Runs

\\(W\_r{=}0\\), \\(W\_a{=}2\\). Pending: \\(\\{J\_{2.2}, J\_{2.3}\\}\\) — only \\(U\_2\\).

**Fair Scheduling Decision:**

\\[\pi(U\_2) = (0,\\; 30,\\; {-}2)\\]

\\(U\_1\\) has no pending jobs, so not in scheduling consideration.

Priority order: \\([U\_2]\\). \\(W\_a{=}2\\).

Allocation: \\(\min(W\_a, n\_p) = \min(2, 2) = 2\\)

Result: \\(J\_{2.2} \to \alpha\_1\\), \\(J\_{2.3} \to \alpha\_2\\)

**Job Submission:**
- \\(\Sigma\_L \to \Omega\\): SubmitWorkflow(\\(J\_{2.2}\\)) → \\(\alpha\_1\\)
- \\(\Sigma\_L \to \Omega\\): SubmitWorkflow(\\(J\_{2.3}\\)) → \\(\alpha\_2\\)

**DB State at \\(t{=}70\\):**

| Table: job\_status | session\_id | \\(O\\) | \\(R\\) | \\(\sigma\\) |
|--------------------|-------------|-----|-----|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(\sigma\_S\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(\sigma\_S\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(\sigma\_S\\) |
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(\sigma\_S\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(\sigma\_I\\) |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(\sigma\_I\\) |

| Table: job\_info | session\_id | \\(O\\) | \\(R\\) | user\_id | \\(t^s\\) | \\(t^c\\) | \\(\omega\\) |
|------------------|-------------|-----|-----|---------|-------|-------|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(U\_1\\) | \\(t{=}10\\) | \\(t{=}40\\) | \\(\omega\_{1.1}\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(U\_1\\) | \\(t{=}10\\) | \\(t{=}40\\) | \\(\omega\_{1.2}\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(U\_1\\) | \\(t{=}40\\) | \\(t{=}70\\) | \\(\omega\_{1.3}\\) |
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(U\_2\\) | \\(t{=}40\\) | \\(t{=}70\\) | \\(\omega\_{2.1}\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(U\_2\\) | \\(t{=}70\\) | NULL | \\(\omega\_{2.2}\\) |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(U\_2\\) | \\(t{=}70\\) | NULL | \\(\omega\_{2.3}\\) |

| Worker | Job | Status |
|--------|-----|--------|
| \\(\alpha\_1\\) | \\(J\_{2.2}\\) | Running |
| \\(\alpha\_2\\) | \\(J\_{2.3}\\) | Running |

---

### \\(t{=}80\\) — Scheduler Poll Cycle 8

\\(W\_r{=}2\\), \\(W\_a{=}0\\). Argo: both Running. No pending jobs. No changes.

---

### \\(t{=}90\\) — Scheduler Poll Cycle 9

Same as \\(t{=}80\\).

---

### \\(t{=}100\\) — \\(J\_{2.2}\\) and \\(J\_{2.3}\\) Complete; All Jobs Done

#### Step 1: Pods Complete

- \\(\alpha\_1\\): execute(\\(\mathcal{Q}'\\), \\(R\_5\\)) completes → \\(\text{result}\_{2.2}\\)
- \\(\alpha\_1 \to \text{MQ}\\): publish(\\(\text{result}\_{2.2}\\))
- \\(\alpha\_2\\): execute(\\(\mathcal{Q}'\\), \\(R\_6\\)) completes → \\(\text{result}\_{2.3}\\)
- \\(\alpha\_2 \to \text{MQ}\\): publish(\\(\text{result}\_{2.3}\\))

#### Step 2: Server Consumes Results

- \\(\text{MQ} \to S\\): consume(\\(\text{result}\_{2.2}\\), \\(\text{result}\_{2.3}\\))
- \\(S \to \text{DB}\\): SetResult + SetStatus → \\(\sigma\_S\\)

#### Step 3: Scheduler Runs

\\(W\_r{=}0\\), \\(W\_a{=}2\\). No pending jobs. System idle.

**Final DB State at \\(t{=}100\\):**

| Table: job\_status | session\_id | \\(O\\) | \\(R\\) | \\(\sigma\\) |
|--------------------|-------------|-----|-----|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(\sigma\_S\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(\sigma\_S\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(\sigma\_S\\) |
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(\sigma\_S\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(\sigma\_S\\) |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(\sigma\_S\\) |

| Table: job\_info | session\_id | \\(O\\) | \\(R\\) | user\_id | \\(t^s\\) | \\(t^c\\) | \\(\omega\\) |
|------------------|-------------|-----|-----|---------|-------|-------|----------|
| | 1 | \\(O\_a\\) | \\(R\_1\\) | \\(U\_1\\) | \\(t{=}10\\) | \\(t{=}40\\) | \\(\omega\_{1.1}\\) |
| | 1 | \\(O\_a\\) | \\(R\_2\\) | \\(U\_1\\) | \\(t{=}10\\) | \\(t{=}40\\) | \\(\omega\_{1.2}\\) |
| | 1 | \\(O\_a\\) | \\(R\_3\\) | \\(U\_1\\) | \\(t{=}40\\) | \\(t{=}70\\) | \\(\omega\_{1.3}\\) |
| | 2 | \\(O\_b\\) | \\(R\_4\\) | \\(U\_2\\) | \\(t{=}40\\) | \\(t{=}70\\) | \\(\omega\_{2.1}\\) |
| | 2 | \\(O\_b\\) | \\(R\_5\\) | \\(U\_2\\) | \\(t{=}70\\) | \\(t{=}100\\) | \\(\omega\_{2.2}\\) |
| | 2 | \\(O\_b\\) | \\(R\_6\\) | \\(U\_2\\) | \\(t{=}70\\) | \\(t{=}100\\) | \\(\omega\_{2.3}\\) |

---

## Worker Gantt Chart

```
Time:    0    10   15   20   30   40   50   60   70   80   90   100
         |    |    |    |    |    |    |    |    |    |    |    |
alpha_1: .... [===J_1.1(U_1)====] [===J_2.1(U_2)====] [===J_2.2(U_2)====]
alpha_2: .... [===J_1.2(U_1)====] [===J_1.3(U_1)====] [===J_2.3(U_2)====]
                   ^                   ^                   ^
                   |                   |                   |
              U_2 submits         Fair sched:          Only U_2
              J_2 at t=15        U_2 prioritized      has pending
```

## Summary of Fair Scheduling Decisions

| Cycle | Time | \\(W\_a\\) | Pending (\\(U\_1\\)) | Pending (\\(U\_2\\)) | \\(\pi(U\_1)\\) | \\(\pi(U\_2)\\) | Priority | Allocated |
|-------|------|-------|-----------------|-----------------|-------------|-------------|----------|-----------|
| 1 | \\(t{=}10\\) | 2 | 3 | — | \\((0,\\; 0,\\; {-}3)\\) | — | \\(U\_1\\) | \\(U\_1\\): 2 (\\(J\_{1.1}\\), \\(J\_{1.2}\\)) |
| 4 | \\(t{=}40\\) | 2 | 1 | 3 | \\((0,\\; 60,\\; {-}1)\\) | \\((0,\\; 0,\\; {-}3)\\) | \\(U\_2 > U\_1\\) | \\(U\_2\\): 1, \\(U\_1\\): 1 |
| 7 | \\(t{=}70\\) | 2 | 0 | 2 | — | \\((0,\\; 30,\\; {-}2)\\) | \\(U\_2\\) | \\(U\_2\\): 2 (\\(J\_{2.2}\\), \\(J\_{2.3}\\)) |

## Message Flow Summary (all messages in order)

| # | Time | From | To | Message |
|---|------|------|----|---------|
| 1 | \\(t{=}0\\) | \\(C\_1\\) | \\(S\\) | submit(\\(\mathcal{Q}\\), \\(\\{R\_1, R\_2, R\_3\\}\\), \\(U\_1\\)) |
| 2 | \\(t{=}0\\) | \\(S\\) | DB | INSERT \\(J\_{1.1}\\), \\(J\_{1.2}\\), \\(J\_{1.3}\\) (\\(\sigma\_P\\)) |
| 3 | \\(t{=}10\\) | \\(\Sigma\_L\\) | DB | SELECT pending/running jobs |
| 4 | \\(t{=}10\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | SubmitWorkflow(\\(J\_{1.1}\\)) |
| 5 | \\(t{=}10\\) | \\(\Omega\\) | \\(\alpha\_1\\) | CreatePod (execute \\(J\_{1.1}\\)) |
| 6 | \\(t{=}10\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | SubmitWorkflow(\\(J\_{1.2}\\)) |
| 7 | \\(t{=}10\\) | \\(\Omega\\) | \\(\alpha\_2\\) | CreatePod (execute \\(J\_{1.2}\\)) |
| 8 | \\(t{=}10\\) | \\(\Sigma\_L\\) | DB | UPDATE \\(J\_{1.1}\\), \\(J\_{1.2}\\) → \\(\sigma\_I\\) |
| 9 | \\(t{=}10\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | GetWorkflowStatus(\\(J\_{1.1}\\)) → Pending |
| 10 | \\(t{=}10\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | GetWorkflowStatus(\\(J\_{1.2}\\)) → Pending |
| 11 | \\(t{=}15\\) | \\(C\_2\\) | \\(S\\) | submit(\\(\mathcal{Q}'\\), \\(\\{R\_4, R\_5, R\_6\\}\\), \\(U\_2\\)) |
| 12 | \\(t{=}15\\) | \\(S\\) | DB | INSERT \\(J\_{2.1}\\), \\(J\_{2.2}\\), \\(J\_{2.3}\\) (\\(\sigma\_P\\)) |
| 13 | \\(t{=}20\\) | \\(\Sigma\_L\\) | DB | SELECT running → \\(W\_r{=}2\\), \\(W\_a{=}0\\) (skip) |
| 14 | \\(t{=}20\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | GetWorkflowStatus(\\(J\_{1.1}\\)) → Running |
| 15 | \\(t{=}20\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | GetWorkflowStatus(\\(J\_{1.2}\\)) → Running |
| 16 | \\(t{=}30\\) | \\(\Sigma\_L\\) | DB | SELECT running → \\(W\_r{=}2\\), \\(W\_a{=}0\\) (skip) |
| 17 | \\(t{=}30\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | GetWorkflowStatus(\\(J\_{1.1}\\)) → Running |
| 18 | \\(t{=}30\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | GetWorkflowStatus(\\(J\_{1.2}\\)) → Running |
| 19 | \\(t{=}40\\) | \\(\alpha\_1\\) | MQ | publish(\\(\text{result}\_{1.1}\\)) |
| 20 | \\(t{=}40\\) | \\(\alpha\_2\\) | MQ | publish(\\(\text{result}\_{1.2}\\)) |
| 21 | \\(t{=}40\\) | MQ | \\(S\\) | consume(\\(\text{result}\_{1.1}\\)) |
| 22 | \\(t{=}40\\) | \\(S\\) | DB | SetResult + SetStatus(\\(J\_{1.1}\\), \\(\sigma\_S\\)) |
| 23 | \\(t{=}40\\) | \\(S\\) | \\(\Sigma\_L\\) | TriggerScheduling() |
| 24 | \\(t{=}40\\) | MQ | \\(S\\) | consume(\\(\text{result}\_{1.2}\\)) |
| 25 | \\(t{=}40\\) | \\(S\\) | DB | SetResult + SetStatus(\\(J\_{1.2}\\), \\(\sigma\_S\\)) |
| 26 | \\(t{=}40\\) | \\(\Sigma\_L\\) | DB | SELECT pending/running → \\(W\_a{=}2\\) |
| 27 | \\(t{=}40\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | SubmitWorkflow(\\(J\_{2.1}\\)) — \\(U\_2\\) prioritized |
| 28 | \\(t{=}40\\) | \\(\Omega\\) | \\(\alpha\_1\\) | CreatePod (execute \\(J\_{2.1}\\)) |
| 29 | \\(t{=}40\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | SubmitWorkflow(\\(J\_{1.3}\\)) |
| 30 | \\(t{=}40\\) | \\(\Omega\\) | \\(\alpha\_2\\) | CreatePod (execute \\(J\_{1.3}\\)) |
| 31 | \\(t{=}40\\) | \\(\Sigma\_L\\) | DB | UPDATE \\(J\_{2.1}\\), \\(J\_{1.3}\\) → \\(\sigma\_I\\) |
| 32 | \\(t{=}50\\) | \\(\Sigma\_L\\) | DB/\\(\Omega\\) | poll: \\(W\_r{=}2\\), \\(W\_a{=}0\\) (skip) |
| 33 | \\(t{=}60\\) | \\(\Sigma\_L\\) | DB/\\(\Omega\\) | poll: \\(W\_r{=}2\\), \\(W\_a{=}0\\) (skip) |
| 34 | \\(t{=}70\\) | \\(\alpha\_1\\) | MQ | publish(\\(\text{result}\_{2.1}\\)) |
| 35 | \\(t{=}70\\) | \\(\alpha\_2\\) | MQ | publish(\\(\text{result}\_{1.3}\\)) |
| 36 | \\(t{=}70\\) | MQ | \\(S\\) | consume(\\(\text{result}\_{2.1}\\), \\(\text{result}\_{1.3}\\)) |
| 37 | \\(t{=}70\\) | \\(S\\) | DB | SetResult + SetStatus → \\(\sigma\_S\\) |
| 38 | \\(t{=}70\\) | \\(S\\) | \\(\Sigma\_L\\) | TriggerScheduling() |
| 39 | \\(t{=}70\\) | \\(\Sigma\_L\\) | DB | SELECT pending → \\(\\{J\_{2.2}, J\_{2.3}\\}\\), \\(W\_a{=}2\\) |
| 40 | \\(t{=}70\\) | \\(\Sigma\_L\\) | \\(\Omega\\) | SubmitWorkflow(\\(J\_{2.2}\\)), SubmitWorkflow(\\(J\_{2.3}\\)) |
| 41 | \\(t{=}70\\) | \\(\Omega\\) | \\(\alpha\_1\\) | CreatePod (execute \\(J\_{2.2}\\)) |
| 42 | \\(t{=}70\\) | \\(\Omega\\) | \\(\alpha\_2\\) | CreatePod (execute \\(J\_{2.3}\\)) |
| 43 | \\(t{=}70\\) | \\(\Sigma\_L\\) | DB | UPDATE \\(J\_{2.2}\\), \\(J\_{2.3}\\) → \\(\sigma\_I\\) |
| 44 | \\(t{=}80\\) | \\(\Sigma\_L\\) | DB/\\(\Omega\\) | poll: \\(W\_r{=}2\\), \\(W\_a{=}0\\) (skip) |
| 45 | \\(t{=}90\\) | \\(\Sigma\_L\\) | DB/\\(\Omega\\) | poll: \\(W\_r{=}2\\), \\(W\_a{=}0\\) (skip) |
| 46 | \\(t{=}100\\) | \\(\alpha\_1\\) | MQ | publish(\\(\text{result}\_{2.2}\\)) |
| 47 | \\(t{=}100\\) | \\(\alpha\_2\\) | MQ | publish(\\(\text{result}\_{2.3}\\)) |
| 48 | \\(t{=}100\\) | MQ | \\(S\\) | consume(\\(\text{result}\_{2.2}\\), \\(\text{result}\_{2.3}\\)) |
| 49 | \\(t{=}100\\) | \\(S\\) | DB | SetResult + SetStatus → \\(\sigma\_S\\) |
| 50 | \\(t{=}100\\) | \\(\Sigma\_L\\) | DB | All \\(\sigma\_S\\), no pending. System idle. |
