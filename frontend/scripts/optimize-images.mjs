// Script to convert genre PNG images to optimized WebP format
// Output goes to public/images/genres/ for Next.js static export

import sharp from 'sharp';
import { stat } from 'fs/promises';
import { join, basename, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

const IMAGES = [
  { src: join(ROOT, 'images', 'sf.png'),      dest: join(ROOT, 'public', 'images', 'genres', 'sf.webp') },
  { src: join(ROOT, 'images', 'fantasy.png'), dest: join(ROOT, 'public', 'images', 'genres', 'fantasy.webp') },
  { src: join(ROOT, 'images', 'horror.png'),  dest: join(ROOT, 'public', 'images', 'genres', 'horror.webp') },
];

const QUALITY = 80;
const MAX_WIDTH = 1024;

async function fileSize(path) {
  const s = await stat(path);
  return s.size;
}

function kb(bytes) {
  return (bytes / 1024).toFixed(1) + ' KB';
}

async function optimizeImage({ src, dest }) {
  const srcSize = await fileSize(src);

  await sharp(src)
    .resize({ width: MAX_WIDTH, withoutEnlargement: true })
    .webp({ quality: QUALITY })
    .toFile(dest);

  const destSize = await fileSize(dest);
  const ratio = ((1 - destSize / srcSize) * 100).toFixed(1);

  console.log(
    `${basename(src)} -> ${basename(dest)}: ${kb(srcSize)} -> ${kb(destSize)} (-${ratio}%)`
  );
}

async function main() {
  console.log(`Converting images to WebP (quality=${QUALITY}, maxWidth=${MAX_WIDTH}px)...\n`);
  for (const img of IMAGES) {
    await optimizeImage(img);
  }
  console.log('\nDone.');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
