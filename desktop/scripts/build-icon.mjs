// Rasterize resources/icon.svg into the Windows .ico used by the app and installer.
// Run with: npm run icon
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pngToIco from "png-to-ico";
import sharp from "sharp";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = path.join(root, "resources", "icon.svg");
const svg = fs.readFileSync(source);

const sizes = [16, 24, 32, 48, 64, 128, 256];

async function render(size) {
  return sharp(svg, { density: 512 })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toBuffer();
}

const buffers = [];
for (const size of sizes) {
  buffers.push(await render(size));
}

const ico = await pngToIco(buffers);
fs.writeFileSync(path.join(root, "resources", "icon.ico"), ico);
fs.writeFileSync(path.join(root, "resources", "icon.png"), await render(512));

console.log(`icon.ico  ${ico.length} bytes (${sizes.join(", ")})`);
console.log("icon.png  512x512");
