import assert from "node:assert/strict";
import test from "node:test";

const templateRoot = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the EcoEvidence workbench", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>EcoEvidence · 文献证据召回工作台<\/title>/i);
  assert.match(html, /EcoEvidence/);
  assert.match(html, /研究需求/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/i);
});

test("starter preview was removed", async () => {
  await assert.rejects(
    import(new URL("../app/_sites-preview/SkeletonPreview.tsx", templateRoot)),
  );
});
