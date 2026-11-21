# MRVA Two-Session Timing Diagram (GPT-Optimized Format)

## Parameters

```yaml
max_workers: 2          # W
poll_interval_s: 10     # T_poll
job_duration_s: 30      # each sub-job
runtime_window_s: 3600  # T_w
workers: [alpha_1, alpha_2]
```

## Sessions

```yaml
J_1:
  user: U_1
  session_id: 1
  sub_jobs:
    - J_1.1: {session_id: 1, owner: org_a, repo: repo_1}
    - J_1.2: {session_id: 1, owner: org_a, repo: repo_2}
    - J_1.3: {session_id: 1, owner: org_a, repo: repo_3}

J_2:
  user: U_2
  session_id: 2
  sub_jobs:
    - J_2.1: {session_id: 2, owner: org_b, repo: repo_4}
    - J_2.2: {session_id: 2, owner: org_b, repo: repo_5}
    - J_2.3: {session_id: 2, owner: org_b, repo: repo_6}
```

## Components

```
C_1     = Client for U_1
C_2     = Client for U_2
S       = Server (API coordinator + result consumer)
DB      = PostgreSQL
Sigma_L = Scheduler (leader)
Omega   = Argo Workflows
alpha_1 = Worker pod 1
alpha_2 = Worker pod 2
MQ      = RabbitMQ "results" queue
```

---

## Timeline

### t=0s -- U_1 Submits Session J_1

**Messages:**
```
C_1 --submit(Q, R={R_1,R_2,R_3}, u=U_1)--> S
S   --INSERT--> DB
```

**Server actions:**
1. Generate session_id=1 via `SELECT nextval('session_id_seq')`
2. Save query pack to MinIO
3. For each repo in {R_1, R_2, R_3}:
   - INSERT INTO analyze_jobs (session_id, owner, repo, payload)
   - INSERT INTO job_status (session_id, owner, repo, status=0)  -- 0=Pending
   - INSERT INTO job_info (session_id, owner, repo, payload, user_id='U_1',
                            started_at=NULL, completed_at=NULL, argo_workflow_id='')
   - UPSERT INTO job_repo_map (owner, repo)

**DB State at t=0:**

| Table: job_status | session_id | owner | repo   | status  |
|-------------------|------------|-------|--------|---------|
|                   | 1          | org_a | repo_1 | Pending |
|                   | 1          | org_a | repo_2 | Pending |
|                   | 1          | org_a | repo_3 | Pending |

| Table: job_info | session_id | owner | repo   | user_id | started_at | completed_at | argo_workflow_id |
|-----------------|------------|-------|--------|---------|------------|--------------|------------------|
|                 | 1          | org_a | repo_1 | U_1     | NULL       | NULL         | ''               |
|                 | 1          | org_a | repo_2 | U_1     | NULL       | NULL         | ''               |
|                 | 1          | org_a | repo_3 | U_1     | NULL       | NULL         | ''               |

---

### t=10s -- Scheduler Poll Cycle 1

**Messages:**
```
Sigma_L --SELECT pending jobs--> DB
DB      --{J_1.1, J_1.2, J_1.3}--> Sigma_L

Sigma_L --SELECT running jobs--> DB
DB      --{} (W_r=0, W_a=2)--> Sigma_L
```

**Fair Scheduling Decision:**
```yaml
users_with_pending:
  U_1:
    n_r: 0          # running count
    tau: 0           # recent runtime (seconds)
    n_p: 3           # pending count
    pi: (0, 0, -3)   # priority tuple

priority_order: [U_1]   # only user
W_a: 2                  # available slots

round_robin_allocation:
  pass_1:
    U_1: 1 slot -> a_U1=1, remaining=1
  pass_2:
    U_1: 1 slot -> a_U1=2, remaining=0

result:
  U_1: 2 jobs allocated (J_1.1, J_1.2)
```

**Job Submission:**
```
Sigma_L --SubmitWorkflow(J_1.1)--> Omega
Omega   --CreatePod--> alpha_1     # pod starts executing J_1.1
Sigma_L <--workflow_id=omega_1.1-- Omega

Sigma_L --SubmitWorkflow(J_1.2)--> Omega
Omega   --CreatePod--> alpha_2     # pod starts executing J_1.2
Sigma_L <--workflow_id=omega_1.2-- Omega
```

