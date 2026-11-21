# d547859 two-wave queue stall

Observed and rechecked on 2026-08-05.

## Scenario

The scenario uses two standalone server instances and two workload waves. Each
wave has two logical requests, one for `alice` and one for `bob`. Each request
contains two repositories, for four jobs per wave.

Delivery is **exactly one**: each logical request is sent once to one server,
not copied to both servers. Wave 1 sends Alice to server A and Bob to server B.
After all four workers exit, wave 2 swaps the endpoints.

The fault is injected only in wave 2:

1. Hold PostgreSQL advisory lock `73001` so request delivery and scheduling
   cannot interleave.
2. Deliver both requests and confirm that they produce exactly two sessions and
   four Pending jobs.
3. Release the advisory lock.
4. Let the scheduling server transition all four jobs from Pending to Queued.
5. Pause that server before its next scheduling action and kill it with
   `SIGKILL`.

The marker used for step 5 is enabled only when
`MRVA_TEST_QUEUE_TRANSITION_MARKER` is set. It is inert in ordinary runs.

## Historical reproduction

Branch: `repro/d547859-two-wave`

Command:

```bash
cd server-commander
CODEQL_JAVA_HOME=/usr ./run-d547-two-wave.sh queue-crash exactly-one
```

Wave 1 completed normally. Four workers processed sessions 1 and 2, produced
four results, and exited.

Wave 2 delivered Alice once to server B and Bob once to server A, creating
sessions 3 and 4. Server A acquired the queue advisory lock, selected all four
jobs, committed their Pending-to-Queued transitions, and paused before calling
`SubmitWorkflow`.

Routing requests to different servers is not sufficient to create this state.
Both replicas share PostgreSQL, and the advisory lock ensures that only one pool
manager performs the global queue transition at a time. If that process
continues running, it proceeds to `SubmitWorkflow` regardless of which replica
received each request.

The required fault is interruption of the scheduling process inside the
non-atomic window after the Queued transaction commits and before workflows are
created. The harness uses `SIGKILL` to place the failure deterministically, but
an unplanned process crash, OOM kill, container or host restart, or host loss at
the same point can produce it. Split request routing only affects which replica
is likely to enter the window; it does not replace the interruption.

Killing server A at that point produced:

```text
queued=4 blank_workflow=4 pending=0 agents=0
```

The surviving server continued a pool cycle every second, but each cycle
computed:

```text
available = max_workers - busy_workers - queued_jobs
          = 4 - 0 - 4
          = 0
```

It returned before selecting work. The workflow reconciler also ignored every
job because no `SubmitWorkflow` call had produced a workflow ID. The jobs were
neither Pending work nor reconcilable workflows, so no code path could recover
them.

The historical harness then applied a control, changing those four statuses from
Queued back to Pending. The surviving server immediately submitted four
workflows, four fresh workers completed the jobs, and all eight results across
both waves downloaded successfully. The control demonstrated that the queued
rows, rather than request delivery or worker startup, caused the stall.

Historical evidence:

```text
/tmp/mrva-d547-two-wave/queue-crash-exactly-one/evidence-stranded.txt
/tmp/mrva-d547-two-wave/queue-crash-exactly-one/evidence-final.txt
```

## Verification on current master

Verification branch: `verify/d547859-two-wave-fix`, based on master at
`a380efb`.

Command:

```bash
CODEQL_JAVA_HOME=/usr cga/system-tests/run-system-08/run crash-recovery
```

The test recreated the same boundary. Wave 1 completed, all four workers exited,
and there were no pending spawns. In wave 2, server A was killed after all four
jobs became Queued but before any workers existed:

```text
queued=4 blank_workflow=4 agents=0
```

Unlike the historical run, the harness did not modify those rows. Server B
acquired the scheduler lease about one lease interval later and recovered the
work directly:

```text
Scheduler lock acquired ... server=server-b
Scaling up workers to_spawn=4 alive=0 pending=0 target=4
```

The four new workers claimed the existing Queued jobs from PostgreSQL. Both
wave-2 sessions succeeded, all four archives downloaded through the surviving
server, and final verification reported:

```text
sessions:                    4/4
succeeded job rows:          8/8
result rows:                 8/8
downloaded archives:         8/8
pending spawns before wave2: 0
worker generations disjoint: yes
spawn log counts:            server-a=0 server-b=4
PASS
```

## Why current master recovers

The relevant fix is the demand-based worker pool introduced by `091d3a8`
(`Replace push-based Argo scheduling with demand-based worker pool`), together
with the current scheduler lease failover.

Historically, queueing and per-job workflow submission were one non-atomic
sequence owned by a particular server:

```text
Pending -> Queued -> SubmitWorkflow(job) -> save workflow ID
```

If that server died between the first two durable actions, the surviving server
had no workflow to reconcile and treated the Queued rows as consumed capacity.

Current code separates durable job demand from worker creation:

```text
queueJobs:    Pending -> Queued
scaleWorkers: target = min(max_workers, busy + queued)
workers:      atomically claim any Queued job from PostgreSQL
```

A queued job no longer needs a per-job workflow ID. After failover, the new
leader sees four queued jobs, calculates a target of four workers, starts four
generic workers, and those workers claim the old leader's queued rows. The
Queued state is therefore recoverable demand rather than a stranded intermediate
state.

The result verifies the intended invariant: an exactly-one two-wave request
pattern can lose the scheduling server after Pending-to-Queued and still
complete without resetting or resubmitting any job.
