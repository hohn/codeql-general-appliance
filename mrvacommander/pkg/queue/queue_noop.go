package queue

// NoopQueue is a Queue / QueueWithSync that discards everything.
//
// The queue in the original architecture existed only to (1) deliver
// result notifications back to the server, which in turn (2) woke the
// pool manager. Both are now redundant: agents persist results directly
// to PostgreSQL (SetResultAndStatus + CompleteJob), and the pool manager
// ticks on its own timer. So the broker was dropped entirely and this
// no-op queue is the only implementation, used by every mode:
// PublishResultSync is a no-op and Results() returns a channel that is
// never written to.
type NoopQueue struct {
	jobs    chan AnalyzeJob    // never written to; allocated so reads block forever
	results chan AnalyzeResult // ditto
}

// NewNoopQueue returns a queue that drops everything.
func NewNoopQueue() *NoopQueue {
	return &NoopQueue{
		jobs:    make(chan AnalyzeJob),
		results: make(chan AnalyzeResult),
	}
}

// Jobs returns a channel that is never written to. Reads block forever.
// Standalone mode doesn't use the queue for job dispatch (agents poll
// state.ClaimJob directly).
func (q *NoopQueue) Jobs() chan AnalyzeJob { return q.jobs }

// Results returns a channel that is never written to. The server's
// ConsumeResults loop will block here harmlessly; the pool manager
// drives scheduling on its own periodic tick instead.
func (q *NoopQueue) Results() chan AnalyzeResult { return q.results }

// Close is a no-op; the channels are deliberately left open so
// blocking receivers stay blocked rather than spinning on zero values.
func (q *NoopQueue) Close() {}

// PublishResultSync silently discards the result. The agent has
// already persisted the result via state.SetResultAndStatus (writing
// analyze_results + job_status) and state.CompleteJob before reaching
// this call, so dropping the notification only affects latency of the
// next scheduler tick.
func (q *NoopQueue) PublishResultSync(_ AnalyzeResult) error { return nil }