**DB Updates:**
```sql
UPDATE job_status SET status=1 WHERE (1, org_a, repo_1);  -- 1=InProgress
UPDATE job_status SET status=1 WHERE (1, org_a, repo_2);
UPDATE job_info SET started_at='t=10', argo_workflow_id='omega_1.1' WHERE (1, org_a, repo_1);
UPDATE job_info SET started_at='t=10', argo_workflow_id='omega_1.2' WHERE (1, org_a, repo_2);
```

**Argo Status Polling (running workflows):**
```
Sigma_L --GetWorkflowStatus(omega_1.1)--> Omega
Omega   --phase=Pending--> Sigma_L        # just submitted, no change

Sigma_L --GetWorkflowStatus(omega_1.2)--> Omega
Omega   --phase=Pending--> Sigma_L        # just submitted, no change
```

**DB State at t=10:**

| Table: job_status | session_id | owner | repo   | status     |
|-------------------|------------|-------|--------|------------|
|                   | 1          | org_a | repo_1 | InProgress |
|                   | 1          | org_a | repo_2 | InProgress |
|                   | 1          | org_a | repo_3 | Pending    |

| Table: job_info | session_id | owner | repo   | user_id | started_at | completed_at | argo_workflow_id |
|-----------------|------------|-------|--------|---------|------------|--------------|------------------|
|                 | 1          | org_a | repo_1 | U_1     | t=10       | NULL         | omega_1.1        |
|                 | 1          | org_a | repo_2 | U_1     | NULL       | NULL         | omega_1.2        |
|                 | 1          | org_a | repo_3 | U_1     | NULL       | NULL         | ''               |

| Worker  | Job   | Status  |
|---------|-------|---------|
| alpha_1 | J_1.1 | Running |
| alpha_2 | J_1.2 | Running |

---

### t=15s -- U_2 Submits Session J_2

**Messages:**
```
C_2 --submit(Q', R'={R_4,R_5,R_6}, u=U_2)--> S
S   --INSERT--> DB
```

**Server actions:** (identical pattern to t=0, with session_id=2, user_id=U_2)

**DB State at t=15 (new rows only):**

| Table: job_status | session_id | owner | repo   | status  |
|-------------------|------------|-------|--------|---------|
|                   | 2          | org_b | repo_4 | Pending |
|                   | 2          | org_b | repo_5 | Pending |
|                   | 2          | org_b | repo_6 | Pending |

| Table: job_info | session_id | owner | repo   | user_id | started_at | completed_at | argo_workflow_id |
|-----------------|------------|-------|--------|---------|------------|--------------|------------------|
|                 | 2          | org_b | repo_4 | U_2     | NULL       | NULL         | ''               |
|                 | 2          | org_b | repo_5 | U_2     | NULL       | NULL         | ''               |
|                 | 2          | org_b | repo_6 | U_2     | NULL       | NULL         | ''               |

---

### t=20s -- Scheduler Poll Cycle 2

**Messages:**
```
Sigma_L --SELECT running jobs--> DB
DB      --{J_1.1, J_1.2} (W_r=2, W_a=0)--> Sigma_L
```

**Scheduling:** W_a=0, no slots available. Skip fair scheduling.

**Argo Status Polling:**
```
Sigma_L --GetWorkflowStatus(omega_1.1)--> Omega
Omega   --phase=Running--> Sigma_L       # 10s into 30s execution

Sigma_L --GetWorkflowStatus(omega_1.2)--> Omega
Omega   --phase=Running--> Sigma_L
```

No DB changes. Pending jobs {J_1.3, J_2.1, J_2.2, J_2.3} wait.

---

### t=30s -- Scheduler Poll Cycle 3

Same as t=20s. Both workers still executing (20s into 30s execution).

```
Sigma_L polls Argo: J_1.1 Running, J_1.2 Running
W_r=2, W_a=0, no scheduling.
```

---

### t=40s -- J_1.1 and J_1.2 Complete; Scheduler Poll Cycle 4

