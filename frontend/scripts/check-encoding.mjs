import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const files = [
  "src/app/AccountGate.tsx",
  "src/app/page.tsx",
  "src/app/ResultsPanel.tsx",
  "src/app/AgentStudio.tsx",
  "src/app/AppIcon.tsx",
  "src/app/layout.tsx",
  "src/app/globals.css",
  "src/app/results.css",
  "src/app/agent-studio.css",
];
const mojibake = [
  String.fromCodePoint(0x00e2, 0x0153), // Common mojibake prefix for check/sparkle symbols.
  String.fromCodePoint(0x00e2, 0x2020), // Common mojibake prefix for arrows.
  String.fromCodePoint(0x00c2, 0x00b7), // Misdecoded middle dot.
  String.fromCodePoint(0x00e3, 0x20ac), // Misdecoded ideographic spaces.
  String.fromCodePoint(0x00ef, 0x00bc), // Misdecoded full-width punctuation.
];

let failed = false;
for (const file of files) {
  const bytes = await readFile(resolve(root, file));
  let source;
  try {
    source = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    console.error(`${file}: source is not valid UTF-8`);
    failed = true;
    continue;
  }
  const matches = mojibake.filter((sequence) => source.includes(sequence));
  if (matches.length) {
    console.error(`${file}: contains a known corrupted text sequence`);
    failed = true;
  }
  if (file === "src/app/layout.tsx" && !/<meta\s+charSet=["']utf-8["']\s*\/>/i.test(source)) {
    console.error(`${file}: missing explicit UTF-8 character set metadata`);
    failed = true;
  }
}

if (failed) process.exitCode = 1;
else console.log(`Encoding check passed for ${files.length} frontend files.`);
