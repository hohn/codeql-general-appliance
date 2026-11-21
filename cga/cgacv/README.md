# cgacv — CVE specification handler

`cgacv` imports deterministic JSON produced by a human or external LLM,
validates it, selects CVEs, and expands each selected CVE into the required
`vulnerable`, `patched`, and `most-recent` work items.

```sh
cgacv import spec.json
cgacv validate
cgacv select [--cve CVE-ID]
cgacv expand
cgacv info
cgacv serve
```

The component records `cgacv-spec`, `cgacv-selection`, and
`cgacv-work-items`. LLM invocation is intentionally outside CGA preparation: any producer
may create the versioned JSON input, while `cgacv` remains deterministic.