This is the most complex event. Three things happen in rapid succession:

#### Step 1: Pods Complete and Publish Results

```
alpha_1 --execute(Q, R_1) completes--> result_1.1
alpha_1 --publish(result_1.1)--> MQ ("results" queue)

alpha_2 --execute(Q, R_2) completes--> result_1.2
alpha_2 --publish(result_1.2)--> MQ ("results" queue)
```

#### Step 2: Server Consumes Results from RabbitMQ

```
S <--consume(result_1.1)-- MQ
S --SetResult(J_1.1, result_1.1)--> DB    # INSERT INTO analyze_results
S --SetStatus(J_1.1, Succeeded)--> DB     # UPDATE job_status SET status=2
S --TriggerScheduling()--> Sigma_L        # wake up scheduler

S <--consume(result_1.2)-- MQ
S --SetResult(J_1.2, result_1.2)--> DB
S --SetStatus(J_1.2, Succeeded)--> DB
S --TriggerScheduling()--> Sigma_L
```

**DB updates from result consumption:**
```sql
INSERT INTO analyze_results (session_id, owner, repo, result)
  VALUES (1, 'org_a', 'repo_1', '<sarif_json>');
UPDATE job_status SET status=2 WHERE (1, org_a, repo_1);  -- 2=Succeeded

INSERT INTO analyze_results (session_id, owner, repo, result)
  VALUES (1, 'org_a', 'repo_2', '<sarif_json>');
UPDATE job_status SET status=2 WHERE (1, org_a, repo_2);
```

#### Step 3: Scheduler Runs (triggered or on poll)

```
Sigma_L --SELECT running jobs--> DB
DB      --{} (W_r=0, W_a=2)--> Sigma_L   # both now Succeeded
```

**Fair Scheduling Decision:**
```yaml
users_with_pending:
  U_1:
    n_r: 0
    tau: 60           # two completed 30s jobs within T_w window
    n_p: 1            # only J_1.3 remains
    pi: (0, 60, -1)

  U_2:
    n_r: 0
    tau: 0            # no completed jobs yet
    n_p: 3            # J_2.1, J_2.2, J_2.3 all pending
    pi: (0, 0, -3)

priority_comparison:
  pi(U_2) = (0,  0, -3)   # <-- HIGHER priority (less runtime)
  pi(U_1) = (0, 60, -1)
  # First components tie (both 0)
  # Second component: 0 < 60, so U_2 wins

priority_order: [U_2, U_1]   # U_2 first due to less runtime
W_a: 2

round_robin_allocation:
  pass_1:
    U_2: 1 slot -> a_U2=1, remaining=1
    U_1: 1 slot -> a_U1=1, remaining=0

result:
  U_2: 1 job (J_2.1)    # gets priority position
  U_1: 1 job (J_1.3)
```

**Note on fairness:** U_2 is prioritized because U_1 has already consumed 60s of
compute time (tau=60) while U_2 has consumed 0s. Even though both have n_r=0,
the second component of pi breaks the tie in U_2's favor.

**Job Submission:**
```
Sigma_L --SubmitWorkflow(J_2.1)--> Omega
Omega   --CreatePod--> alpha_1
Sigma_L <--workflow_id=omega_2.1-- Omega

Sigma_L --SubmitWorkflow(J_1.3)--> Omega
Omega   --CreatePod--> alpha_2
Sigma_L <--workflow_id=omega_1.3-- Omega
```

**DB updates:**
```sql
UPDATE job_status SET status=1 WHERE (2, org_b, repo_4);  -- J_2.1 InProgress
UPDATE job_status SET status=1 WHERE (1, org_a, repo_3);  -- J_1.3 InProgress
UPDATE job_info SET started_at='t=40', argo_workflow_id='omega_2.1' WHERE (2, org_b, repo_4);
UPDATE job_info SET started_at='t=40', argo_workflow_id='omega_1.3' WHERE (1, org_a, repo_3);
-- Also set completed_at for finished jobs (from Argo polling or RabbitMQ path):
UPDATE job_info SET completed_at='t=40' WHERE (1, org_a, repo_1);
UPDATE job_info SET completed_at='t=40' WHERE (1, org_a, repo_2);
```

