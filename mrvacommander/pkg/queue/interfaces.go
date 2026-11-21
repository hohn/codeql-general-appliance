package queue

type Queue interface {
	Jobs() chan AnalyzeJob
	Results() chan AnalyzeResult
	Close()
}

// QueueWithSync extends Queue with synchronous publishing capabilities
type QueueWithSync interface {
	Queue
	PublishResultSync(result AnalyzeResult) error
}
