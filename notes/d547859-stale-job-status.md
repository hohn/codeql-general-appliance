# d547859 stale `job_status` rows

Observed and verified on 2026-08-05.

## Informal summary

The motivating question was whether stale PostgreSQL `job_status` rows can
reproduce the historical two-wave zero-runner stall without stopping either
server.

Yes. Four orphan rows marked Queued are sufficient in the historical code. The
rows do not need matching sessions, job payloads, job information, workers, or
workflows.

## Historical reproduction

Branch: `repro/d547859-stale-job-status`

Commit: `4aa3336`

Command:

```bash
cd server-commander
CODEQL_JAVA_HOME=/usr ./run-d547-two-wave.sh stale-queued exactly-one
```

The scenario first completes wave 1 and waits for all four workers to exit. It
then inserts:

```text
session_id = -547859
owner      = stale-job-status
repo       = orphan-1 through orphan-4
status     = Queued
```

These rows exist only in `job_status`. Wave 2 is then delivered exactly once:
Alice submits through server B and Bob through server A. Both servers remain
running.

The observed stalled state was:

```text
wave2_pending=4 stale_queued=4 agents=0
```

PostgreSQL showed four successful wave-1 jobs, four orphan Queued rows, and all
four legitimate wave-2 jobs still Pending. Both server PIDs were alive.

The historical scheduler calculated global capacity as:

```text
available = max_workers - busy_workers - all_queued_status_rows
          = 4 - 0 - 4
          = 0
```

`GetQueuedJobCount` counted every Queued `job_status` row without requiring a
matching `analyze_jobs` row. Each pool cycle therefore returned before selecting
the legitimate Pending jobs.

The harness deleted only the four synthetic status rows as a control. Scheduling
resumed on the next pool cycle, four fresh workers completed wave 2, and all
eight results downloaded.

Evidence:

```text
/tmp/mrva-d547-two-wave/stale-queued-exactly-one/evidence-stale-queued.txt
/tmp/mrva-d547-two-wave/stale-queued-exactly-one/evidence-final.txt
```

## Verification branch

Branch: `verify/d547859-stale-job-status`

Based on master at `a017bb8`.

Command:

```bash
CODEQL_JAVA_HOME=/usr \
  cga/system-tests/run-system-08/run stale-status-recovery
```

### Initial master result

The first run against unchanged master failed. Demand-based scaling prevented
the old zero-runner shape but did not make orphan statuses harmless:

1. `GetQueuedJobCount` treated the four orphan rows as demand and spawned four
   workers.
2. `ClaimJob` selected the first Queued status before checking for a matching
   payload.
3. Loading that payload failed with:

   ```text
   ClaimJob: get analyze_job: no rows in result set
   ```

4. The transaction rolled back, leaving the same orphan first in queue order.
5. Workers repeatedly failed, exited idle, and were replaced. Legitimate wave-2
   jobs did not complete.

The 30-second diagnostic run accumulated 20 worker rows while four live workers
continued failing against the same orphan statuses.

### Fix

The verification branch changes both relevant state queries:

- `GetQueuedJobCount` counts only Queued rows that join a real `analyze_jobs`
  payload.
- `ClaimJob` selects only Queued rows that join a real `analyze_jobs` payload.

The orphan rows are not deleted or silently repaired. They remain available for
inspection but are excluded from executable demand.

### Final result

The exact scenario then passed:

```text
sessions:                    4/4
succeeded job rows:          8/8
result rows:                 8/8
downloaded archives:         8/8
orphan queued rows retained: 4/4
manual stale-row deletion:   0
PASS
```

Wave 2 used four fresh workers and completed while all four orphan Queued
statuses remained in PostgreSQL. Neither server was stopped.

## Conclusion

The historical scheduler could be indefinitely suppressed by arbitrary Queued
values in `job_status`. Demand-based worker spawning alone did not fully solve
malformed orphan state because workers could still select a status with no
executable payload.

The verification branch establishes a stronger invariant: only a `job_status`
row backed by `analyze_jobs` counts as queued demand or can be claimed. Orphan
status rows therefore cannot suppress or poison valid work.

# Appendix
## Branch status

| Branch                            | Commit    | Status                                                                    |
| --------------------------------- | --------- | ------------------------------------------------------------------------- |
| `repro/d547859-stale-job-status`  | `4aa3336` | Contains the historical scheduler and reproduces the orphan-Queued stall. |
| `verify/d547859-stale-job-status` | `d668662` | Contains the regression and verified fix.                                 |
| `master`                          | `39394d4` | Contains the same fix and regression as the verification branch.          |