**DB State at t=40:**

| Table: job_status | session_id | owner | repo   | status     |
|-------------------|------------|-------|--------|------------|
|                   | 1          | org_a | repo_1 | Succeeded  |
|                   | 1          | org_a | repo_2 | Succeeded  |
|                   | 1          | org_a | repo_3 | InProgress |
|                   | 2          | org_b | repo_4 | InProgress |
|                   | 2          | org_b | repo_5 | Pending    |
|                   | 2          | org_b | repo_6 | Pending    |

| Table: job_info | session_id | owner | repo   | user_id | started_at | completed_at | argo_workflow_id |
|-----------------|------------|-------|--------|---------|------------|--------------|------------------|
|                 | 1          | org_a | repo_1 | U_1     | t=10       | t=40         | omega_1.1        |
|                 | 1          | org_a | repo_2 | U_1     | t=10       | t=40         | omega_1.2        |
|                 | 1          | org_a | repo_3 | U_1     | t=40       | NULL         | omega_1.3        |
|                 | 2          | org_b | repo_4 | U_2     | t=40       | NULL         | omega_2.1        |
|                 | 2          | org_b | repo_5 | U_2     | NULL       | NULL         | ''               |
|                 | 2          | org_b | repo_6 | U_2     | NULL       | NULL         | ''               |

| Worker  | Job   | Status  |
|---------|-------|---------|
| alpha_1 | J_2.1 | Running |
| alpha_2 | J_1.3 | Running |

---

### t=50s -- Scheduler Poll Cycle 5

```
Sigma_L: W_r=2, W_a=0. No slots.
Argo status: J_2.1 Running, J_1.3 Running.
Pending: {J_2.2, J_2.3}
No changes.
```

---

### t=60s -- Scheduler Poll Cycle 6

Same as t=50s. Workers at 20s into 30s execution.

---

### t=70s -- J_2.1 and J_1.3 Complete; Scheduler Poll Cycle 7

#### Step 1: Pods Complete

```
alpha_1 --execute(Q', R_4) completes--> result_2.1
alpha_1 --publish(result_2.1)--> MQ

alpha_2 --execute(Q, R_3) completes--> result_1.3
alpha_2 --publish(result_1.3)--> MQ
```

#### Step 2: Server Consumes Results

```
S <--consume(result_2.1)-- MQ
S --SetResult(J_2.1)--> DB
S --SetStatus(J_2.1, Succeeded)--> DB
S --TriggerScheduling()--> Sigma_L

S <--consume(result_1.3)-- MQ
S --SetResult(J_1.3)--> DB
S --SetStatus(J_1.3, Succeeded)--> DB
S --TriggerScheduling()--> Sigma_L
```

#### Step 3: Scheduler Runs

```
W_r=0, W_a=2
Pending: {J_2.2, J_2.3} -- only U_2
```

**Fair Scheduling Decision:**
```yaml
users_with_pending:
  U_2:
    n_r: 0
    tau: 30            # one completed 30s job (J_2.1) in window
    n_p: 2
    pi: (0, 30, -2)

# U_1 has NO pending jobs, so not in scheduling consideration.

priority_order: [U_2]
W_a: 2

allocation:
  U_2: min(2, 2) = 2 jobs (J_2.2, J_2.3)
```

**Job Submission:**
```
Sigma_L --SubmitWorkflow(J_2.2)--> Omega --> alpha_1
Sigma_L --SubmitWorkflow(J_2.3)--> Omega --> alpha_2
```

**DB State at t=70:**

| Table: job_status | session_id | owner | repo   | status     |
|-------------------|------------|-------|--------|------------|
|                   | 1          | org_a | repo_1 | Succeeded  |
|                   | 1          | org_a | repo_2 | Succeeded  |
|                   | 1          | org_a | repo_3 | Succeeded  |
|                   | 2          | org_b | repo_4 | Succeeded  |
|                   | 2          | org_b | repo_5 | InProgress |
|                   | 2          | org_b | repo_6 | InProgress |

