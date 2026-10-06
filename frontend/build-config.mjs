// Vercel build step: writes config.js from the API_URL environment variable (no localhost hard-coding).
import { writeFileSync } from "node:fs";
const api = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
if (!api) console.warn("API_URL is not set — the web app will call its own origin");
writeFileSync("config.js", `window.GRIDINTEL_CONFIG=${JSON.stringify({ API_URL: api })};\n`);
console.log("config.js written for", api || "(same origin)");