The intended alignment is therefore: the error remains reproducible only on the
`repro/` branch; both the `verify/` branch and `master` exclude orphan status
rows from queued demand and worker claims.


## Formal state model

Let a job key be

$$
k = (s, o, r)
$$

where $s$ is a session ID, $o$ an owner, and $r$ a repository. Define:

$$
\begin{aligned}
J &= \{k : k \text{ has a row in } \texttt{analyze\_jobs}\}, \\
S(k) &\in \{\mathsf{Pending},\mathsf{Queued},\mathsf{InProgress},
                 \mathsf{Succeeded},\ldots\}, \\
Q &= \{k : S(k)=\mathsf{Queued}\}, \\
Q_v &= Q \cap J, \\
O &= Q \setminus J, \\
B &= \text{number of Busy workers}, \\
W &= \text{configured maximum workers}.
\end{aligned}
$$

Thus $Q_v$ is executable queued work and $O$ is the set of orphan Queued status
rows. In this experiment:

$$
W=4,\qquad |O|=4.
$$

Let $P_2$ be the four legitimate wave-2 jobs. Immediately after delivery:

$$
|P_2|=4,\qquad B=0,\qquad |Q_v|=0,\qquad |O|=4.
$$

### Historical scheduler

The historical capacity calculation was

$$
A_{\mathrm{old}} = W-B-|Q|.
$$

Because $Q=Q_v\mathbin{\dot\cup}O$,

$$
A_{\mathrm{old}}
  = 4-0-(0+4)
  = 0.
$$

The Pending-to-Queued transition was enabled only when $A_{\mathrm{old}}>0$.
Therefore

$$
(|P_2|,|Q_v|,|O|,B)=(4,0,4,0)
\longrightarrow (4,0,4,0).
$$

This is a fixed point while the orphan rows persist:

$$
\forall n\ge 0,\qquad T_{\mathrm{old}}^n(4,0,4,0)=(4,0,4,0).
$$

No server failure is required. Both pool managers repeatedly observe the same
global PostgreSQL state and compute zero available capacity.

### Demand-based pool before the orphan-row fix

Demand-based scaling changed the worker target to

$$
R_{\mathrm{old}}=\min(W,B+|Q|).
$$

For the orphan state,

$$
R_{\mathrm{old}}=\min(4,0+4)=4,
$$

so four workers were spawned. However, the claim operation selected

$$
o=\min_{\mathrm{lex}} Q.
$$

The synthetic orphan keys used session ID $-547859$, so an orphan sorted before
every legitimate positive session ID. Since $o\notin J$, payload lookup was
undefined:

$$
\operatorname{payload}(o)=\bot.
$$

The claim transaction therefore rolled back:

$$
\mathsf{Queued}
\xrightarrow{\text{select }o}
\xrightarrow{\operatorname{payload}(o)=\bot}
\mathsf{rollback}.
$$

Rollback preserved the original state:

$$
S(o)=\mathsf{Queued},\qquad Q'=Q.
$$

Every worker selected the same first orphan again. This produced a livelock:

$$
Q \xrightarrow{\mathsf{ClaimJob}} Q
  \xrightarrow{\mathsf{ClaimJob}} Q
  \xrightarrow{\mathsf{ClaimJob}} \cdots
$$

Workers existed, but no valid job made progress.

### Corrected scheduler and claim relation

The fix replaces every queued-demand and queued-claim domain $Q$ with
$Q_v=Q\cap J$:

$$
A_{\mathrm{new}}=W-B-|Q_v|,
$$

$$
R_{\mathrm{new}}=\min(W,B+|Q_v|),
$$

$$
\mathsf{Claimable}=Q_v.
$$

The complete corrected evolution is:

$$
\begin{aligned}
x_0 &: (|P_2|,|Q_v|,|O|,B)=(4,0,4,0), \\
A_{\mathrm{new}}(x_0) &= 4-0-0=4, \\
x_0 &\xrightarrow{\mathsf{queue}} x_1=(0,4,4,0), \\
R_{\mathrm{new}}(x_1) &= \min(4,0+4)=4, \\
x_1 &\xrightarrow{\mathsf{spawn+claim}} x_2=(0,0,4,4), \\
x_2 &\xrightarrow{\mathsf{complete}} x_3=(0,0,4,0).
\end{aligned}
$$

At $x_3$, all four wave-2 jobs are Succeeded. The orphan set is deliberately
unchanged:

$$
O_3=O_0,\qquad |O_3|=4.
$$

Therefore the safety property established by the regression is:

$$
O\cap J=\varnothing
\implies
\left(
  O\text{ neither contributes to demand nor belongs to the claim domain}
\right).
$$