| Table: job_info | session_id | owner | repo   | user_id | started_at | completed_at | argo_workflow_id |
|-----------------|------------|-------|--------|---------|------------|--------------|------------------|
|                 | 1          | org_a | repo_1 | U_1     | t=10       | t=40         | omega_1.1        |
|                 | 1          | org_a | repo_2 | U_1     | t=10       | t=40         | omega_1.2        |
|                 | 1          | org_a | repo_3 | U_1     | t=40       | t=70         | omega_1.3        |
|                 | 2          | org_b | repo_4 | U_2     | t=40       | t=70         | omega_2.1        |
|                 | 2          | org_b | repo_5 | U_2     | t=70       | NULL         | omega_2.2        |
|                 | 2          | org_b | repo_6 | U_2     | t=70       | NULL         | omega_2.3        |

| Worker  | Job   | Status  |
|---------|-------|---------|
| alpha_1 | J_2.2 | Running |
| alpha_2 | J_2.3 | Running |

---

### t=80s -- Scheduler Poll Cycle 8

```
W_r=2, W_a=0. Argo: both Running. No pending jobs. No changes.
```

---

### t=90s -- Scheduler Poll Cycle 9

Same as t=80s.

---

### t=100s -- J_2.2 and J_2.3 Complete; All Jobs Done

#### Step 1: Pods Complete

```
alpha_1 --execute(Q', R_5) completes--> result_2.2
alpha_1 --publish(result_2.2)--> MQ

alpha_2 --execute(Q', R_6) completes--> result_2.3
alpha_2 --publish(result_2.3)--> MQ
```

#### Step 2: Server Consumes Results

```
S <--consume(result_2.2)-- MQ --> DB (Succeeded)
S <--consume(result_2.3)-- MQ --> DB (Succeeded)
```

#### Step 3: Scheduler Runs

```
W_r=0, W_a=2. No pending jobs. System idle.
```

**Final DB State at t=100:**

| Table: job_status | session_id | owner | repo   | status    |
|-------------------|------------|-------|--------|-----------|
|                   | 1          | org_a | repo_1 | Succeeded |
|                   | 1          | org_a | repo_2 | Succeeded |
|                   | 1          | org_a | repo_3 | Succeeded |
|                   | 2          | org_b | repo_4 | Succeeded |
|                   | 2          | org_b | repo_5 | Succeeded |
|                   | 2          | org_b | repo_6 | Succeeded |

| Table: job_info | session_id | owner | repo   | user_id | started_at | completed_at | argo_workflow_id |
|-----------------|------------|-------|--------|---------|------------|--------------|------------------|
|                 | 1          | org_a | repo_1 | U_1     | t=10       | t=40         | omega_1.1        |
|                 | 1          | org_a | repo_2 | U_1     | t=10       | t=40         | omega_1.2        |
|                 | 1          | org_a | repo_3 | U_1     | t=40       | t=70         | omega_1.3        |
|                 | 2          | org_b | repo_4 | U_2     | t=40       | t=70         | omega_2.1        |
|                 | 2          | org_b | repo_5 | U_2     | t=70       | t=100        | omega_2.2        |
|                 | 2          | org_b | repo_6 | U_2     | t=70       | t=100        | omega_2.3        |

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

| Cycle | Time | W_a | Pending (U_1) | Pending (U_2) | pi(U_1)     | pi(U_2)     | Priority | Allocated               |
|-------|------|-----|---------------|---------------|-------------|-------------|----------|-------------------------|
| 1     | t=10 | 2   | 3             | --            | (0, 0, -3)  | --          | U_1      | U_1: 2 (J_1.1, J_1.2)  |
| 4     | t=40 | 2   | 1             | 3             | (0, 60, -1) | (0, 0, -3)  | U_2>U_1  | U_2: 1, U_1: 1         |
| 7     | t=70 | 2   | 0             | 2             | --          | (0, 30, -2) | U_2      | U_2: 2 (J_2.2, J_2.3)  |

## Message Flow Summary (all messages in order)

