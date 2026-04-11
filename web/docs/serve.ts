// Simple static file server for the built docs site.
// Astro's dev/preview servers have SPA routing bugs — this serves
// the pre-built dist/ directory correctly with proper MIME types.

const port = 4321;

Bun.serve({
  port,
  async fetch(req) {
    let path = new URL(req.url).pathname;

    // Directory → index.html
    if (path.endsWith("/")) path += "index.html";
    if (!path.includes(".")) path += "/index.html";

    const file = Bun.file(`./dist${path}`);
    if (await file.exists()) {
      return new Response(file);
    }

    // Try 404 page
    const notFound = Bun.file("./dist/404.html");
    if (await notFound.exists()) {
      return new Response(notFound, { status: 404 });
    }
    return new Response("Not found", { status: 404 });
  },
});

console.log(`Docs serving at http://127.0.0.1:${port}/`);
