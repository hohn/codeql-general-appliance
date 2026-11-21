// Package sysviewui holds the shared assets for the MRVA system-state view,
// so both the live server dashboard and the offline replay tool render from
// the same CSS and JavaScript.
package sysviewui

import _ "embed"

//go:embed style.css
var styleCSS string

// Style is the full <style> block for the sysview page.
var Style = "<style>\n" + styleCSS + "</style>\n"

// RenderJS defines the shared rendering functions and per-view state. It
// expects the host page to provide #meta, #servers, #jobs and #workers
// elements, and exposes render(data) which paints one sysViewSnapshot.
//
//go:embed render.js
var RenderJS string