```
 #  Time  From     To       Message
 1  t=0   C_1      S        submit(Q, {R_1,R_2,R_3}, U_1)
 2  t=0   S        DB       INSERT jobs J_1.1, J_1.2, J_1.3 (Pending)
 3  t=10  Sigma_L  DB       SELECT pending/running jobs
 4  t=10  Sigma_L  Omega    SubmitWorkflow(J_1.1)
 5  t=10  Omega    alpha_1  CreatePod (execute J_1.1)
 6  t=10  Sigma_L  Omega    SubmitWorkflow(J_1.2)
 7  t=10  Omega    alpha_2  CreatePod (execute J_1.2)
 8  t=10  Sigma_L  DB       UPDATE J_1.1, J_1.2 -> InProgress
 9  t=10  Sigma_L  Omega    GetWorkflowStatus(J_1.1) -> Pending
10  t=10  Sigma_L  Omega    GetWorkflowStatus(J_1.2) -> Pending
11  t=15  C_2      S        submit(Q', {R_4,R_5,R_6}, U_2)
12  t=15  S        DB       INSERT jobs J_2.1, J_2.2, J_2.3 (Pending)
13  t=20  Sigma_L  DB       SELECT running -> W_r=2, W_a=0 (skip)
14  t=20  Sigma_L  Omega    GetWorkflowStatus(J_1.1) -> Running
15  t=20  Sigma_L  Omega    GetWorkflowStatus(J_1.2) -> Running
16  t=30  Sigma_L  DB       SELECT running -> W_r=2, W_a=0 (skip)
17  t=30  Sigma_L  Omega    GetWorkflowStatus(J_1.1) -> Running
18  t=30  Sigma_L  Omega    GetWorkflowStatus(J_1.2) -> Running
19  t=40  alpha_1  MQ       publish(result_1.1)
20  t=40  alpha_2  MQ       publish(result_1.2)
21  t=40  MQ       S        consume(result_1.1)
22  t=40  S        DB       SetResult + SetStatus(J_1.1, Succeeded)
23  t=40  S        Sigma_L  TriggerScheduling()
24  t=40  MQ       S        consume(result_1.2)
25  t=40  S        DB       SetResult + SetStatus(J_1.2, Succeeded)
26  t=40  Sigma_L  DB       SELECT pending/running -> W_a=2
27  t=40  Sigma_L  Omega    SubmitWorkflow(J_2.1) -- U_2 prioritized
28  t=40  Omega    alpha_1  CreatePod (execute J_2.1)
29  t=40  Sigma_L  Omega    SubmitWorkflow(J_1.3)
30  t=40  Omega    alpha_2  CreatePod (execute J_1.3)
31  t=40  Sigma_L  DB       UPDATE J_2.1, J_1.3 -> InProgress
32  t=50  Sigma_L  DB/Omega poll: W_r=2, W_a=0 (skip)
33  t=60  Sigma_L  DB/Omega poll: W_r=2, W_a=0 (skip)
34  t=70  alpha_1  MQ       publish(result_2.1)
35  t=70  alpha_2  MQ       publish(result_1.3)
36  t=70  MQ       S        consume(result_2.1, result_1.3)
37  t=70  S        DB       SetResult + SetStatus -> Succeeded
38  t=70  S        Sigma_L  TriggerScheduling()
39  t=70  Sigma_L  DB       SELECT pending -> {J_2.2, J_2.3}, W_a=2
40  t=70  Sigma_L  Omega    SubmitWorkflow(J_2.2), SubmitWorkflow(J_2.3)
41  t=70  Omega    alpha_1  CreatePod (execute J_2.2)
42  t=70  Omega    alpha_2  CreatePod (execute J_2.3)
43  t=70  Sigma_L  DB       UPDATE J_2.2, J_2.3 -> InProgress
44  t=80  Sigma_L  DB/Omega poll: W_r=2, W_a=0 (skip)
45  t=90  Sigma_L  DB/Omega poll: W_r=2, W_a=0 (skip)
46  t=100 alpha_1  MQ       publish(result_2.2)
47  t=100 alpha_2  MQ       publish(result_2.3)
48  t=100 MQ       S        consume(result_2.2, result_2.3)
49  t=100 S        DB       SetResult + SetStatus -> Succeeded
50  t=100 Sigma_L  DB       All Succeeded, no pending. System idle.
```
