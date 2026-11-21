# cga view

`cga view` captures the rendered CGA composite dashboard and exports the
captures as one self-contained HTML replay. Each capture stores the system
header plus all ten workflow overviews and detail fragments, so the replay
needs no CGA or MRVA process and still lets you select each component's detail
panel.

Capture one live state (ports come from the standard `CGA_*_PORT` variables):

```sh
cga view --dump /tmp/cga-dashboard.jsonl \
  --capture --label "cgamr status --name bob-1"
```

Export and open the capture:

```sh
cga view --dump /tmp/cga-dashboard.jsonl \
  --export replay.html
chromium-browser replay.html
```

The HTML contains the dashboard CSS, every rendered fragment, and the replay
driver inline. Drag the progress slider on the left, scroll over it, or use the
arrow, Home, and End keys. Captured detail panels are read-only. The upper-right
theme control switches between the original dark palette and a
colorblind-friendly light palette without changing layout or control shapes. The
browser retains the choice locally for both the live dashboard and replay.
The live composite page server sends `Cache-Control: no-store` (plus compatible
legacy headers) for every response, so an ordinary reload always fetches the
current HTML, generated configuration, CSS, and JavaScript.

`mrva-flow.sh` captures after every successful workflow command and exports its
final replay. The deprecated two-user `sample-05-i` retains the older
numbered-script capture mechanism for reference.
