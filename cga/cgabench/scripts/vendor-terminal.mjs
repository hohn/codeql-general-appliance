import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const destination = join(root, "cgabench/static/vendor");
await mkdir(destination, { recursive: true });
for (const [source, name] of [
  ["@xterm/xterm/lib/xterm.js", "xterm.js"],
  ["@xterm/xterm/css/xterm.css", "xterm.css"],
  ["@xterm/xterm/LICENSE", "xterm-LICENSE"],
  ["@xterm/addon-fit/lib/addon-fit.js", "addon-fit.js"],
  ["@xterm/addon-fit/LICENSE", "addon-fit-LICENSE"],
]) {
  await copyFile(join(root, "node_modules", source), join(destination, name));
}
